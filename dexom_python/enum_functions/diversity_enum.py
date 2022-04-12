
import argparse
import six
import time
import numpy as np
import pandas as pd
from dexom_python.imat import imat, create_partial_variables, create_full_variables, create_new_partial_variables
from dexom_python.result_functions import read_solution, write_solution
from dexom_python.model_functions import load_reaction_weights, read_model, check_model_options
from dexom_python.enum_functions.enumeration import EnumSolution, get_recent_solution_and_iteration
from dexom_python.enum_functions.icut import create_icut_constraint
from dexom_python.enum_functions.maxdist import create_maxdist_constraint, create_maxdist_objective


def diversity_enum(model, reaction_weights, prev_sol, eps=1e-3, thr=1e-5, obj_tol=1e-3, maxiter=10, dist_anneal=0.995,
                   out_path="enum_dexom", icut=True, full=False, save=False):
    """
    diversity-based enumeration
    Parameters
    ----------
    model
    reaction_weights
    prev_sol
    thr
    obj_tol
    maxiter
    dist_anneal
    icut
    only_ones

    model: cobrapy Model
    reaction_weights: dict
        keys = reactions and values = weights
    prev_sol: Solution instance
        a previous imat solution
    threshold: float
        detection threshold of activated reactions
    obj_tol: float
        variance allowed in the objective_values of the solutions
    maxiter: foat
        maximum number of solutions to search for
    dist_anneal: float
        parameter which influences the probability of selecting reactions
    out_path: str
        path to which the results are saved
    icut: bool
        if True, icut constraints are applied
    full: bool
        if True, the full-DEXOM implementation is used
    save: bool
        if True, every individual solution is saved in the iMAT solution format
    Returns
    -------

    """
    tol = model.solver.configuration.tolerances.feasibility
    times = []
    selected_recs = []
    prev_sol_bin = (np.abs(prev_sol.fluxes) >= thr-tol).values.astype(int)
    all_solutions = [prev_sol]
    all_binary = [prev_sol_bin]
    icut_constraints = []

    for rid in reaction_weights.keys():
        if reaction_weights[rid] == 0:
            pass
        elif full and "x_"+rid not in model.solver.variables:
            model = create_full_variables(model=model, reaction_weights=reaction_weights, epsilon=eps, threshold=thr)
            break
        elif not full and "rh_"+rid+"_pos" not in model.solver.variables and "rl_"+rid not in model.solver.variables:
            model = create_new_partial_variables(model=model, reaction_weights=reaction_weights, epsilon=eps,
                                                 threshold=thr)  # uses new variable implementation
            break

    # preserve the optimality of the solution
    opt_const = create_maxdist_constraint(model, reaction_weights, prev_sol, obj_tol, "dexom_optimality", full=full)
    model.solver.add(opt_const)
    for idx in range(1, maxiter+1):
        # if idx == 5:
        #     print("iter5")
        t0 = time.perf_counter()
        if icut:
            # adding the icut constraint to prevent the algorithm from finding duplicate solutions
            const = create_icut_constraint(model, reaction_weights, thr, prev_sol, "icut_"+str(idx), full)
            model.solver.add(const)
            icut_constraints.append(const)

        # randomly selecting reactions which were active in the previous solution
        tempweights = {}
        i = 0
        for rid, weight in six.iteritems(reaction_weights):
            if np.random.random() > dist_anneal**idx and weight != 0:
                tempweights[rid] = weight
                i += 1
        selected_recs.append(i)

        objective = create_maxdist_objective(model, tempweights, prev_sol, prev_sol_bin, full=full)
        model.objective = objective
        try:
            t2 = time.perf_counter()
            print("time before optimizing in iteration "+str(idx)+":", t2-t0)
            with model:
                prev_sol = model.optimize()
            prev_sol_bin = (np.abs(prev_sol.fluxes) >= thr-tol).values.astype(int)
            all_solutions.append(prev_sol)
            all_binary.append(prev_sol_bin)
            if save:
                write_solution(model, prev_sol, thr,
                               filename=out_path+"_solution_"+time.strftime("%Y%m%d-%H%M%S")+".csv")
            t1 = time.perf_counter()
            print("time for optimizing in iteration " + str(idx) + ":", t1 - t2)
            times.append(t1 - t0)
        except:
            print("An error occured in iteration %i of dexom, no solution was returned" % idx)
            times.append(-1)
            prev_sol = all_solutions[-1]
            # break

    model.solver.remove([const for const in icut_constraints if const in model.solver.constraints])
    model.solver.remove(opt_const)
    solution = EnumSolution(all_solutions, all_binary, all_solutions[0].objective_value)

    df = pd.DataFrame({"selected reactions": selected_recs, "time": times})
    sol = pd.DataFrame(solution.binary)

    if save:
        df.to_csv(out_path+time.strftime("%Y%m%d-%H%M%S")+"_results.csv")
        sol.to_csv(out_path+time.strftime("%Y%m%d-%H%M%S")+"_solutions.csv")
    else:
        df.to_csv(out_path+"_results.csv")
        sol.to_csv(out_path+"_solutions.csv")

    return solution


