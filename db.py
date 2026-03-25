import sqlite3
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path

from config import STARTING_WEIGHT

DB_PATH = Path(__file__).parent / "bot.db"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS food_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                food_name TEXT NOT NULL,
                calories INTEGER NOT NULL,
                protein REAL DEFAULT 0,
                carbs REAL DEFAULT 0,
                fat REAL DEFAULT 0,
                is_restaurant INTEGER DEFAULT 0,
                raw_text TEXT,
                corrections TEXT
            );

            CREATE TABLE IF NOT EXISTS weight_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                weight REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS water_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                glasses INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS supplement_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                supplement_name TEXT NOT NULL,
                taken_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sleep_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                sleep_time TEXT,
                wake_time TEXT
            );

            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS mood_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                score INTEGER NOT NULL,
                note TEXT
            );

            CREATE TABLE IF NOT EXISTS workout_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                duration_mins INTEGER NOT NULL,
                calories_burned INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                waist REAL,
                arms REAL,
                chest REAL
            );

            CREATE TABLE IF NOT EXISTS milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                type TEXT NOT NULL,
                value TEXT,
                message TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                time TEXT NOT NULL,
                text TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ai_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                observation TEXT NOT NULL,
                data_json TEXT,
                confidence REAL DEFAULT 0.5,
                valid_from TEXT NOT NULL,
                valid_until TEXT,
                source TEXT
            );

            CREATE TABLE IF NOT EXISTS personal_food_db (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                calories INTEGER NOT NULL,
                protein REAL DEFAULT 0,
                carbs REAL DEFAULT 0,
                fat REAL DEFAULT 0,
                uses INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS fasting_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                duration_mins INTEGER
            );

            CREATE TABLE IF NOT EXISTS progress_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                file_id TEXT NOT NULL
            );
        """)
        defaults = [
            ("is_sleeping", "0"),
            ("first_food_today", ""),
            ("last_sleep_date", ""),
            ("pending_correction_food_id", ""),
            ("pending_correction_expires_at", ""),
            ("user_name", ""),
            ("user_diet", ""),
            ("user_wake_time", ""),
            ("user_motivation", ""),
            ("onboarding_step", "name"),
            ("notification_level", "normal"),
            ("notifications_paused_until", ""),
        ]
        for key, val in defaults:
            conn.execute(
                "INSERT OR IGNORE INTO bot_state (key, value) VALUES (?, ?)", (key, val)
            )


# ── State ──────────────────────────────────────────────────────────────────────

def get_state(key: str) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else ""


def set_state(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", (key, str(value))
        )


# ── Food ───────────────────────────────────────────────────────────────────────

def log_food(food_name, calories, protein, carbs, fat, is_restaurant=False, raw_text="", for_date=None) -> int:
    log_date = for_date if for_date else date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO food_logs
               (date, time, food_name, calories, protein, carbs, fat, is_restaurant, raw_text)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (log_date, now, food_name, calories, protein, carbs, fat, int(is_restaurant), raw_text),
        )
        return cur.lastrowid


def update_food_correction(food_id, food_name, calories, protein, carbs, fat):
    now = datetime.now().strftime("%H:%M")
    with get_conn() as conn:
        conn.execute(
            """UPDATE food_logs
               SET food_name=?, calories=?, protein=?, carbs=?, fat=?, corrections=?
               WHERE id=?""",
            (food_name, calories, protein, carbs, fat, f"corrected at {now}", food_id),
        )


def delete_food_log(food_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM food_logs WHERE id = ?", (food_id,))


def get_today_food() -> list[dict]:
    today = date.today().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM food_logs WHERE date = ? ORDER BY time", (today,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_today_totals() -> dict:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(calories),0) AS calories,
                      COALESCE(SUM(protein),0)  AS protein,
                      COALESCE(SUM(carbs),0)    AS carbs,
                      COALESCE(SUM(fat),0)      AS fat
               FROM food_logs WHERE date = ?""",
            (today,),
        ).fetchone()
        return dict(row)


# ── Weight ─────────────────────────────────────────────────────────────────────

def log_weight(weight: float):
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO weight_logs (date, weight) VALUES (?, ?)", (today, weight)
        )


def get_weight_history(days: int = 30) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, weight FROM weight_logs ORDER BY date DESC LIMIT ?", (days,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def get_latest_weight() -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT weight FROM weight_logs ORDER BY date DESC LIMIT 1"
        ).fetchone()
        return row["weight"] if row else STARTING_WEIGHT


