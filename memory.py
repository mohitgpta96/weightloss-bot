"""
AI memory system — learns patterns from logs over time.
Stores observations with temporal metadata and confidence scores.
"""
import json
from datetime import date, timedelta

import db


def update_from_logs():
    """
    Weekly job: analyze last 4 weeks of data and save observations to ai_memory.
    Called by scheduler every Sunday.
    """
    today = date.today()
    four_weeks_ago = (today - timedelta(weeks=4)).isoformat()
    today_str = today.isoformat()

    # ── Weak day detection ────────────────────────────────────────────────────
    import sqlite3
    from pathlib import Path
    conn = sqlite3.connect(db.DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            "SELECT date, SUM(calories) AS cal FROM food_logs "
            "WHERE date BETWEEN ? AND ? GROUP BY date",
            (four_weeks_ago, today_str),
        ).fetchall()

        day_totals: dict[str, list[float]] = {}
        for r in rows:
            d = date.fromisoformat(r["date"])
            day_name = d.strftime("%A")  # Monday, Tuesday, ...
            day_totals.setdefault(day_name, []).append(r["cal"])

        for day_name, cals in day_totals.items():
            avg = sum(cals) / len(cals)
            if avg > 1800:
                db.save_observation(
                    category="weak_day",
                    observation=f"User tends to overeat on {day_name}s (avg {avg:.0f} kcal)",
                    confidence=min(0.5 + len(cals) * 0.1, 0.95),
                    data_json=json.dumps({"day": day_name, "avg_kcal": round(avg), "samples": len(cals)}),
                    source="weekly_analysis",
                )

        # ── Supplement compliance ─────────────────────────────────────────────
        supp_rows = conn.execute(
            "SELECT COUNT(DISTINCT date) AS days FROM supplement_logs WHERE date BETWEEN ? AND ?",
            (four_weeks_ago, today_str),
        ).fetchone()
        total_days = (today - date.fromisoformat(four_weeks_ago)).days
        compliance = (supp_rows["days"] / total_days) if total_days else 0
        if compliance < 0.5:
            db.save_observation(
                category="supplement_compliance",
                observation=f"Low supplement compliance ({compliance:.0%}) — reminders may not be working",
                confidence=0.8,
                source="weekly_analysis",
            )

        # ── Eating pattern: late eating ───────────────────────────────────────
        late_rows = conn.execute(
            "SELECT COUNT(*) AS cnt FROM food_logs WHERE time >= '21:30' AND date BETWEEN ? AND ?",
            (four_weeks_ago, today_str),
        ).fetchone()
        if late_rows["cnt"] >= 5:
            db.save_observation(
                category="eating_pattern",
                observation=f"User frequently eats after 9:30 PM ({late_rows['cnt']} times in 4 weeks) — breaking fasting window",
                confidence=0.85,
                source="weekly_analysis",
            )

        # ── Protein pattern ───────────────────────────────────────────────────
        prot_rows = conn.execute(
            "SELECT date, SUM(protein) AS dp FROM food_logs WHERE date BETWEEN ? AND ? GROUP BY date",
            (four_weeks_ago, today_str),
        ).fetchall()
        if prot_rows:
            avg_prot = sum(r["dp"] for r in prot_rows) / len(prot_rows)
            if avg_prot < 100:
                db.save_observation(
                    category="eating_pattern",
                    observation=f"Consistently low protein (avg {avg_prot:.0f}g/day vs 150g goal)",
                    confidence=0.9,
                    source="weekly_analysis",
                )

    finally:
        conn.close()


def get_context_for_prompt(intent: str = "general") -> str:
    """Thin wrapper around db.get_context_for_prompt for use in ai.py."""
    return db.get_context_for_prompt(intent)
