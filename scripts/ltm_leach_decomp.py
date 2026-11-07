"""Where Exp 3's leaching cut comes from: the measured monthly totals and the best-train CMA-ES
schedule (runs/ltm_algos_balanced.json), each at irrigation efficiency 1.0 and 0.80, against the
measured daily replay, on the test windows -> runs/ltm_leach_decomp.json (read by
scripts/ltm_algos_report.py).

    uv run python scripts/ltm_leach_decomp.py
"""
import json, dataclasses, numpy as np
from swat_gym.ltm import econ, practice
from swat_gym.ltm.env import plan_from_x
from swat_gym.ltm.practice import measured_x
from swat_gym.ltm.windows import TEST, TRAIN
from swat_gym.experiments import ltm as L
from swat_gym.experiments.ltm_algos import references
practice.set_irr_eff(0.80)
prices = econ.prices()
_, rs, ref = references(prices, "ltm_exp3")
D = json.load(open("runs/ltm_algos_balanced.json"))
best = lambda a: max(D["algos"][a], key=lambda r: r["picked_train_score"])
cma_x = np.array(best("cma")["test_x"][str(TEST[0])])
P = lambda x, eff: dataclasses.replace(plan_from_x("I", x), irr_eff=eff)
plans = {"default_eff100": P(measured_x("I"), 1.0), "default_eff80": P(measured_x("I"), 0.8),
         "cma_eff80": P(cma_x, 0.8), "cma_eff100": P(cma_x, 1.0)}
eps = dict(zip(plans, L.run_plans(list(plans.values()), TEST, prices)))
n = len(TRAIN)
eps["measured_daily_eff100"] = rs["measured"][n:]
out = {}
for k, e in eps.items():
    e = L._with_score(e, ref, 0.5)
    out[k] = {m: float(np.mean([x[m] for x in e])) for m in ("score", "ry", "no3", "water")}
    out[k]["eff"] = 1.0 if k.endswith("eff100") else 0.8
    print(f"{k:24s}", {m: round(v, 3) for m, v in out[k].items()})
json.dump(out, open("runs/ltm_leach_decomp.json", "w"), indent=1)