# ── Water ──────────────────────────────────────────────────────────────────────

def log_water(glasses: int) -> int:
    today = date.today().isoformat()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT glasses FROM water_logs WHERE date = ?", (today,)
        ).fetchone()
        if existing:
            new_total = existing["glasses"] + glasses
            conn.execute("UPDATE water_logs SET glasses = ? WHERE date = ?", (new_total, today))
            return new_total
        conn.execute("INSERT INTO water_logs (date, glasses) VALUES (?, ?)", (today, glasses))
        return glasses


def get_today_water() -> int:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT glasses FROM water_logs WHERE date = ?", (today,)
        ).fetchone()
        return row["glasses"] if row else 0


# ── Supplements ────────────────────────────────────────────────────────────────

def log_supplement(supplement_name: str) -> bool:
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM supplement_logs WHERE date = ? AND supplement_name = ?",
            (today, supplement_name),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO supplement_logs (date, supplement_name, taken_at) VALUES (?, ?, ?)",
            (today, supplement_name, now),
        )
        return True


def get_today_supplements() -> list[str]:
    today = date.today().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT supplement_name FROM supplement_logs WHERE date = ?", (today,)
        ).fetchall()
        return [r["supplement_name"] for r in rows]


# ── Sleep ──────────────────────────────────────────────────────────────────────

def log_sleep(sleep_time: str | None = None):
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM sleep_logs WHERE date = ? AND wake_time IS NULL", (today,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO sleep_logs (date, sleep_time) VALUES (?, ?)",
                (today, sleep_time or now),
            )


def log_wake(wake_time: str | None = None):
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    now = datetime.now().strftime("%H:%M")
    with get_conn() as conn:
        for d in [today, yesterday]:
            row = conn.execute(
                "SELECT id FROM sleep_logs WHERE date = ? AND wake_time IS NULL", (d,)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE sleep_logs SET wake_time = ? WHERE id = ?",
                    (wake_time or now, row["id"]),
                )
                return
        # No open entry — create a complete one
        conn.execute(
            "INSERT INTO sleep_logs (date, sleep_time, wake_time) VALUES (?, ?, ?)",
            (today, "unknown", wake_time or now),
        )


def get_sleep_history(days: int = 7) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, sleep_time, wake_time FROM sleep_logs ORDER BY date DESC LIMIT ?",
            (days,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Stats ──────────────────────────────────────────────────────────────────────

def get_streak() -> int:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT date FROM food_logs ORDER BY date DESC LIMIT 60"
        ).fetchall()
    dates = [row["date"] for row in rows]
    if not dates:
        return 0
    streak = 0
    check = date.today()
    for d_str in dates:
        d = date.fromisoformat(d_str)
        if d == check:
            streak += 1
            check = check - timedelta(days=1)
        elif d == check - timedelta(days=1) and streak == 0:
            # Today not logged yet, start from yesterday
            check = d - timedelta(days=1)
            streak += 1
        else:
            break
    return streak


