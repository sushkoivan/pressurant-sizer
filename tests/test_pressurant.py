import json
from pathlib import Path

import pytest

import pressurant as P
from pressurant.cli import main
from pressurant.eos import _cubic_roots

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# Reference compressibility factors from CoolProp 7 (Span-Wagner / Helmholtz reference equations).
REFERENCE_Z = [
    ("N2", 300e5, 293.15, 1.1401),
    ("N2", 200e5, 293.15, 1.0518),
    ("N2", 50e5, 250.0, 0.9690),
    ("N2", 100e5, 200.0, 0.8447),
    ("He", 300e5, 293.15, 1.1413),
    ("He", 200e5, 293.15, 1.0952),
    ("Ar", 200e5, 293.15, 0.9443),
    ("air", 200e5, 293.15, 1.0260),
]


@pytest.mark.parametrize("gas,p,t,z_ref", REFERENCE_Z)
def test_peng_robinson_within_5_percent_of_reference(gas, p, t, z_ref):
    assert P.z_factor_pr(gas, p, t) == pytest.approx(z_ref, rel=0.05)


def test_low_pressure_is_ideal():
    for gas in ("N2", "He", "Ar", "air", "CO2"):
        assert P.z_factor_pr(gas, 1e5, 300.0) == pytest.approx(1.0, abs=0.01)


def test_cubic_roots():
    # (x-1)(x-2)(x-3) = x^3 - 6x^2 + 11x - 6
    assert sorted(_cubic_roots(-6, 11, -6)) == pytest.approx([1, 2, 3])
    assert _cubic_roots(0, 0, -8) == pytest.approx([2])


def test_density_ideal():
    rho = P.density_ideal("N2", 1e5, 273.15)
    assert rho == pytest.approx(1.2334, rel=1e-3)


def test_get_gas():
    assert P.get_gas("Nitrogen") is P.NITROGEN
    assert P.get_gas(P.HELIUM) is P.HELIUM
    with pytest.raises(ValueError):
        P.get_gas("unobtainium")


def test_pressure_conversion_roundtrip():
    assert P.to_bar_g(P.bar_g(42.0)) == pytest.approx(42.0)
    assert P.bar_g(0.0) == pytest.approx(P.P_ATM)


def test_thruster_mass_closed_form():
    d = P.ThrusterDemand("rcs", thrust=9.80665, isp=50.0, firing_time=10.0, count=2)
    # mdot = F / (Isp g0) = 0.02 kg/s per thruster
    assert d.gas_mass(P.NITROGEN) == pytest.approx(0.4)


def test_isp_per_gas():
    d = P.ThrusterDemand("rcs", 1.0, {"N2": 70.0, "helium": 165.0}, 10.0)
    assert d.isp_for(P.HELIUM) == 165.0
    assert d.gas_mass(P.NITROGEN) > d.gas_mass(P.HELIUM)
    with pytest.raises(ValueError):
        d.gas_mass(P.ARGON)


def test_tank_demand_options():
    t = P.TankDemand("t", 0.01, P.bar_g(30), 280.0)
    base = t.gas_mass(P.NITROGEN)
    assert P.TankDemand("t", 0.01, P.bar_g(30), 280.0, dissolution=0.1).gas_mass(P.NITROGEN) == pytest.approx(1.1 * base)
    assert P.TankDemand("t", 0.01, P.bar_g(30), 280.0, prepressurised_fraction=0.25).gas_mass(P.NITROGEN) == pytest.approx(0.75 * base)


def test_isothermal_ideal_matches_hand_calc():
    """Ideal gas, isothermal, fixed mass demand: V = m (1+margin) / ((p0 - pmin) / RT)."""
    p0, pmin, t, m = P.bar_g(200), P.bar_g(20), 293.15, 0.5
    u = P.usable_density("N2", p0, t, pmin, n=1.0, ideal=True)
    assert u == pytest.approx((p0 - pmin) / (P.NITROGEN.r_specific * t))
    r = P.size_bottle("N2", [P.MassDemand("x", m)], p0, t, p_min=pmin, n=1.0, margin=0.1)
    assert r.ideal_gas_volume == pytest.approx(m * 1.1 / u)


