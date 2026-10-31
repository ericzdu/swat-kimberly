"""Author a SWAT+ management schedule (crop + auto-irrigation) into a TxtInOut.

Single crop  -> a flat management.sch (plant -> manure -> harvest+kill), which SWAT+
                replays every year. This is Galen's proven corn-silage path.
Rotation     -> a generated jday + year_rot decision table in lum.dtl, referenced from
                management.sch as an auto operation, so SWAT+ cycles a different crop
                (and its manure) each rotation year on realistic fixed dates.

Defaults = Galen Richards' corn-silage: plant `csil` Jun 1, harvest `silage` Sep 25,
auto-irrigate 9.1 mm when soil water < 0.8*field-capacity (sprinkler_med, eff 1.0).
Proven to run on SWAT+ rev-62.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date
from pathlib import Path

import config

logger = logging.getLogger(__name__)


# Auto-irrigation efficiency tiers (edit irr.ops sprinkler_med + the fc trigger).
# "medium" = Galen's stated default (9.1 mm, eff 1.0, trigger 0.8*fc).
IRR_TIERS = {
    "high":   {"amt": 12.0, "eff": 0.95, "trigger": 0.85},
    "medium": {"amt": 9.1,  "eff": 1.00, "trigger": 0.80},
    "low":    {"amt": 50.0, "eff": 0.65, "trigger": 0.60},
}
_MANURE_FRT = "beef_fr"  # assumed manure nutrient params (per Galen: "for now")

# ---------------------------------------------------------------------------
# Auto-fertilisation (SWAT+ decision table, modelled on the template's
# `fert_stess_test`). SWAT+ applies `const` kg/ha of the fertiliser whenever the
# plant is stressed and immature, up to `const2` applications — confirmed in the
# engine source (actions.f90):
#     if (num_actions(iac) <= Int(const2)) then ; frt_kg = const
#
# Mapping the farmer's SWAT2012 vocabulary onto that:
#   AUTO_NAPP (max mineral N per application)  -> `const`   on the elem_n action
#   AUTO_EFF  (supply harvest removal x eff)   -> has NO direct rev-62 equivalent;
#       the stress trigger is the feedback loop instead. We size `const2` so the
#       season CAN deliver AUTO_EFF x a typical harvest N removal, and the
#       n_stress < 0.9 condition stops applying once the crop is satisfied.
_FERT_N = "elem_n"          # 100% mineral N in fertilizer.frt -> kg product = kg N
_FERT_P = "elem_p"          # 100% mineral P
AUTO_NAPP = 10.0            # kg N/ha per application (farmer's setting)
AUTO_EFF = 1.1              # harvest removal + 10% for runoff/leaching losses
AUTO_PAPP = 5.0             # kg P/ha per application
# Typical harvest N removal (kg N/ha) used only to size the application cap.
_N_REMOVAL = {
    "csil": 200.0, "corn": 200.0, "pota": 220.0, "sgbt": 150.0,
    "wwht": 140.0, "swht": 130.0, "barl": 110.0,
    "soyb": 0.0, "alfa": 0.0,      # legumes fix their own N — no auto-N
}
_P_REMOVAL = {
    "csil": 30.0, "corn": 30.0, "pota": 40.0, "sgbt": 30.0,
    "wwht": 25.0, "swht": 25.0, "barl": 20.0, "soyb": 20.0, "alfa": 35.0,
}

# Attainable yields (kg/ha dry matter) for irrigated south-central Idaho. AUTO_EFF is
# defined against nitrogen removed AT HARVEST, so the rate must be based on the yield
# the grower is fertilising FOR — a target — not on whatever the model last produced.
# Sizing from achieved yield makes the loop self-referential: a depressed yield gives a
# depressed rate, which can never lift the yield. Legumes fix their own N (target 0).
TARGET_YIELD = {
    "corn": 11000.0,   # grain
    "csil": 20000.0,   # silage (whole-plant DM)
    "pota": 10000.0,   # tuber DM (~50 t/ha fresh at ~20% DM)
    "sgbt": 12000.0,   # root DM
    "wwht": 5500.0,
    "swht": 5000.0,
    "barl": 4500.0,
    "soyb": 3200.0,
    "alfa": 13000.0,   # hay DM — N target still 0 (fixes its own)
}
# Legumes: fertilise P against the target yield, but never N.
_NO_AUTO_N = {"alfa", "soyb"}


def target_removal(txtinout: str | Path, rotation: list[str]) -> dict[str, dict]:
    """Nutrient removed at an attainable target yield — the basis for AUTO_EFF."""
    fracs = read_plant_yield_fracs(txtinout)
    out: dict[str, dict] = {}
    for crop in set(rotation):
        y = TARGET_YIELD.get(crop, 0.0)
        f = fracs.get(crop) or {}
        out[crop] = {
            "n": 0.0 if crop in _NO_AUTO_N else y * float(f.get("n") or 0.0),
            "p": y * float(f.get("p") or 0.0),
        }
    return out


def read_plant_yield_fracs(txtinout: str | Path) -> dict[str, dict]:
    """{crop: {'n': frac_n_yld, 'p': frac_p_yld}} straight from the field's plants.plt.

    These are the fractions of N and P in harvested yield — SWAT's own definition of
    "nitrogen removed at harvest", so N_removed = yield_kg_ha * frac_n_yld.
    """
    plt = Path(txtinout) / "plants.plt"
    if not plt.is_file():
        return {}
    lines = plt.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(lines) < 3:
        return {}
    hdr = lines[1].split()
    try:
        i_n, i_p = hdr.index("frac_n_yld"), hdr.index("frac_p_yld")
    except ValueError:
        return {}
    out: dict[str, dict] = {}
    for ln in lines[2:]:
        t = ln.split()
        if len(t) > max(i_n, i_p):
            try:
                out[t[0]] = {"n": float(t[i_n]), "p": float(t[i_p])}
            except ValueError:
                continue
    return out


def harvest_removal(txtinout: str | Path, yields: dict[str, float]) -> dict[str, dict]:
    """Nutrient removed at harvest per crop, from observed yields (kg/ha).

    yields: {crop_code: mean harvested yield kg/ha} — read from a completed run.
    """
    fracs = read_plant_yield_fracs(txtinout)
    out: dict[str, dict] = {}
    for crop, y in (yields or {}).items():
        f = fracs.get(crop) or {}
        out[crop] = {
            "n": max(0.0, float(y) * float(f.get("n") or 0.0)),
            "p": max(0.0, float(y) * float(f.get("p") or 0.0)),
        }
    return out


def _removal_fert_alts(rotation: list[str], jd: list[tuple], removal: dict[str, dict],
                       eff: float, napp_n: float, napp_p: float) -> tuple[list[tuple], int]:
    """Explicit AUTO_EFF applications: replace harvest removal x efficiency, delivered
    in AUTO_NAPP-sized increments spread across each crop's growing window.

    This is SWAT2012's auto-fertiliser rule implemented directly, because rev-62's
    decision tables have no harvest-removal fertiliser action (only fixed-amount
    `fertilize`, capped by a max number of applications).
    """
    alts: list[tuple] = []
    napp = 0
    N = len(rotation)
    for y, crop in enumerate(rotation, start=1):
        pj, hj, is_fall = jd[y - 1]
        need = removal.get(crop) or {}
        window = (hj - pj) if not is_fall else (365 - pj + hj)
        if window < 20:
            continue
        start = pj + 10                       # let the crop establish first
        usable = max(10, window - 25)         # stop well before maturity
        for nutrient, amount, per_app in (
            ("n", float(need.get("n") or 0.0) * eff, napp_n),
            ("p", float(need.get("p") or 0.0) * eff, napp_p),
        ):
            if amount <= 0 or per_app <= 0:
                continue
            n_app = max(1, int(math.ceil(amount / per_app)))
            step = max(3, int(usable / n_app))
            frt = _FERT_N if nutrient == "n" else _FERT_P
            left = amount
            for k in range(n_app):
                if left <= 0:
                    break
                dose = min(per_app, left)     # last split takes the remainder
                left -= dose
                day = start + k * step
                yr = y
                if day > 365:                 # fall-planted crops run into the next year
                    day -= 365
                    yr = (y % N) + 1
                alts.append(("fertilize", f"af{nutrient}{y}_{k}", frt, f"{dose:.5f}",
                             "1.00000", "broadcast", day, yr, "="))
                napp += 1
    return alts, napp


def _autofert_caps(rotation: list[str], napp_n: float, eff: float,
                   napp_p: float) -> tuple[int, int]:
    """How many applications the table may make, from the most demanding crop."""
    n_need = max((_N_REMOVAL.get(c, 0.0) for c in rotation), default=0.0) * eff
    p_need = max((_P_REMOVAL.get(c, 0.0) for c in rotation), default=0.0) * eff
    n_max = int(round(n_need / napp_n)) if napp_n > 0 else 0
    p_max = int(round(p_need / napp_p)) if napp_p > 0 else 0
    return max(0, n_max), max(0, p_max)


def _build_autofert_dtl(name: str, rotation: list[str], napp_n: float = AUTO_NAPP,
                        eff: float = AUTO_EFF, napp_p: float = AUTO_PAPP) -> str:
    """Stress-triggered auto-fertiliser table (N and P), sized for this rotation.

    Fires while the plant is growing, has not passed maturity, and is nutrient
    stressed — so a legume year simply never triggers the N action.
    """
    n_max, p_max = _autofert_caps(rotation, napp_n, eff, napp_p)
    hdr = (
        "name                     conds      alts      acts       "
        "!auto-fertilise: apply mineral N/P while the plant is stressed and immature\n"
        f"{name:<25}{4:>6}{2:>10}{2:>10}  \n"
        "var                        obj   obj_num           lim_var            lim_op"
        "     lim_const      alt1      alt2  \n"
        "n_stress                   hru         0              null                 -"
        "       0.90000         <         -  \n"
        "p_stress                   hru         0              null                 -"
        "       0.90000         -         <  \n"
        "plant_gro                  hru         0                 y                 -"
        "       1.00000         =         =  \n"
        "phu_plant                  hru         0           phu_mat                 -"
        "       1.05000         <         <  \n"
        "act_typ                    obj   obj_num              name            option"
        "         const        const2                fp  outcome           \n"
        f"fertilize                  hru         0        side_dress            {_FERT_N:<6}"
        f"{napp_n:>14.5f}{float(n_max):>14.5f}         broadcast  y   n  \n"
        f"fertilize                  hru         0        side_dress            {_FERT_P:<6}"
        f"{napp_p:>14.5f}{float(p_max):>14.5f}         broadcast  n   y  \n"
    )
    return hdr

# Per-crop planting/harvest calendar + harvest operation. csil reproduces Galen's
# schedule exactly; the rest are typical Idaho/Great-Plains dates the farmer can change.
CROP_CAL = {
    "csil": {"plant": (6, 1),  "harvest": (9, 25),  "harv_op": "silage"},
    "corn": {"plant": (5, 1),  "harvest": (10, 15), "harv_op": "grain"},
    "soyb": {"plant": (5, 20), "harvest": (10, 10), "harv_op": "grain"},
    "wwht": {"plant": (9, 20), "harvest": (7, 15),  "harv_op": "grain"},
    "swht": {"plant": (4, 15), "harvest": (8, 15),  "harv_op": "grain"},   # spring wheat
    "alfa": {"plant": (4, 15), "harvest": (9, 1),   "harv_op": "hay_cut_high"},
    "barl": {"plant": (4, 1),  "harvest": (8, 1),   "harv_op": "grain"},
    # Root/tuber crops MUST use the tuber harvest operation — a "grain" harvest on a
    # root crop removes the seed pool, which is empty, so yield comes out exactly 0.
    "pota": {"plant": (5, 1),  "harvest": (9, 25),  "harv_op": "tuber"},   # potato (Idaho)
    "sgbt": {"plant": (4, 10), "harvest": (10, 15), "harv_op": "tuber"},   # sugar beet (Idaho)
}


def _crop_cal(crop: str) -> dict:
    return CROP_CAL.get(crop, {"plant": config.GALEN_DEFAULTS["plant"],
                               "harvest": config.GALEN_DEFAULTS["harvest"],
                               "harv_op": config.GALEN_DEFAULTS["harv_op"]})


# Days to wait after a fall/winter crop's harvest before planting the next rotation crop,
# so the next crop is never established on top of the still-standing winter crop.
_PLANT_GAP = 10


def _jday(mon: int, day: int) -> int:
    return date(2021, mon, day).timetuple().tm_yday  # non-leap reference


def _build_rotation_dtl(name: str, rotation: list[str], cals: list[dict],
                        manure_by_year: dict[int, list[dict]],
                        extra_alts: list[tuple] | None = None) -> tuple[str, int]:
    """Generate a jday + year_rot plant/harvest(/fertilize) decision table.

    One alternative per operation; each fires on its own (jday == day AND year_rot == y).
    A reset alt fires as soon as year_rot EXCEEDS the rotation length (year_rot > N, no
    jday) and rolls the counter back to 1 so the rotation repeats — matching the SWAT+
    template's pl_hv_summer2 pattern. Returns (table_text, manure_applications)."""
    # each alt: (act_typ, name, option, const, const2, fp, jday|None, year, year_op)
    alts: list[tuple] = list(extra_alts or [])
    napp = 0
    N = len(rotation)
    # Precompute each slot's plant/harvest jday and whether it is a fall/winter crop
    # (harvest jday < plant jday), which grows into the NEXT rotation year.
    jd = [(_jday(*c["plant"]), _jday(*c["harvest"]),
           _jday(*c["harvest"]) < _jday(*c["plant"])) for c in cals]
    for y, crop in enumerate(rotation, start=1):
        cal = cals[y - 1]
        pj, hj, is_fall = jd[y - 1]
        # A fall/winter crop in the PREVIOUS slot (cyclic) is harvested in THIS crop's
        # planting year. If this crop would be planted before that harvest it would grow
        # on top of the still-standing winter crop — the overlap seen in the timeline.
        # Delay planting until just after the winter crop clears the field (as long as
        # there is still room before this crop's own harvest).
        prev_hj, prev_is_fall = jd[(y - 2) % N][1], jd[(y - 2) % N][2]
        if prev_is_fall and not is_fall and pj < prev_hj + _PLANT_GAP < hj:
            pj = prev_hj + _PLANT_GAP
        alts.append(("plant", f"plnt_{y}", crop, "0.00000", "1.00000", "null", pj, y, "="))

        for k, m in enumerate(manure_by_year.get(y, [])):
            amt = float(m.get("amount_kg_ha") or 0)
            mon = int(m.get("month") or 5)
            if amt > 0:
                alts.append(("fertilize", f"manure_{y}_{k}", _MANURE_FRT, f"{amt:.5f}",
                             "1.00000", "broadcast", _jday(mon, 15), y, "="))
                napp += 1
        # fall/winter-planted crops (harvest jday < plant jday) span into the NEXT
        # rotation year, so bind their harvest to year y+1 (wrapping the last slot to 1).
        # Use the crop's own (undelayed) fall status so a delayed spring crop isn't wrapped.
        hy = (y % N) + 1 if is_fall else y
        alts.append(("harvest_kill", f"harv_{y}", crop, "0.00000", "1.00000",
                     cal["harv_op"], hj, hy, "="))
    # reset: no jday, fires when year_rot > N (start of the year after the last)
    alts.append(("rot_reset", f"reset_{N}", "null", "1.00000", "1.00000", "null", None, N, ">"))
    K = len(alts)
    jday_alts = [i for i, a in enumerate(alts) if a[6] is not None]
    n_conds = len(jday_alts) + K  # one jday row per dated alt + one year_rot row per alt

    out = [f"name                     conds      alts      acts       "
           f"!AI-SWAT+ rotation ({'-'.join(rotation)})",
           f"{name:<24} {n_conds:>8} {K:>9} {K:>9}  ",
           "var                        obj   obj_num           lim_var            lim_op"
           "     lim_const" + "".join(f"      alt{i + 1}" for i in range(K))]
    for i in jday_alts:  # jday conditions (dated alts only)
        ops = ["-"] * K; ops[i] = "="
        out.append(f"jday                       hru         0              null"
                   f"                 -  {float(alts[i][6]):>11.5f}" + "".join(f"  {o:>7}" for o in ops))
    for i, a in enumerate(alts):  # year_rot conditions (op per alt: '=' ops, '>' reset)
        ops = ["-"] * K; ops[i] = a[8]
        out.append(f"year_rot                   hru         0              null"
                   f"                 -  {float(a[7]):>11.5f}" + "".join(f"  {o:>7}" for o in ops))
    out.append("act_typ                    obj   obj_num              name            option"
               "         const        const2                fp  outcome")
    for i, a in enumerate(alts):
        yn = ["n"] * K; yn[i] = "y"
        out.append(f"{a[0]:<26} hru         0  {a[1]:>16}  {a[2]:>12}  {a[3]:>10}"
                   f"  {a[4]:>10}  {a[5]:>16}  " + "   ".join(yn))
    return "\n".join(out) + "\n", napp