def get_weekly_stats() -> dict:
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT AVG(dc) AS avg_cal, AVG(dp) AS avg_protein
               FROM (
                   SELECT date,
                          SUM(calories) AS dc,
                          SUM(protein)  AS dp
                   FROM food_logs
                   WHERE date BETWEEN ? AND ?
                   GROUP BY date
               )""",
            (week_ago, today),
        ).fetchone()
        weights = conn.execute(
            "SELECT weight FROM weight_logs WHERE date BETWEEN ? AND ? ORDER BY date",
            (week_ago, today),
        ).fetchall()
    w_list = [r["weight"] for r in weights]
    return {
        "avg_calories": round(row["avg_cal"] or 0),
        "avg_protein": round(row["avg_protein"] or 0),
        "weight_start": w_list[0] if w_list else None,
        "weight_end": w_list[-1] if w_list else None,
        "weight_change": round(w_list[-1] - w_list[0], 1) if len(w_list) >= 2 else None,
    }


# ── 7-day rolling weight average ──────────────────────────────────────────────

def get_7day_weight_average() -> float | None:
    seven_ago = (date.today() - timedelta(days=7)).isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT AVG(weight) AS avg FROM weight_logs WHERE date >= ?", (seven_ago,)
        ).fetchone()
    return round(row["avg"], 1) if row["avg"] else None


# ── Mood ──────────────────────────────────────────────────────────────────────

def log_mood(score: int, note: str = ""):
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO mood_logs (date, time, score, note) VALUES (?, ?, ?, ?)",
            (today, now, score, note),
        )

def get_mood_history(days: int = 7) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, score, note FROM mood_logs WHERE date >= ? ORDER BY date DESC",
            (since,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Workout ───────────────────────────────────────────────────────────────────

def log_workout(workout_type: str, duration_mins: int, calories_burned: int = 0):
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO workout_logs (date, type, duration_mins, calories_burned) VALUES (?, ?, ?, ?)",
            (today, workout_type, duration_mins, calories_burned),
        )

def get_today_workout_burn() -> int:
    today = date.today().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(calories_burned), 0) AS total FROM workout_logs WHERE date = ?",
            (today,),
        ).fetchone()
    return row["total"]

def get_workouts(days: int = 7) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, type, duration_mins, calories_burned FROM workout_logs WHERE date >= ? ORDER BY date DESC",
            (since,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Measurements ──────────────────────────────────────────────────────────────

def log_measurement(waist: float = None, arms: float = None, chest: float = None):
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO measurements (date, waist, arms, chest) VALUES (?, ?, ?, ?)",
            (today, waist, arms, chest),
        )

def get_measurements(limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, waist, arms, chest FROM measurements ORDER BY date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── Milestones ────────────────────────────────────────────────────────────────

def log_milestone(milestone_type: str, value: str, message: str):
    today = date.today().isoformat()
    with get_conn() as conn:
        # Avoid duplicate milestone on same day
        existing = conn.execute(
            "SELECT id FROM milestones WHERE type = ? AND value = ?", (milestone_type, value)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO milestones (date, type, value, message) VALUES (?, ?, ?, ?)",
                (today, milestone_type, value, message),
            )
            return True
    return False

def get_milestones() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, type, value, message FROM milestones ORDER BY date DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Fasting sessions ──────────────────────────────────────────────────────────

def start_fast():
    now = datetime.now().isoformat()
    with get_conn() as conn:
        # Close any open session first
        conn.execute("UPDATE fasting_sessions SET end_time = ? WHERE end_time IS NULL", (now,))
        conn.execute("INSERT INTO fasting_sessions (start_time) VALUES (?)", (now,))

def end_fast() -> int | None:
    """Returns duration in minutes, or None if no open session."""
    now = datetime.now()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, start_time FROM fasting_sessions WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        start = datetime.fromisoformat(row["start_time"])
        duration = int((now - start).total_seconds() / 60)
        conn.execute(
            "UPDATE fasting_sessions SET end_time = ?, duration_mins = ? WHERE id = ?",
            (now.isoformat(), duration, row["id"]),
        )
    return duration

def get_current_fast_duration() -> int | None:
    """Returns minutes since fast started, or None if not fasting."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT start_time FROM fasting_sessions WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    start = datetime.fromisoformat(row["start_time"])
    return int((datetime.now() - start).total_seconds() / 60)


# ── AI Memory ────────────────────────────────────────────────────────────────

def save_observation(category: str, observation: str, confidence: float = 0.5,
                     data_json: str = "", source: str = "auto"):
    today = date.today().isoformat()
    with get_conn() as conn:
        # Expire any existing observation in this category with same text
        conn.execute(
            "UPDATE ai_memory SET valid_until = ? WHERE category = ? AND observation = ? AND valid_until IS NULL",
            (today, category, observation),
        )
        conn.execute(
            "INSERT INTO ai_memory (category, observation, data_json, confidence, valid_from, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (category, observation, data_json, confidence, today, source),
        )

def get_context_for_prompt(intent: str = "general") -> str:
    """Return relevant AI memory as a formatted string for prompt injection."""
    # Map intent → relevant categories
    category_map = {
        "food_log": ["eating_pattern", "weak_day"],
        "craving": ["craving", "eating_pattern"],
        "food_question": ["eating_pattern"],
        "ingredient_query": ["eating_pattern"],
        "general": ["eating_pattern", "sleep_pattern", "supplement_compliance", "weak_day"],
    }
    categories = category_map.get(intent, category_map["general"])
    placeholders = ",".join("?" * len(categories))
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT category, observation, confidence FROM ai_memory "
            f"WHERE category IN ({placeholders}) AND valid_until IS NULL AND confidence >= 0.5 "
            f"ORDER BY confidence DESC LIMIT 5",
            categories,
        ).fetchall()
    if not rows:
        return ""
    return "\n".join(f"- [{r['category']}] {r['observation']} (confidence: {r['confidence']:.0%})" for r in rows)


