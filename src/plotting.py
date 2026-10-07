"""Plots shared by the DHNx steps."""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PIPE_COLORS = {"DN-25": "#9ecae1", "DN-32": "#4292c6", "DN-40": "#41ab5d",
               "DN-50": "#fd8d3c", "DN-63": "#d7301f"}


def plot_network(producers, forks, consumers, candidates, built, names,
                 title, path):
    """Candidate pipes in grey, built pipes coloured by type with capacity labels."""
    pts = {}
    for kind, d in [("producers", producers), ("forks", forks),
                    ("consumers", consumers)]:
        for i, xy in d.items():
            pts[f"{kind}-{i}"] = xy

    fig, ax = plt.subplots(figsize=(10, 7))
    for _, p in candidates.iterrows():
        (x1, y1), (x2, y2) = pts[p["from_node"]], pts[p["to_node"]]
        ax.plot([x1, x2], [y1, y2], color="lightgrey", lw=1.5, ls="--", zorder=1)
    for _, p in built.iterrows():
        (x1, y1), (x2, y2) = pts[p["from_node"]], pts[p["to_node"]]
        ax.plot([x1, x2], [y1, y2], color=PIPE_COLORS[p["hp_type"]], lw=4, zorder=2)
        ax.annotate(f"{p['capacity']:.0f} kW", ((x1 + x2) / 2, (y1 + y2) / 2),
                    fontsize=7, ha="center", va="bottom", zorder=4)

    for i, (x, y) in producers.items():
        ax.scatter(x, y, s=220, marker="s", color="#e31a1c", zorder=3)
        ax.annotate(f"P{i}: {names['producers'][i]}", (x, y), xytext=(6, 8),
                    textcoords="offset points", fontsize=8, color="#e31a1c")
    for i, (x, y) in forks.items():
        ax.scatter(x, y, s=30, color="black", zorder=3)
        ax.annotate(f"F{i}", (x, y), xytext=(4, -10), textcoords="offset points",
                    fontsize=7)
    for i, (x, y) in consumers.items():
        ax.scatter(x, y, s=150, marker="^", color="#33a02c", zorder=3)
        ax.annotate(f"C{i}: {names['consumers'][i]}", (x, y), xytext=(6, 6),
                    textcoords="offset points", fontsize=8, color="#33a02c")

    for t in sorted(built["hp_type"].unique()):
        ax.plot([], [], color=PIPE_COLORS[t], lw=4, label=t)
    ax.plot([], [], color="lightgrey", lw=1.5, ls="--", label="candidate, not built")
    ax.legend(loc="best", fontsize=8)
    ax.set_title(title)
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_producers(prod, names, demand_total, title, path):
    """Hourly producer output (daily mean for readability) and demand."""
    fig, ax = plt.subplots(figsize=(11, 4.5))
    daily = prod.groupby(prod.index // 24).mean()
    ax.stackplot(daily.index, *[daily[c] for c in daily.columns],
                 labels=[names[c] for c in daily.columns], alpha=0.8)
    d = demand_total.reset_index(drop=True)
    ax.plot(d.groupby(d.index // 24).mean().values, color="black", lw=1,
            label="consumer demand (no losses)")
    ax.set_xlabel("day of year")
    ax.set_ylabel("heat [kW], daily mean")
    ax.set_title(title)
    ax.legend(fontsize=8, loc="upper center")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
