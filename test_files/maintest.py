import cobra

model = cobra.Model("testmodel")
print(model)
model.solver = "cplex"
print(model.solver)
model.add_metabolites([cobra.Metabolite("M")])
rin = cobra.Reaction("in")
rout = cobra.Reaction("out")
model.add_reactions([rin, rout])
rin.add_metabolites({"M":1.})
rout.add_metabolites({"M":-1.})
print(model)
sol = model.optimize()
print(sol)
print(sol.fluxes)