# ── Weekly adherence score ────────────────────────────────────────────────────

def get_weekly_adherence_score() -> dict:
    """Returns 0–100 score and breakdown for the past 7 days."""
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    today = date.today().isoformat()
    score = 0
    breakdown = {}

    with get_conn() as conn:
        # Calorie compliance (days within 10% of goal) — 30 pts
        rows = conn.execute(
            "SELECT date, SUM(calories) AS daily_cal FROM food_logs WHERE date BETWEEN ? AND ? GROUP BY date",
            (week_ago, today),
        ).fetchall()
        cal_days = sum(1 for r in rows if abs(r["daily_cal"] - 1500) <= 150)
        breakdown["calorie_days"] = f"{cal_days}/7"
        score += int((cal_days / 7) * 30)

        # Protein compliance (days >= 100g) — 30 pts
        rows = conn.execute(
            "SELECT date, SUM(protein) AS daily_prot FROM food_logs WHERE date BETWEEN ? AND ? GROUP BY date",
            (week_ago, today),
        ).fetchall()
        prot_days = sum(1 for r in rows if r["daily_prot"] >= 100)
        breakdown["protein_days"] = f"{prot_days}/7"
        score += int((prot_days / 7) * 30)

        # Water compliance (days >= WATER_GOAL) — 20 pts
        from config import WATER_GOAL
        rows = conn.execute(
            "SELECT glasses FROM water_logs WHERE date BETWEEN ? AND ?", (week_ago, today)
        ).fetchall()
        water_days = sum(1 for r in rows if r["glasses"] >= WATER_GOAL)
        breakdown["water_days"] = f"{water_days}/7"
        score += int((water_days / 7) * 20)

        # Logging streak (any food logged) — 20 pts
        rows = conn.execute(
            "SELECT DISTINCT date FROM food_logs WHERE date BETWEEN ? AND ?", (week_ago, today)
        ).fetchall()
        log_days = len(rows)
        breakdown["log_days"] = f"{log_days}/7"
        score += int((log_days / 7) * 20)

    breakdown["score"] = score
    return breakdown


def get_water_compliance_week() -> str:
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    today = date.today().isoformat()
    from config import WATER_GOAL
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT glasses FROM water_logs WHERE date BETWEEN ? AND ?", (week_ago, today)
        ).fetchall()
    hit = sum(1 for r in rows if r["glasses"] >= WATER_GOAL)
    return f"{hit}/7 days"


# ── Personal food DB ──────────────────────────────────────────────────────────

def add_or_update_personal_food(name: str, calories: int, protein: float, carbs: float, fat: float):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO personal_food_db (name, calories, protein, carbs, fat, uses)
               VALUES (?, ?, ?, ?, ?, 1)
               ON CONFLICT(name) DO UPDATE SET
               calories=excluded.calories, protein=excluded.protein,
               carbs=excluded.carbs, fat=excluded.fat, uses=uses+1""",
            (name.lower(), calories, protein, carbs, fat),
        )

def search_personal_food(name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM personal_food_db WHERE name LIKE ? ORDER BY uses DESC LIMIT 1",
            (f"%{name.lower()}%",),
        ).fetchone()
    return dict(row) if row else None


# ── Progress photos ──────────────────────────────────────────────────────────

def save_progress_photo(file_id: str):
    today = date.today().isoformat()
    with get_conn() as conn:
        conn.execute("INSERT INTO progress_photos (date, file_id) VALUES (?, ?)", (today, file_id))

def get_progress_photos(limit: int = 4) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, file_id FROM progress_photos ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Plateau detection ────────────────────────────────────────────────────────

def is_plateau(days: int = 5) -> bool:
    """Returns True if weight hasn't changed by more than 0.3 kg in `days` days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT weight FROM weight_logs WHERE date >= ? ORDER BY date", (since,)
        ).fetchall()
    if len(rows) < days:
        return False
    weights = [r["weight"] for r in rows]
    return (max(weights) - min(weights)) <= 0.3
