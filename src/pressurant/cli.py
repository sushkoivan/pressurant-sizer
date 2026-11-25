"""Command-line interface.

    python -m pressurant examples/biprop_vehicle.json
    python -m pressurant --gas N2,He --fill 310 --tank ox,8,35 --tank fuel,4,35,0 --thruster rcs,2,65,8,4
    python -m pressurant examples/biprop_vehicle.json --sweep --json result.json
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .eos import set_backend
from .sizing import MassDemand, TankDemand, ThrusterDemand, bar_g, size_bottle

C_TO_K = 273.15


def _floats(text: str, n_min: int, n_max: int, what: str) -> list:
    parts = text.split(",")
    if not n_min <= len(parts) <= n_max:
        raise argparse.ArgumentTypeError(f"{what}: expected {n_min}-{n_max} comma-separated fields, got {text!r}")
    return [parts[0]] + [float(x) for x in parts[1:]]


def parse_tank(text: str) -> TankDemand:
    """NAME,VOLUME_L,P_BARG[,T_ULLAGE_C[,DISSOLUTION]]"""
    f = _floats(text, 3, 5, "--tank")
    return TankDemand(f[0], f[1] * 1e-3, bar_g(f[2]), (f[3] if len(f) > 3 else 0.0) + C_TO_K,
                      f[4] if len(f) > 4 else 0.0)


def parse_thruster(text: str) -> ThrusterDemand:
    """NAME,THRUST_N,ISP_S,FIRING_TIME_S[,COUNT]"""
    f = _floats(text, 4, 5, "--thruster")
    return ThrusterDemand(f[0], f[1], f[2], f[3], int(f[4]) if len(f) > 4 else 1)


def load_config(path: str) -> dict:
    """Read a JSON case file (see examples/). Units: L, bar g, deg C, N, s, g."""
    with open(path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    demands = []
    for t in cfg.get("tanks", []):
        demands.append(TankDemand(t["name"], t["volume_L"] * 1e-3, bar_g(t["pressure_bar_g"]),
                                  t.get("ullage_temp_C", 0.0) + C_TO_K, t.get("dissolution", 0.0),
                                  t.get("prepressurised_fraction", 0.0)))
    for t in cfg.get("thrusters", []):
        demands.append(ThrusterDemand(t["name"], t["thrust_N"], t["isp_s"], t["firing_time_s"], t.get("count", 1)))
    for t in cfg.get("fixed", []):
        demands.append(MassDemand(t["name"], t["mass_g"] * 1e-3))
    b = cfg.get("bottle", {})
    return {
        "gases": cfg.get("gases", ["N2"]),
        "demands": demands,
        "p_fill": bar_g(b.get("fill_pressure_bar_g", 300.0)),
        "t_fill": b.get("fill_temp_C", 20.0) + C_TO_K,
        "dropout": b.get("regulator_dropout_bar", 15.0) * 1e5,
        "n": b.get("polytropic_n", 1.2),
        "margin": cfg.get("margin", 0.10),
        "title": cfg.get("title", path),
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pressurant", description="Real-gas pressurant bottle sizing.")
    p.add_argument("config", nargs="?", help="JSON case file (command-line options override it)")
    p.add_argument("--gas", help="comma-separated gases to compare, e.g. N2,He")
    p.add_argument("--fill", type=float, help="bottle fill pressure [bar g]")
    p.add_argument("--fill-temp", type=float, help="bottle temperature at fill [deg C]")
    p.add_argument("--dropout", type=float, help="regulator dropout [bar]")
    p.add_argument("--n", type=float, help="polytropic exponent of the blowdown (1 = isothermal)")
    p.add_argument("--margin", type=float, help="fractional margin on the gas demand")
    p.add_argument("--tank", action="append", type=parse_tank, default=[],
                   metavar="NAME,L,BARG[,T_C[,DISS]]", help="tank emptied under pressure (repeatable)")
    p.add_argument("--thruster", action="append", type=parse_thruster, default=[],
                   metavar="NAME,N,ISP,T_S[,COUNT]", help="cold-gas thruster(s) (repeatable)")
    p.add_argument("--sweep", action="store_true", help="also print volume for isothermal / n / adiabatic blowdown")
    p.add_argument("--coolprop", action="store_true", help="use CoolProp instead of Peng-Robinson")
    p.add_argument("--json", metavar="PATH", help="write results as JSON")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    case = load_config(args.config) if args.config else {
        "gases": ["N2"], "demands": [], "p_fill": bar_g(300.0), "t_fill": 20.0 + C_TO_K,
        "dropout": 15e5, "n": 1.2, "margin": 0.10, "title": "command line"}
    if args.gas:
        case["gases"] = args.gas.split(",")
    if args.fill is not None:
        case["p_fill"] = bar_g(args.fill)
    if args.fill_temp is not None:
        case["t_fill"] = args.fill_temp + C_TO_K
    if args.dropout is not None:
        case["dropout"] = args.dropout * 1e5
    if args.n is not None:
        case["n"] = args.n
    if args.margin is not None:
        case["margin"] = args.margin
    case["demands"] = case["demands"] + args.tank + args.thruster
    if not case["demands"]:
        print("nothing to size: give a config file or --tank / --thruster", file=sys.stderr)
        return 2
    if args.coolprop:
        set_backend("coolprop")

    print(f"== {case['title']}")
    results = []
    for gas in case["gases"]:
        r = size_bottle(gas, case["demands"], case["p_fill"], case["t_fill"], dropout=case["dropout"],
                        n=case["n"], margin=case["margin"])
        results.append(r)
        print()
        print(r.report())
        if args.sweep:
            gamma = r.gas.gamma
            print(f"   blowdown sensitivity: " + ",  ".join(
                f"n {nn:g}: {size_bottle(gas, case['demands'], case['p_fill'], case['t_fill'], dropout=case['dropout'], n=nn, margin=case['margin']).volume_l:.2f} L"
                for nn in (1.0, case["n"], gamma)))
    if len(results) > 1:
        print("\nComparison")
        print(f"   {'gas':<16}{'volume [L]':>11}{'gas mass [kg]':>15}{'energy [kJ]':>13}")
        for r in results:
            print(f"   {r.gas.name:<16}{r.volume_l:>11.2f}{r.charged_mass:>15.3f}{r.stored_energy / 1e3:>13.0f}")
    print("\nNote: preliminary sizing only. Pressure vessels store lethal energy; buy certified bottles, "
          "respect their ratings and proof-test hydrostatically.")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump([r.to_dict() for r in results], fh, indent=2)
    return 0
