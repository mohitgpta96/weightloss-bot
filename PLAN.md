# Weight Loss Bot — Build Plan & Status

## The Mission

**Goal:** 80 kg → 70 kg by April 25, 2026
**Start date:** March 22, 2026
**Days:** 34

### Realistic Projection

| Type | Amount |
|------|--------|
| Water weight + glycogen (Week 1) | 2–3 kg |
| Actual fat (Weeks 2–5, ~1 kg/week) | 4–5 kg |
| **Realistic total by April 25** | **6–8 kg** |

### The Math

- TDEE at 80 kg (sedentary): ~2,100 kcal/day
- Calorie target: **1,200 kcal/day**
- Deficit from food: 900 kcal/day
- Daily 45-min brisk walk: +350 kcal burned
- **Total daily deficit: 1,250 kcal ≈ 1.1 kg/week fat loss**

### Week-by-Week

| Week | Dates | Expected weight |
|------|-------|----------------|
| Week 1 | Mar 22–28 | 77–78 kg |
| Week 2 | Mar 29–Apr 4 | 76–77 kg |
| Week 3 | Apr 5–11 | 75–76 kg |
| Week 4 | Apr 12–18 | 74–75 kg |
| Week 5 (partial) | Apr 19–25 | 73–74 kg |

---

## Files Built

Location: `/Users/mohit/Desktop/Figuring Out/weightloss_bot/`

| File | Status | What it does |
|------|--------|-------------|
| `main.py` | ✅ Done | Entry point — starts bot + scheduler |
| `config.py` | ✅ Done | All targets and constants |
| `db.py` | ✅ Done | SQLite — 6 tables |
| `ai.py` | ✅ Done | 4 Groq AI functions |
| `bot.py` | ✅ Done | All Telegram command handlers |
| `charts.py` | ✅ Done | Dark-theme weight progress chart |
| `requirements.txt` | ✅ Done | All dependencies |
| `.env.example` | ✅ Done | Env template |

### Database Tables (db.py)

1. `food_logs` — calorie + macro entries
2. `weight_logs` — daily weigh-ins
3. `water_logs` — glass-by-glass tracking
4. `sleep_logs` — hours + quality
5. `supplement_logs` — daily supplement compliance
6. `user_settings` — per-user config

### Bot Commands (bot.py)

- `/start` — onboarding
- `/today` — full daily dashboard (calories, protein, water, sleep)
- `/log [food]` — log a meal (AI estimates calories + macros)
- `/weight [kg]` — log weight
- `/water` — log a glass of water
- `/sleep [hours]` — log sleep
- `/supplements` — mark supplements taken
- `/progress` — weight chart (last 30 days)
- `/report` — weekly summary
- `/help` — all commands

### AI Functions (ai.py — using Groq)

1. `estimate_food_calories(food_description)` — returns kcal + protein + carbs + fat
2. `generate_daily_summary(day_data)` — end-of-day AI coach message
3. `answer_food_question(question, context)` — "kya main X kha sakta hoon?"
4. `generate_motivation(stats)` — context-aware encouragement

---

## Config Values

```python
STARTING_WEIGHT = 80.0    # kg
TARGET_WEIGHT   = 70.0    # kg
CALORIE_GOAL    = 1200    # kcal/day (aggressive cut)
PROTEIN_GOAL    = 150     # grams/day
WATER_GOAL      = 16      # glasses/day
```

---

## To Run the Bot

1. Get credentials:
   - Telegram Bot Token — from @BotFather
   - Groq API Key — from console.groq.com
   - Your Telegram Chat ID

2. Create your `.env` file:
   ```
   cp .env.example .env
   # fill in the 3 values
   ```

3. Install and run:
   ```
   pip install -r requirements.txt
   python main.py
   ```

---

## Next: World-Class Upgrade (not yet built)

Phase 2 adds proactive AI coaching on top of the logging platform:

- **8 new DB tables:** mood_logs, workout_logs, measurements, milestones, daily_journal, ai_memory, personal_food_db, fasting_sessions
- **11 new commands:** /mood /workout /measure /insights /deficit /meal /fasting /body /journal /export /milestones
- **3 new files:** scheduler.py (10 proactive scheduled jobs), milestones.py (auto-celebrate every 1 kg lost), memory.py (AI learns patterns over time)

Implementation order: db.py → memory.py → ai.py → milestones.py → scheduler.py → bot.py → charts.py → main.py
