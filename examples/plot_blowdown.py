"""Plot bottle pressure and temperature vs delivered gas for N2 and He (needs matplotlib).

    python examples/plot_blowdown.py docs/img/blowdown.svg
"""
import sys

import matplotlib.pyplot as plt

import pressurant as P

demands = [
    P.TankDemand("oxidiser tank", 8e-3, P.bar_g(35), 263.15, dissolution=0.05),
    P.TankDemand("fuel tank", 4e-3, P.bar_g(35), 273.15),
]

fig, (ax_p, ax_z) = plt.subplots(1, 2, figsize=(10, 4))
for gas, colour in (("N2", "#1f5fa8"), ("He", "#d0661d")):
    r = P.size_bottle(gas, demands, P.bar_g(310), margin=0.15)
    for n, style in ((1.0, ":"), (1.2, "-"), (r.gas.gamma, "--")):
        curve = P.blowdown_curve(gas, r.volume, r.p_fill, r.t_fill, r.p_min, n=n)
        ax_p.plot([c[0] / r.demand_with_margin * 100 for c in curve], [P.to_bar_g(c[1]) for c in curve],
                  style, color=colour, label=f"{r.gas.name}, n = {n:g}")
    ax_p.annotate(f"{r.gas.name} bottle: {r.volume_l:.2f} L", (2, 75 - (14 if gas == "He" else 0)),
                  color=colour)
ax_p.set_xlabel("gas delivered [% of design demand]")
ax_p.set_ylabel("bottle pressure [bar g]")
ax_p.set_title("Blowdown of a bottle sized for n = 1.2")
ax_p.legend(fontsize=8)
ax_p.grid(alpha=0.3)

p = [x * 1e5 for x in range(5, 401, 5)]
for gas, colour in (("N2", "#1f5fa8"), ("He", "#d0661d"), ("Ar", "#5a8f29")):
    ax_z.plot([x / 1e5 for x in p], [P.z_factor(gas, x, 293.15) for x in p], color=colour, label=P.get_gas(gas).name)
ax_z.axhline(1.0, color="grey", lw=0.8)
ax_z.set_xlabel("pressure [bar abs]")
ax_z.set_ylabel("compressibility factor Z at 20 C")
ax_z.set_title("Why an ideal-gas model is not enough")
ax_z.legend(fontsize=8)
ax_z.grid(alpha=0.3)

fig.tight_layout()
fig.savefig(sys.argv[1] if len(sys.argv) > 1 else "blowdown.png", dpi=150)