if __name__ == "__main__":
    description = "Performs the diversity-enumeration algorithm"

    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-m", "--model", help="Metabolic model in sbml, matlab, or json format")
    parser.add_argument("-r", "--reaction_weights", default=None,
                        help="Reaction weights in csv format (first row: reaction names, second row: weights)")
    parser.add_argument("-p", "--prev_sol", default=[], help="starting solution or directory of recent solutions")
    parser.add_argument("-e", "--epsilon", type=float, default=1e-3,
                        help="Activation threshold for highly expressed reactions")
    parser.add_argument("--threshold", type=float, default=1e-5, help="Activation threshold for all reactions")
    parser.add_argument("-t", "--timelimit", type=int, default=None, help="Solver time limit")
    parser.add_argument("-i", "--maxiter", type=int, default=10, help="Iteration limit")
    parser.add_argument("--tol", type=float, default=1e-8, help="Solver feasibility tolerance")
    parser.add_argument("--mipgap", type=float, default=1e-6, help="Solver MIP gap tolerance")
    parser.add_argument("--obj_tol", type=float, default=1e-2,
                        help="objective value tolerance, as a fraction of the original value")
    parser.add_argument("-o", "--output", default="div_enum", help="Base name of output files, without format")
    parser.add_argument("-a", "--dist_anneal", type=float, default=0.995, help="annealing distance")
    parser.add_argument("--noicut", action='store_true', help="Use this flag to remove the icut constraint")
    parser.add_argument("--full", action='store_true', help="Use this flag to assign non-zero weights to all reactions")
    parser.add_argument("--save", action='store_true', help="Use this flag to save each individual solution")
    args = parser.parse_args()

    model = read_model(args.model)
    check_model_options(model, timelimit=args.timelimit, feasibility=args.tol, mipgaptol=args.mipgap)

    reaction_weights = {}
    if args.reaction_weights:
        reaction_weights = load_reaction_weights(args.reaction_weights)

    a = args.dist_anneal
    if "." in args.prev_sol:
        prev_sol, prev_bin = read_solution(args.prev_sol, model, reaction_weights)
        model = create_new_partial_variables(model, reaction_weights, epsilon=args.epsilon, threshold=args.threshold)
    elif args.prev_sol:
        prev_sol, i = get_recent_solution_and_iteration(args.prev_sol, args.startsol_num)
        a = a ** i
        model = create_new_partial_variables(model, reaction_weights, epsilon=args.epsilon, threshold=args.threshold)
    else:
        prev_sol = imat(model, reaction_weights, epsilon=args.epsilon, threshold=args.threshold)

    icut = False if args.noicut else True
    save = True if args.save else False
    full = True if args.full else False

    dexom_sol = diversity_enum(model=model, reaction_weights=reaction_weights, prev_sol=prev_sol, thr=args.threshold,
                               maxiter=args.maxiter, obj_tol=args.obj_tol, dist_anneal=a, icut=icut,
                               out_path=args.output, full=args.full, save=save)
