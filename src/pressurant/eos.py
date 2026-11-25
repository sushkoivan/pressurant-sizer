"""Real-gas equation of state: Peng-Robinson (1976), with an optional CoolProp backend.

Peng-Robinson in terms of the compressibility factor Z = p / (rho R T):

    Z^3 - (1 - B) Z^2 + (A - 3B^2 - 2B) Z - (AB - B^2 - B^3) = 0
    A = a alpha p / (R T)^2,   B = b p / (R T)
    a = 0.45724 (R Tc)^2 / pc,  b = 0.07780 R Tc / pc
    alpha = [1 + kappa (1 - sqrt(T/Tc))]^2,  kappa = 0.37464 + 1.54226 w - 0.26992 w^2

The gas-phase root is the largest real root of the cubic.
"""
from __future__ import annotations

import math

from .gases import Gas, get_gas

_BACKEND = "pr"


def set_backend(name: str) -> None:
    """Select the property backend: ``"pr"`` (Peng-Robinson, default, no dependencies) or
    ``"coolprop"`` (reference-quality Helmholtz equations, needs ``pip install CoolProp``)."""
    global _BACKEND
    name = name.lower()
    if name not in ("pr", "coolprop"):
        raise ValueError("backend must be 'pr' or 'coolprop'")
    if name == "coolprop":
        import CoolProp  # noqa: F401  (fail early with ImportError)
    _BACKEND = name


def get_backend() -> str:
    return _BACKEND


def _cubic_roots(c2: float, c1: float, c0: float) -> list[float]:
    """Real roots of x^3 + c2 x^2 + c1 x + c0 = 0 (Cardano / trigonometric form)."""
    q = (3 * c1 - c2 * c2) / 9
    r = (9 * c2 * c1 - 27 * c0 - 2 * c2 ** 3) / 54
    disc = q ** 3 + r ** 2
    shift = -c2 / 3
    if disc > 0:
        s = math.sqrt(disc)
        return [math.copysign(abs(r + s) ** (1 / 3), r + s) + math.copysign(abs(r - s) ** (1 / 3), r - s) + shift]
    if q == 0:
        return [shift]
    theta = math.acos(max(-1.0, min(1.0, r / math.sqrt(-q ** 3))))
    m = 2 * math.sqrt(-q)
    return [m * math.cos((theta + 2 * math.pi * k) / 3) + shift for k in range(3)]


def z_factor_pr(gas: Gas | str, p: float, t: float) -> float:
    """Peng-Robinson compressibility factor of the gas phase at pressure p [Pa abs] and temperature t [K]."""
    g = get_gas(gas)
    if p <= 0 or t <= 0:
        raise ValueError("pressure and temperature must be positive (absolute units)")
    r = g.r_specific
    a = 0.45724 * (r * g.t_crit) ** 2 / g.p_crit
    b = 0.07780 * r * g.t_crit / g.p_crit
    kappa = 0.37464 + 1.54226 * g.omega - 0.26992 * g.omega ** 2
    alpha = (1 + kappa * (1 - math.sqrt(t / g.t_crit))) ** 2
    big_a = a * alpha * p / (r * t) ** 2
    big_b = b * p / (r * t)
    roots = _cubic_roots(-(1 - big_b), big_a - 3 * big_b ** 2 - 2 * big_b, -(big_a * big_b - big_b ** 2 - big_b ** 3))
    roots = [z for z in roots if z > big_b]
    if not roots:
        raise ArithmeticError("no physical Peng-Robinson root")
    return max(roots)


def z_factor(gas: Gas | str, p: float, t: float) -> float:
    """Compressibility factor Z with the active backend."""
    g = get_gas(gas)
    if _BACKEND == "coolprop":
        import CoolProp.CoolProp as CP
        return CP.PropsSI("Z", "P", p, "T", t, g.coolprop_name)
    return z_factor_pr(g, p, t)


def density(gas: Gas | str, p: float, t: float) -> float:
    """Gas density [kg/m^3] at p [Pa abs], t [K]."""
    g = get_gas(gas)
    return p / (z_factor(g, p, t) * g.r_specific * t)


def density_ideal(gas: Gas | str, p: float, t: float) -> float:
    """Ideal-gas density [kg/m^3] -- for comparison only."""
    g = get_gas(gas)
    return p / (g.r_specific * t)
