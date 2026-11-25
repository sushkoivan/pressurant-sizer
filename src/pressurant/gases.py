"""Gas property data used by the Peng-Robinson equation of state."""
from __future__ import annotations

from dataclasses import dataclass

R_UNIVERSAL = 8.314462618  # J/(mol K)


@dataclass(frozen=True)
class Gas:
    """Constants of a pure gas (or a pseudo-pure mixture such as air).

    Attributes:
        name: display name
        molar_mass: kg/mol
        t_crit: critical temperature [K]
        p_crit: critical pressure [Pa]
        omega: Pitzer acentric factor [-]
        gamma: ideal-gas heat-capacity ratio cp/cv near room temperature [-]
        coolprop_name: fluid name for the optional CoolProp backend
    """

    name: str
    molar_mass: float
    t_crit: float
    p_crit: float
    omega: float
    gamma: float
    coolprop_name: str

    @property
    def r_specific(self) -> float:
        """Specific gas constant R/M [J/(kg K)]."""
        return R_UNIVERSAL / self.molar_mass


# Critical constants and acentric factors: NIST Chemistry WebBook / Poling, Prausnitz & O'Connell,
# "The Properties of Gases and Liquids", 5th ed., Appendix A.
NITROGEN = Gas("nitrogen", 28.0134e-3, 126.19, 33.958e5, 0.0372, 1.400, "Nitrogen")
HELIUM = Gas("helium", 4.002602e-3, 5.1953, 2.2832e5, -0.382, 1.667, "Helium")
ARGON = Gas("argon", 39.948e-3, 150.687, 48.630e5, -0.00219, 1.667, "Argon")
AIR = Gas("air", 28.9586e-3, 132.53, 37.86e5, 0.0335, 1.400, "Air")
CARBON_DIOXIDE = Gas("carbon dioxide", 44.0095e-3, 304.13, 73.773e5, 0.2239, 1.289, "CarbonDioxide")

GASES = {
    "n2": NITROGEN, "nitrogen": NITROGEN,
    "he": HELIUM, "helium": HELIUM,
    "ar": ARGON, "argon": ARGON,
    "air": AIR,
    "co2": CARBON_DIOXIDE, "carbon dioxide": CARBON_DIOXIDE,
}


def get_gas(name: str | Gas) -> Gas:
    """Look up a gas by name or symbol (case-insensitive). A `Gas` instance is returned unchanged."""
    if isinstance(name, Gas):
        return name
    try:
        return GASES[name.strip().lower()]
    except KeyError:
        raise ValueError(f"unknown gas {name!r}; known: {sorted(set(g.name for g in GASES.values()))}") from None
