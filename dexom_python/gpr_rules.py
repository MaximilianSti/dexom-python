
import re
import argparse
import numpy as np
import pandas as pd
from symengine import sympify, Add, Mul, Max, Min
from dexom_python.model_functions import read_model, save_reaction_weights


def replace_MulMax_AddMin(expression):
    if expression.is_Atom:
        return expression
    else:
        replaced_args = (replace_MulMax_AddMin(arg) for arg in expression.args)
        if expression.__class__ == Mul:
            return Max(*replaced_args)
        elif expression.__class__ == Add:
            return Min(*replaced_args)
        else:
            return expression.func(*replaced_args)


def expression2qualitative(expression_file, column_idx, percentage=25, method="keep", save=True, outpath="geneweights"):
    """

    Parameters
    ----------
    expression_file: path to file containing gene IDs in the first column and gene expression values in a later column
    column_idx: column indexes containing gene expression values to be transformed. If None, all columns will be transformed
    percentage: percentage of genes to be used for determining high/low gene expression
    method: one of "max", "mean" or "keep". chooses how to deal with genes containing multiple conflicting expression values
    save
    outpath

    Returns
    -------

    """

    if type(column_idx) == int:
        column_idx = list(range(column_idx))

    df = pd.read_csv(expression_file, index_col=0)
    cutoff = 1/(percentage/100)
    colnames = df.columns[column_idx]
    for col in colnames:
        if method == "max":
            for x in set(df.index):
                df[col][x] = df[col][x].max()
        elif method == "mean":
            for x in set(df.index):
                df[col][x] = df[col][x].mean()

        df.sort_values(col, inplace=True)
        df[col].iloc[:int(len(df)//cutoff)+1] = -1.
        df[col].iloc[int(len(df)//cutoff)+1:int(len(df)*(cutoff-1)//cutoff)] = 0.
        df[col].iloc[int(len(df) * (cutoff-1) // cutoff):] = 1.
    if save:
        df.to_csv(outpath+".csv")
    return df


def prepare_expr_split_gen_list(rxn, modelname):
    if modelname == "recon2":
        expr_split = rxn.gene_reaction_rule.replace("(", "( ").replace(")", " )").split()
        expr_split = [s.replace(':', '_') if ':' in s else s for s in expr_split]
        rxngenes = re.sub('and|or|\(|\)', '', rxn.gene_reaction_rule).split()
        gen_list = set([s.replace(':', '_') for s in rxngenes if ':' in s])
    elif modelname == "recon1":
        expr_split = rxn.gene_reaction_rule.replace("(", "( ").replace(")", " )").split()
        expr_split = ["g_" + s[:-4] if '_' in s else s for s in expr_split]
        rxngenes = re.sub('and|or|\(|\)', '', rxn.gene_reaction_rule).split()
        gen_list = set(["g_" + s[:-4] for s in rxngenes if '_' in s])
    elif modelname == "iMM1865":
        expr_split = rxn.gene_reaction_rule.split()
        expr_split = ["g_" + s if s.isdigit() else s for s in expr_split]
        rxngenes = re.sub('and|or|\(|\)', '', rxn.gene_reaction_rule).split()
        gen_list = set(["g_" + s for s in rxngenes if s.isdigit()])
    elif modelname == "human1":
        expr_split = rxn.gene_reaction_rule.replace("(", "( ").replace(")", " )").split()
        gen_list = set([g.id for g in rxn.genes])
    elif modelname == "zebrafish1":
        expr_split = rxn.gene_reaction_rule.replace("(", "( ").replace(")", " )").split()
        expr_split = [re.sub(':|\.', '_', s) for s in expr_split]
        gen_list = set([re.sub(':|\.', '_', g.id) for g in rxn.genes])
    else:
        print("Modelname not found")
        expr_split = None
        gen_list = None

    return expr_split, gen_list


def apply_gpr(model, gene_weights, modelname, save=True, filename="reaction_weights"):
    """
    Applies the GPR rules from the human-GEM model for creating reaction weights

    Parameters
    ----------
    model: a cobrapy model
    gene_file: the path to a csv file containing gene scores
    gene_weights: a dictionary containing gene IDs & weights
    save: if True, saves the reaction weights as a csv file

    Returns
    -------
    reaction_weights: dict where keys = reaction IDs and values = weights
    """
    reaction_weights = {}
    for rxn in model.reactions:
        if len(rxn.genes) > 0:
            expr_split, gen_list = prepare_expr_split_gen_list(rxn, modelname)
            new_weights = {g: gene_weights.get(g, 0) for g in gen_list}
            negweights = []
            for g, v in new_weights.items():
                if v < 0:
                    new_weights[g] = -v - 1e-15
                    negweights.append(-v)
            expression = ' '.join(expr_split).replace('or', '*').replace('and', '+')
            # weight = sympify(expression).xreplace({Mul: Max}).xreplace({Add: Min})
            weight = replace_MulMax_AddMin(sympify(expression)).subs(new_weights)
            if weight + 1e-15 in negweights:
                weight = -weight - 1e-15
            reaction_weights[rxn.id] = weight
        else:
            reaction_weights[rxn.id] = 0.
    if save:
        save_reaction_weights(reaction_weights, filename+".csv")
    return reaction_weights


if __name__ == "__main__":

    description = "Applies GPR rules to transform gene weights into reaction weights"

    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-m", "--model", help="GEM in json, sbml or matlab format")
    parser.add_argument("-n", "--modelname", help="supported: human1, recon1, recon2, iMM1865")
    parser.add_argument("-g", "--gene_file", help="csv file containing gene identifiers and scores")
    parser.add_argument("-o", "--output", default="reaction_weights",
                        help="Path to which the reaction_weights .csv file is saved")
    parser.add_argument("--gene_ID", default="ID", help="column containing the gene identifiers")
    parser.add_argument("--gene_score", default="t", help="column containing the gene scores")
    args = parser.parse_args()

    model = read_model(args.model)
    model_list = ["human1", "recon1", "recon2", "iMM1865", "zebrafish1"]

    genes = pd.read_csv(args.gene_file)
    gene_weights = pd.Series(genes[args.gene_score], index=genes[args.gene_ID])

    # current behavior: all genes with several different weights are removed
    for x in set(gene_weights.index):
        if type(gene_weights[x]) != np.float64:
            if len(gene_weights[x].value_counts()) > 1:
                gene_weights.pop(x)
    gene_weights = gene_weights.to_dict()

    if args.modelname not in model_list:
        print("Unsupported model. The currently supported models are: human1, recon1, recon2, iMM1865, zebrafish1")
    else:
        reaction_weights = apply_gpr(model=model, gene_weights=gene_weights, modelname=args.modelname, save=True,
                                     filename=args.output)
