"""Pressurant bottle sizing.

Method
------
1. **Demand.** Every consumer is converted to a gas mass:

   * a propellant tank that must be full of gas when it is empty:
     ``m = rho(p_tank, T_ullage) * V_tank * (1 + dissolution) * (1 - prepressurised_fraction)``
   * a cold-gas thruster: ``m = count * F / (Isp * g0) * t_fire``
   * a fixed mass (purges, valve actuation, leaks): ``m``

2. **Supply.** A bottle filled to ``p0, T0`` stops being useful when it drops to ``p_min``
   (highest regulated pressure + regulator dropout). The gas left in the bottle expands while it flows
   out and cools along a polytropic path ``T = T0 (p / p0)^((n-1)/n)``:
   ``n = 1`` isothermal (slow draw, warm walls), ``n = gamma`` adiabatic (fast), ``n ~ 1.2`` is a common
   design value for flight-length blowdowns.

   usable density  ``rho_u = rho(p0, T0) - rho(p_min, T_end)``

3. **Volume.** ``V = m_demand (1 + margin) / rho_u``

All densities come from a real-gas equation of state (Peng-Robinson by default). At 300 bar an ideal-gas
model undersizes a nitrogen bottle by more than 10 %.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Tuple, Union

from .eos import density, density_ideal
from .gases import Gas, get_gas

G0 = 9.80665          # m/s^2
P_ATM = 101_325.0     # Pa
TNT_J_PER_KG = 4.184e6


def bar_g(x: float) -> float:
    """Gauge pressure in bar -> absolute pressure in Pa."""
    return x * 1e5 + P_ATM


def to_bar_g(p: float) -> float:
    """Absolute pressure in Pa -> gauge pressure in bar."""
    return (p - P_ATM) / 1e5


# --------------------------------------------------------------------------------------------- demands
@dataclass
class TankDemand:
    """A propellant tank that the bottle pressurises while it empties.

    Attributes:
        name: label for reports
        volume: tank volume that is full of gas at the end of the burn [m^3]
        pressure: regulated tank pressure [Pa abs]
        t_gas: gas temperature in the ullage at the end of the burn [K]
        dissolution: extra fraction of gas lost into the liquid (e.g. 0.1)
        prepressurised_fraction: fraction of the volume already full of gas at ``pressure`` before
            flight (pressurised from ground equipment, so the bottle does not supply it)
    """

    name: str
    volume: float
    pressure: float
    t_gas: float = 273.15
    dissolution: float = 0.0
    prepressurised_fraction: float = 0.0

    def gas_mass(self, gas: Gas, ideal: bool = False) -> float:
        rho = (density_ideal if ideal else density)(gas, self.pressure, self.t_gas)
        return rho * self.volume * (1 + self.dissolution) * (1 - self.prepressurised_fraction)


@dataclass
class ThrusterDemand:
    """Cold-gas thrusters (reaction control) fed from the bottle.

    Attributes:
        thrust: thrust per thruster [N]
        isp: specific impulse [s]; either one number or a dict per gas, e.g. ``{"N2": 70, "He": 165}``
            (cold-gas Isp depends strongly on the gas)
        firing_time: total on-time per thruster over the mission [s]
        count: number of thrusters that each fire for ``firing_time``
    """

    name: str
    thrust: float
    isp: Union[float, dict]
    firing_time: float
    count: int = 1

    def isp_for(self, gas: Gas) -> float:
        """Specific impulse for this gas [s]."""
        if not isinstance(self.isp, dict):
            return float(self.isp)
        for key, value in self.isp.items():
            if get_gas(key) is gas:
                return float(value)
        raise ValueError(f"thruster {self.name!r}: no Isp given for {gas.name}")

    def gas_mass(self, gas: Gas, ideal: bool = False) -> float:
        return self.count * self.thrust / (self.isp_for(gas) * G0) * self.firing_time


@dataclass
class MassDemand:
    """A fixed gas mass (purges, valve actuation, leak allowance) [kg]."""

    name: str
    mass: float

    def gas_mass(self, gas: Gas, ideal: bool = False) -> float:
        return self.mass


Demand = Union[TankDemand, ThrusterDemand, MassDemand]


# --------------------------------------------------------------------------------------------- result
@dataclass
class SizingResult:
    """Everything `size_bottle` computed. Pressures in Pa abs, temperatures in K, volumes in m^3."""

    gas: Gas
    volume: float
    demand: float
    demand_with_margin: float
    breakdown: dict = field(default_factory=dict)
    p_fill: float = 0.0
    t_fill: float = 0.0
    p_min: float = 0.0
    t_end: float = 0.0
    n: float = 1.2
    margin: float = 0.0
    rho_fill: float = 0.0
    rho_end: float = 0.0
    usable_density: float = 0.0
    ideal_gas_volume: float = 0.0

    @property
    def volume_l(self) -> float:
        """Required bottle volume [L]."""
        return self.volume * 1e3

    @property
    def charged_mass(self) -> float:
        """Gas mass loaded into the bottle at fill [kg]."""
        return self.rho_fill * self.volume

    @property
    def stored_energy(self) -> float:
        """Indicative energy of an isentropic expansion of the full bottle to ambient [J].

        Ideal-gas expression ``p V / (gamma - 1) * [1 - (p_atm / p)^((gamma - 1) / gamma)]`` -- use it to
        rank the hazard, not for blast design.
        """
        k = self.gas.gamma
        return self.p_fill * self.volume / (k - 1) * (1 - (P_ATM / self.p_fill) ** ((k - 1) / k))

    @property
    def tnt_equivalent(self) -> float:
        """Stored energy expressed as kg of TNT (4.184 MJ/kg)."""
        return self.stored_energy / TNT_J_PER_KG

    def report(self) -> str:
        """Human-readable step-by-step report."""
        lines = [f"Pressurant: {self.gas.name}", "1. Demand"]
        for name, m in self.breakdown.items():
            lines.append(f"   {name:<28} {m * 1e3:9.1f} g")
        lines += [
            f"   {'total':<28} {self.demand * 1e3:9.1f} g  x (1 + {self.margin:.2f} margin) = "
            f"{self.demand_with_margin * 1e3:.1f} g",
            "2. Bottle",
            f"   full   {to_bar_g(self.p_fill):6.0f} bar g  {self.t_fill - 273.15:6.1f} C   "
            f"rho {self.rho_fill:7.2f} kg/m3",
            f"   empty  {to_bar_g(self.p_min):6.0f} bar g  {self.t_end - 273.15:6.1f} C   "
            f"rho {self.rho_end:7.2f} kg/m3   (polytropic n = {self.n:g})",
            f"   usable {self.usable_density:.2f} g of gas per litre of bottle",
            "3. Result",
            f"   required volume  {self.volume_l:8.2f} L   (ideal gas would say {self.ideal_gas_volume * 1e3:.2f} L)",
            f"   gas charged      {self.charged_mass:8.3f} kg",
            f"   stored energy    {self.stored_energy / 1e3:8.0f} kJ  (~{self.tnt_equivalent * 1e3:.0f} g TNT, indicative)",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "gas": self.gas.name, "volume_L": self.volume_l, "demand_kg": self.demand,
            "demand_with_margin_kg": self.demand_with_margin, "breakdown_kg": dict(self.breakdown),
            "p_fill_bar_g": to_bar_g(self.p_fill), "t_fill_K": self.t_fill,
            "p_min_bar_g": to_bar_g(self.p_min), "t_end_K": self.t_end, "n": self.n, "margin": self.margin,
            "usable_density_kg_m3": self.usable_density, "charged_mass_kg": self.charged_mass,
            "stored_energy_J": self.stored_energy, "ideal_gas_volume_L": self.ideal_gas_volume * 1e3,
        }


# --------------------------------------------------------------------------------------------- core
def end_temperature(t_fill: float, p_fill: float, p: float, n: float) -> float:
    """Polytropic temperature of the gas left in the bottle when it has dropped to pressure ``p``."""
    if n < 1:
        raise ValueError("polytropic exponent n must be >= 1")
    return t_fill * (p / p_fill) ** ((n - 1) / n)


def usable_density(gas, p_fill: float, t_fill: float, p_min: float, n: float = 1.2,
                   ideal: bool = False) -> float:
    """Gas mass a bottle can deliver per m^3 of internal volume [kg/m^3]."""
    g = get_gas(gas)
    if p_min >= p_fill:
        raise ValueError("bottle fill pressure must exceed the minimum useful pressure")
    rho_fn = density_ideal if ideal else density
    return rho_fn(g, p_fill, t_fill) - rho_fn(g, p_min, end_temperature(t_fill, p_fill, p_min, n))


def min_pressure(demands: Iterable[Demand], dropout: float) -> float:
    """Highest regulated tank pressure plus regulator dropout [Pa abs]."""
    tanks = [d.pressure for d in demands if isinstance(d, TankDemand)]
    return (max(tanks) if tanks else P_ATM) + dropout


def size_bottle(gas, demands: Iterable[Demand], p_fill: float, t_fill: float = 293.15,
                p_min: Optional[float] = None, dropout: float = 15e5, n: float = 1.2,
                margin: float = 0.10) -> SizingResult:
    """Size a pressurant bottle.

    Args:
        gas: gas name ("N2", "He", "Ar", "air", "CO2") or a `Gas`
        demands: tanks, thrusters and fixed masses fed by the bottle
        p_fill: bottle fill pressure [Pa abs]
        t_fill: settled bottle temperature at fill [K]
        p_min: pressure at which the bottle counts as empty [Pa abs]; default: highest tank pressure + dropout
        dropout: regulator dropout [Pa], used when ``p_min`` is not given
        n: polytropic exponent of the blowdown (1 = isothermal, gamma = adiabatic)
        margin: fractional margin on the demand (leaks, regulator lock-up, line volume, residuals)
    """
    g = get_gas(gas)
    demands = list(demands)
    if not demands:
        raise ValueError("at least one demand is required")
    if margin < 0:
        raise ValueError("margin must be >= 0")
    if p_min is None:
        p_min = min_pressure(demands, dropout)
    breakdown = {d.name: d.gas_mass(g) for d in demands}
    m = sum(breakdown.values())
    need = m * (1 + margin)
    t_end = end_temperature(t_fill, p_fill, p_min, n)
    rho0, rho1 = density(g, p_fill, t_fill), density(g, p_min, t_end)
    u = rho0 - rho1
    need_ideal = sum(d.gas_mass(g, ideal=True) for d in demands) * (1 + margin)
    u_ideal = usable_density(g, p_fill, t_fill, p_min, n, ideal=True)
    return SizingResult(gas=g, volume=need / u, demand=m, demand_with_margin=need, breakdown=breakdown,
                        p_fill=p_fill, t_fill=t_fill, p_min=p_min, t_end=t_end, n=n, margin=margin,
                        rho_fill=rho0, rho_end=rho1, usable_density=u, ideal_gas_volume=need_ideal / u_ideal)


def blowdown_curve(gas, volume: float, p_fill: float, t_fill: float, p_min: float, n: float = 1.2,
                   steps: int = 50) -> List[Tuple[float, float, float]]:
    """Bottle state along a polytropic blowdown.

    Returns ``(delivered_mass_kg, pressure_Pa_abs, temperature_K)`` tuples from full down to ``p_min``.
    """
    g = get_gas(gas)
    m0 = density(g, p_fill, t_fill) * volume
    out = []
    for i in range(steps + 1):
        p = p_fill + (p_min - p_fill) * i / steps
        t = end_temperature(t_fill, p_fill, p, n)
        out.append((m0 - density(g, p, t) * volume, p, t))
    return out
