import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

from config import STARTING_WEIGHT


def generate_weight_chart(weight_history: list[dict], target_weight: float = 70.0) -> bytes | None:
    if not weight_history:
        return None

    dates = [datetime.strptime(r["date"], "%Y-%m-%d").date() for r in weight_history]
    weights = [r["weight"] for r in weight_history]

    # 7-day rolling average
    rolling_avg = []
    for i in range(len(weights)):
        window = weights[max(0, i - 6): i + 1]
        rolling_avg.append(sum(window) / len(window))

    # Milestone points (every 1 kg lost from start)
    milestone_dates = []
    milestone_weights = []
    seen_milestones = set()
    for d, w in zip(dates, weights):
        kg_lost = int(STARTING_WEIGHT - w)
        if kg_lost > 0 and kg_lost not in seen_milestones:
            seen_milestones.add(kg_lost)
            milestone_dates.append(d)
            milestone_weights.append(w)

    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#161b22")

    # Actual weight line
    ax.plot(
        dates, weights,
        color="#58a6ff", linewidth=2.5, marker="o",
        markersize=5, markerfacecolor="#58a6ff", label="Weight",
    )
    ax.fill_between(dates, weights, min(weights) - 0.5, alpha=0.12, color="#58a6ff")

    # 7-day rolling average
    if len(dates) >= 3:
        ax.plot(
            dates, rolling_avg,
            color="#f0883e", linewidth=1.8, linestyle="-",
            alpha=0.85, label="7-day avg",
        )

    # Milestone dots (gold)
    if milestone_dates:
        ax.scatter(
            milestone_dates, milestone_weights,
            color="#ffd700", s=70, zorder=5, label="Milestones",
            edgecolors="#0d1117", linewidths=0.8,
        )

    # Goal line
    ax.axhline(
        y=target_weight, color="#f85149", linestyle="--",
        linewidth=1.5, alpha=0.85, label=f"Goal: {target_weight} kg",
    )

    # Starting weight reference
    ax.axhline(
        y=STARTING_WEIGHT, color="#6e7681", linestyle=":", linewidth=1, alpha=0.5,
        label=f"Start: {STARTING_WEIGHT} kg"
    )

    ax.set_xlabel("Date", color="#8b949e", fontsize=9)
    ax.set_ylabel("Weight (kg)", color="#8b949e", fontsize=9)
    ax.tick_params(colors="#8b949e", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#30363d")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.yaxis.grid(True, color="#21262d", linewidth=0.8)
    ax.xaxis.grid(False)

    if len(dates) > 1:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        fig.autofmt_xdate(rotation=30)

    current = weights[-1]
    lost = STARTING_WEIGHT - current
    ax.set_title(
        f"Weight: {current:.1f} kg  |  Lost: {lost:.1f} kg  |  Remaining: {current - target_weight:.1f} kg",
        color="#e6edf3", fontsize=11, pad=12, fontweight="bold",
    )

    ax.legend(
        facecolor="#161b22", labelcolor="#c9d1d9",
        framealpha=0.9, edgecolor="#30363d", fontsize=8,
    )

    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, facecolor="#0d1117")
    buf.seek(0)
    plt.close(fig)
    return buf.read()


def generate_weekly_card(stats: dict) -> bytes | None:
    """
    Generate a shareable weekly summary card.

    stats keys: week_number, weight_change (float|None), weight_current,
                total_lost, streak, score (0-100)
    """
    fig, ax = plt.subplots(figsize=(6, 4))
    fig.patch.set_facecolor("#0d1117")
    ax.set_facecolor("#0d1117")
    ax.axis("off")

    week_number = stats.get("week_number", "?")
    weight_change = stats.get("weight_change")
    weight_current = stats.get("weight_current", "?")
    total_lost = stats.get("total_lost", 0)
    streak = stats.get("streak", 0)
    score = stats.get("score", 0)

    # Score color
    if score >= 80:
        score_color = "#3fb950"
    elif score >= 50:
        score_color = "#f0883e"
    else:
        score_color = "#f85149"

    # Change arrow
    if weight_change is not None:
        change_str = f"{weight_change:+.1f} kg"
        change_color = "#3fb950" if weight_change < 0 else "#f85149"
    else:
        change_str = "—"
        change_color = "#8b949e"

    # Title
    ax.text(0.5, 0.93, f"Week {week_number} Complete ✅",
            ha="center", va="top", fontsize=14, fontweight="bold",
            color="#e6edf3", transform=ax.transAxes)

    # Divider
    ax.axhline(y=0.82, xmin=0.05, xmax=0.95, color="#30363d", linewidth=0.8,
               transform=ax.transAxes)

    # Stats row 1: weight change + current
    ax.text(0.25, 0.72, "This week",
            ha="center", va="center", fontsize=8, color="#8b949e", transform=ax.transAxes)
    ax.text(0.25, 0.60, change_str,
            ha="center", va="center", fontsize=18, fontweight="bold",
            color=change_color, transform=ax.transAxes)

    ax.text(0.75, 0.72, "Current",
            ha="center", va="center", fontsize=8, color="#8b949e", transform=ax.transAxes)
    ax.text(0.75, 0.60, f"{weight_current} kg",
            ha="center", va="center", fontsize=18, fontweight="bold",
            color="#58a6ff", transform=ax.transAxes)

    # Stats row 2
    ax.text(0.2, 0.44, "Total lost",
            ha="center", va="center", fontsize=8, color="#8b949e", transform=ax.transAxes)
    ax.text(0.2, 0.32, f"{total_lost} kg",
            ha="center", va="center", fontsize=15, fontweight="bold",
            color="#e6edf3", transform=ax.transAxes)

    ax.text(0.5, 0.44, "Streak",
            ha="center", va="center", fontsize=8, color="#8b949e", transform=ax.transAxes)
    ax.text(0.5, 0.32, f"🔥 {streak}d",
            ha="center", va="center", fontsize=15, fontweight="bold",
            color="#e6edf3", transform=ax.transAxes)

    ax.text(0.8, 0.44, "Score",
            ha="center", va="center", fontsize=8, color="#8b949e", transform=ax.transAxes)
    ax.text(0.8, 0.32, f"{score}/100",
            ha="center", va="center", fontsize=15, fontweight="bold",
            color=score_color, transform=ax.transAxes)

    # Footer
    ax.axhline(y=0.18, xmin=0.05, xmax=0.95, color="#30363d", linewidth=0.8,
               transform=ax.transAxes)
    ax.text(0.5, 0.09, "Keep going. Every logged meal counts.",
            ha="center", va="center", fontsize=8, color="#6e7681",
            style="italic", transform=ax.transAxes)

    plt.tight_layout(pad=0.5)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, facecolor="#0d1117")
    buf.seek(0)
    plt.close(fig)
    return buf.read()