def apply_management(
    txtinout: str | Path,
    crop: str | None = None,
    crops: list[str] | None = None,
    plant: tuple[int, int] | None = None,
    harvest: tuple[int, int] | None = None,
    harv_op: str | None = None,
    irrigation_tier: str | None = None,
    manure: list[dict] | None = None,
    irr_amt: float | None = None,
    irr_eff: float | None = None,
    irr_trigger: float | None = None,
    fertilizer: bool = True,
    fert_n: float | None = None,
    fert_p: float | None = None,
    expected_yield: dict[str, float] | None = None,
) -> dict:
    g = config.GALEN_DEFAULTS
    # rotation = one crop per year; single-crop is a 1-element rotation.
    rotation = [c for c in (crops or ([crop] if crop else [])) if c] or [g["crop"]]
    is_rot = len(rotation) > 1
    tier = IRR_TIERS.get((irrigation_tier or "medium").lower(), IRR_TIERS["medium"])
    irr_amt = irr_amt if irr_amt is not None else tier["amt"]
    irr_eff = irr_eff if irr_eff is not None else tier["eff"]
    irr_trigger = irr_trigger if irr_trigger is not None else tier["trigger"]

    tio = Path(txtinout)
    tag = rotation[0] if not is_rot else "rot"
    comm, sched = f"{tag}_comm", f"{tag}_auto_irr"
    rot_dtl = f"{tag}_croprot"

    # per-crop calendar; the first crop honours explicit plant/harvest overrides.
    cals = []
    for i, c in enumerate(rotation):
        cal = dict(_crop_cal(c))
        if i == 0:
            if plant:   cal["plant"] = plant
            if harvest: cal["harvest"] = harvest
            if harv_op: cal["harv_op"] = harv_op
        cals.append(cal)

    # manure indexed by rotation year (1-based); entries without a year -> year 1.
    manure_by_year: dict[int, list[dict]] = {}
    for m in (manure or []):
        manure_by_year.setdefault(int(m.get("year") or 1), []).append(m)

    # Auto-fertiliser table, appended to lum.dtl and referenced as an auto operation.
    # Without this the field gets NO fertiliser at all (the template ships the table
    # but nothing attaches it, which is why runs reported 0 kg N applied).
    napp_n = AUTO_NAPP if fert_n is None else float(fert_n)
    napp_p = AUTO_PAPP if fert_p is None else float(fert_p)
    # AUTO_EFF mode: when observed yields are supplied we schedule exactly
    # (harvest removal x AUTO_EFF) in AUTO_NAPP-sized splits. Otherwise fall back to
    # the stress-triggered table (which can only ever apply a fixed amount).
    if fertilizer:
        # explicit yields win; otherwise fertilise against attainable target yields
        removal = (harvest_removal(tio, expected_yield) if expected_yield
                   else target_removal(tio, rotation))
    else:
        removal = {}
    autofert_dtl = f"{tag}_autofert" if (fertilizer and not removal) else None

    OPI = "                                                            "
    if is_rot:
        # 1a) rotation decision table -> lum.dtl (bump table count), auto in management.sch
        jd_all = [(_jday(*c["plant"]), _jday(*c["harvest"]),
                   _jday(*c["harvest"]) < _jday(*c["plant"])) for c in cals]
        rem_alts, rem_napp = _removal_fert_alts(rotation, jd_all, removal, AUTO_EFF,
                                                napp_n, napp_p) if removal else ([], 0)
        table, napp = _build_rotation_dtl(rot_dtl, rotation, cals, manure_by_year, rem_alts)
        napp += rem_napp
        extra = "\n" + _build_autofert_dtl(autofert_dtl, rotation, napp_n, AUTO_EFF, napp_p) \
            if autofert_dtl else ""
        dtl = tio / "lum.dtl"
        D = dtl.read_text(encoding="utf-8").splitlines()
        if len(D) > 1 and D[1].strip().isdigit():
            D[1] = str(int(D[1]) + (2 if autofert_dtl else 1))
        dtl.write_text("\n".join(D) + "\n\n" + table + extra, encoding="utf-8")
        autos = [rot_dtl, "irr_opt_sw_unlim"] + ([autofert_dtl] if autofert_dtl else [])
        (tio / "management.sch").write_text(
            "management.sch: AI-SWAT+ crop rotation\n"
            "name                                       numb_ops  numb_auto            op_typ"
            "       mon       day        hu_sch          op_data1          op_data2      op_data3  \n"
            f"{sched:<34}0{len(autos):>11}  \n"
            + "".join(f"                                                {a}  \n" for a in autos),
            encoding="utf-8",
        )
    else:
        # 1b) single crop -> flat plant -> manure -> harvest+kill (SWAT+ replays annually)
        napp = 0
        c = rotation[0]; cal = cals[0]
        ops = [f"{OPI}plnt      {cal['plant'][0]:>4}      {cal['plant'][1]:>4}       0.00000"
               f"              {c:<12}      null       0.00000  "]
        for m in manure_by_year.get(1, []):
            amt = float(m.get("amount_kg_ha") or 0)
            mon = int(m.get("month") or 5)
            if amt > 0:
                ops.append(f"{OPI}fert      {mon:>4}        15       0.00000"
                           f"              {_MANURE_FRT:<12} broadcast   {amt:>8.5f}  ")
                napp += 1
        ops.append(f"{OPI}hvkl      {cal['harvest'][0]:>4}      {cal['harvest'][1]:>4}       0.00000"
                   f"              {c:<12}    {cal['harv_op']:>8}       0.00000  ")
        (tio / "management.sch").write_text(
            "management.sch: AI-SWAT+ field management\n"
            "name                                       numb_ops  numb_auto            op_typ"
            "       mon       day        hu_sch          op_data1          op_data2      op_data3  \n"
            f"{sched:<34}{len(ops):<11}{2 if autofert_dtl else 1}  \n"
            "                                                irr_opt_sw_unlim  \n"
            + (f"                                                {autofert_dtl}  \n"
               if autofert_dtl else "")
            + "\n".join(ops) + "\n",
            encoding="utf-8",
        )
        if autofert_dtl:                       # single-crop path needs the table too
            dtl = tio / "lum.dtl"
            D = dtl.read_text(encoding="utf-8").splitlines()
            if len(D) > 1 and D[1].strip().isdigit():
                D[1] = str(int(D[1]) + 1)
            dtl.write_text("\n".join(D) + "\n\n"
                           + _build_autofert_dtl(autofert_dtl, rotation, napp_n, AUTO_EFF, napp_p),
                           encoding="utf-8")

    # 2) plant.ini — community with every distinct crop. Single crop grows at start
    # (lc_status y); rotation crops are initiated by the decision table (all n).
    #
    # Every rotation shares the community name "rot_comm", so this MUST replace any
    # existing block of that name rather than skip when it is already present —
    # otherwise switching rotations (e.g. corn/alfalfa -> corn/potato/sugarbeet/wheat)
    # silently keeps the previous crop list and the new crops never grow.
    pini = tio / "plant.ini"
    ptxt = pini.read_text(encoding="utf-8")
    seen: list[str] = []
    for c in rotation:
        if c not in seen:
            seen.append(c)

    lines = ptxt.splitlines()
    kept: list[str] = []
    skip = 0
    for ln in lines:
        if skip > 0:                      # drop the old community's plant rows
            skip -= 1
            continue
        tok = ln.split()
        if tok and tok[0] == comm:        # community header: name, n_plants, rot_yr
            try:
                skip = int(tok[1])
            except (IndexError, ValueError):
                skip = 0
            continue
        kept.append(ln)

    plant_lines = "".join(
        f"                                        {c:<12} {'y' if (i == 0 and not is_rot) else 'n'}"
        "       0.00000       0.00000       0.00000       0.00000       1.00000       0.00000  \n"
        for i, c in enumerate(seen)
    )
    pini.write_text(
        "\n".join(kept).rstrip("\n") + "\n"
        + f"{comm:<21}{len(seen):<10}1  \n"
        + plant_lines,
        encoding="utf-8",
    )

    # 3) landuse.lum — HRU row: plnt_com=<comm>, mgt=<sched>
    lum = tio / "landuse.lum"
    L = lum.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(L):
        t = ln.split()
        if len(t) >= 4 and t[0].endswith("_lum"):
            t[2], t[3] = comm, sched
            L[i] = t[0].ljust(30) + "  ".join(x.ljust(16) for x in t[1:])
            break
    lum.write_text("\n".join(L) + "\n", encoding="utf-8")

    # 4) file.cio — lum line 2nd slot -> management.sch
    cio = tio / "file.cio"
    C = cio.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(C):
        t = ln.split()
        if t and t[0] == "lum":
            t[2] = "management.sch"
            C[i] = "".join(x.ljust(18) for x in t)
            break
    cio.write_text("\n".join(C) + "\n", encoding="utf-8")

    # 5) irr.ops — sprinkler_med per Galen (amt, eff; defaults on no3/po4)
    irr = tio / "irr.ops"
    I = irr.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(I):
        if ln.strip().startswith("sprinkler_med"):
            I[i] = (f"sprinkler_med       {irr_amt:>8.5f}      {irr_eff:>8.5f}       0.00000"
                    "       0.00000       0.00000      20.00000       1.00000  ")
            break
    irr.write_text("\n".join(I) + "\n", encoding="utf-8")

    # 6) lum.dtl — irr_opt_sw_unlim: trigger fraction of fc, action -> sprinkler_med
    dtl = tio / "lum.dtl"
    D = dtl.read_text(encoding="utf-8")
    D = D.replace("sprinkler_ilm", "sprinkler_med")  # fix undefined ref in the a10/template table
    D = re.sub(r"(soil_water\s+hru\s+0\s+fc\s+-\s+)\d\.\d+", rf"\g<1>{irr_trigger:.5f}", D)
    dtl.write_text(D, encoding="utf-8")

    first = cals[0]
    return {
        "ok": True, "schedule": sched, "crop": rotation[0], "rotation": rotation,
        "rotation_years": len(rotation), "rotation_mode": "decision_table" if is_rot else "annual",
        "plant": f"{first['plant'][0]:02d}-{first['plant'][1]:02d}",
        "harvest": f"{first['harvest'][0]:02d}-{first['harvest'][1]:02d}",
        "harv_op": first["harv_op"], "irrigation_tier": (irrigation_tier or "medium").lower(),
        "irr_amt_mm": irr_amt, "irr_eff": irr_eff, "irr_trigger_fc": irr_trigger,
        "manure_applications": napp,
    }
