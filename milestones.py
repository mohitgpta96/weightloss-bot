"""
Milestone detection — weight milestones and behavior milestones.
"""
import db
from config import STARTING_WEIGHT


def check_weight_milestone(current_weight: float) -> str | None:
    """
    Returns a celebration message if a new 1 kg milestone was just crossed,
    else None. Logs the milestone to DB.
    """
    kg_lost = STARTING_WEIGHT - current_weight
    if kg_lost <= 0:
        return None

    # Check each integer milestone (1 kg, 2 kg, 3 kg...)
    milestone_kg = int(kg_lost)
    if milestone_kg == 0:
        return None

    milestone_value = f"weight_{milestone_kg}kg"
    logged = db.log_milestone(
        milestone_type="weight",
        value=milestone_value,
        message=f"Lost {milestone_kg} kg total",
    )
    if not logged:
        return None  # Already celebrated this milestone

    messages = {
        1:  "🎉 *1 kg down!* You've started. This is real.",
        2:  "🔥 *2 kg lost!* Your body is responding. Keep going.",
        3:  "💪 *3 kg down!* You're proving this works.",
        4:  "⚡ *4 kg lost!* Halfway to 8 kg. You're crushing it.",
        5:  "🏆 *5 kg gone!* This is a huge milestone. You've built a real habit.",
        7:  "🚀 *7 kg down!* The momentum is undeniable now.",
        10: "🌟 *10 kg lost!* Half the journey. You've transformed your relationship with food.",
        15: "👑 *15 kg gone!* 75% there. Most people quit before reaching this.",
        20: "🎊 *20 KG LOST! GOAL ACHIEVED!* You did what most people only talk about.",
    }
    msg = messages.get(milestone_kg, f"🎉 *{milestone_kg} kg lost!* Every kilo counts. Well done.")
    return msg


def check_behavior_milestone(streak: int, protein_days_this_week: int = 0,
                              water_days_this_week: int = 0) -> str | None:
    """
    Checks behavior-based milestones (streak, protein, water compliance).
    Returns celebration message or None.
    """
    result = None

    # Streak milestones
    streak_milestones = {7: "7-day streak", 14: "14-day streak", 30: "30-day streak",
                         60: "60-day streak", 90: "90-day streak"}
    if streak in streak_milestones:
        logged = db.log_milestone(
            milestone_type="streak",
            value=streak_milestones[streak],
            message=f"{streak}-day logging streak",
        )
        if logged:
            if streak == 7:
                result = "🔥 *7-day streak!* One full week of consistency — that's how habits form."
            elif streak == 14:
                result = "🔥🔥 *14-day streak!* Two weeks straight. This is becoming automatic."
            elif streak == 30:
                result = "🏆 *30-day streak!* One month of daily logging. You're in the top 5% of people who start."
            elif streak == 60:
                result = "👑 *60-day streak!* Two months. This isn't willpower anymore — it's who you are."
            elif streak == 90:
                result = "🌟 *90-day streak!* 3 months. The habit is permanent now."

    # Protein compliance milestone
    if protein_days_this_week >= 5 and not result:
        logged = db.log_milestone(
            milestone_type="protein",
            value=f"protein_5days_{db.date.today().isocalendar()[1]}",
            message="Hit protein goal 5+ days this week",
        )
        if logged:
            result = "💪 *Protein goal hit 5 days this week!* 150g/day is hard — you made it look easy."

    # Water compliance milestone
    if water_days_this_week >= 7 and not result:
        logged = db.log_milestone(
            milestone_type="water",
            value=f"water_7days_{db.date.today().isocalendar()[1]}",
            message="Hit water goal every day this week",
        )
        if logged:
            result = "💧 *Perfect water week!* 14 glasses every day — your metabolism is optimized."

    return result