def test_real_gas_needs_bigger_bottle_than_ideal_at_high_pressure():
    r = P.size_bottle("N2", [P.TankDemand("t", 0.01, P.bar_g(30))], P.bar_g(300))
    assert r.volume > 1.05 * r.ideal_gas_volume


def test_adiabatic_needs_more_volume_than_isothermal():
    demands = [P.TankDemand("t", 0.005, P.bar_g(40))]
    v = [P.size_bottle("N2", demands, P.bar_g(300), n=n).volume for n in (1.0, 1.2, 1.4)]
    assert v[0] < v[1] < v[2]


def test_end_temperature():
    assert P.end_temperature(300.0, 300e5, 30e5, 1.0) == pytest.approx(300.0)
    assert P.end_temperature(300.0, 300e5, 30e5, 1.4) == pytest.approx(300.0 * 0.1 ** (0.4 / 1.4))
    with pytest.raises(ValueError):
        P.end_temperature(300.0, 300e5, 30e5, 0.9)


def test_default_min_pressure_uses_highest_tank_plus_dropout():
    d = [P.TankDemand("a", 0.001, P.bar_g(20)), P.TankDemand("b", 0.001, P.bar_g(35))]
    r = P.size_bottle("N2", d, P.bar_g(300), dropout=10e5)
    assert P.to_bar_g(r.p_min) == pytest.approx(45.0)


def test_bottle_delivers_exactly_the_demand():
    """Consistency: the mass released along the blowdown curve equals the demand with margin."""
    d = [P.TankDemand("t", 0.006, P.bar_g(25), 270.0), P.ThrusterDemand("rcs", 2.0, 60.0, 5.0, 2)]
    r = P.size_bottle("He", d, P.bar_g(300), margin=0.2)
    curve = P.blowdown_curve("He", r.volume, r.p_fill, r.t_fill, r.p_min, r.n, steps=10)
    assert curve[0][0] == pytest.approx(0.0, abs=1e-12)
    assert curve[-1][0] == pytest.approx(r.demand_with_margin, rel=1e-9)
    assert all(b[0] >= a[0] for a, b in zip(curve, curve[1:]))


def test_stored_energy_positive_and_scales_with_volume():
    d = [P.MassDemand("x", 0.3)]
    r1 = P.size_bottle("N2", d, P.bar_g(300))
    r2 = P.size_bottle("N2", [P.MassDemand("x", 0.6)], P.bar_g(300))
    assert r1.stored_energy > 0
    assert r2.stored_energy == pytest.approx(2 * r1.stored_energy)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        P.size_bottle("N2", [], P.bar_g(300))
    with pytest.raises(ValueError):
        P.size_bottle("N2", [P.TankDemand("t", 0.01, P.bar_g(300))], P.bar_g(200))
    with pytest.raises(ValueError):
        P.z_factor_pr("N2", -1.0, 300.0)


def test_report_and_dict():
    r = P.size_bottle("N2", [P.TankDemand("fuel", 0.004, P.bar_g(30))], P.bar_g(300))
    assert "required volume" in r.report()
    d = r.to_dict()
    assert d["volume_L"] == pytest.approx(r.volume_l)
    json.dumps(d)


def test_coolprop_backend_agrees():
    pytest.importorskip("CoolProp")
    P.set_backend("coolprop")
    try:
        assert P.z_factor("N2", 300e5, 293.15) == pytest.approx(1.1401, rel=1e-3)
    finally:
        P.set_backend("pr")


def test_cli_with_example(tmp_path, capsys):
    out = tmp_path / "r.json"
    assert main([str(EXAMPLES / "biprop_vehicle.json"), "--sweep", "--json", str(out)]) == 0
    data = json.loads(out.read_text())
    assert [d["gas"] for d in data] == ["nitrogen", "helium"]
    assert "Comparison" in capsys.readouterr().out


def test_cli_inline_arguments(capsys):
    assert main(["--gas", "N2", "--fill", "250", "--tank", "ox,5,30,-5,0.05", "--thruster", "rcs,1,60,10,2"]) == 0
    assert "required volume" in capsys.readouterr().out


def test_cli_without_demands_fails():
    assert main([]) == 2
