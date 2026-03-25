CALORIE_GOAL = 1500
PROTEIN_GOAL = 150
CARB_GOAL = 150
FAT_GOAL = 50
WATER_GOAL = 14
STARTING_WEIGHT = 90.0
TARGET_WEIGHT = 70.0

EATING_WINDOW_START = "13:30"
EATING_WINDOW_END = "21:30"

FASTING_SAFE_ITEMS = {
    "black coffee": 5, "kali coffee": 5, "black chai": 5,
    "green tea": 2, "hari chai": 2,
    "chaach": 50, "buttermilk": 50, "chhachh": 50, "chach": 50,
    "cucumber": 16, "kheera": 16, "khira": 16,
    "plain water": 0, "water": 0, "pani": 0,
}

SLEEP_TRIGGERS = [
    "so raha hoon", "sone ja raha", "goodnight", "good night", "gn",
    "so gaya", "neend aa rahi", "so rha hoon", "soja raha", "neend aa gayi",
    "sleeping", "sleep time", "so rha hun", "so raha hun",
]

WAKE_TRIGGERS = [
    "uth gaya", "uth gya", "good morning", "gm", "jag gaya",
    "jag gya", "woke up", "jagaa", "subah ho gayi", "neend khuli",
    "good mrng", "morning", "utha hun", "uth gya hu",
]

SUPPLEMENTS = [
    {
        "name": "Iron (Ferrous Ascorbate)",
        "dose": "100mg",
        "timing": "with first meal",
        "note": "With lemon water / Vitamin C. NOT with dairy or calcium.",
        "timeline": {"energy": "2–4 weeks", "hair fall reduction": "8–12 weeks"},
    },
    {
        "name": "Vitamin B12 (Methylcobalamin)",
        "dose": "1500mcg sublingual",
        "timing": "morning with meal",
        "note": "Hold under tongue 30 sec before swallowing.",
        "timeline": {"energy": "2–4 weeks", "nerve function": "4–8 weeks"},
    },
    {
        "name": "Vitamin D3 + K2",
        "dose": "2000 IU D3 daily",
        "timing": "with fatty meal",
        "note": "Fat-soluble — take with your heaviest meal.",
        "timeline": {"energy": "2–4 weeks", "immunity": "4–6 weeks", "mood": "4–8 weeks"},
    },
    {
        "name": "Zinc (Zinc Gluconate)",
        "dose": "15mg",
        "timing": "with meal",
        "note": "NOT on empty stomach — causes nausea.",
        "timeline": {"skin glow": "4–6 weeks", "hair": "8–12 weeks", "beard patches": "3–6 months"},
    },
    {
        "name": "Omega-3 Fish Oil",
        "dose": "1000mg EPA+DHA",
        "timing": "with heaviest meal",
        "note": "Max absorption with fat-containing meal.",
        "timeline": {"skin": "4–6 weeks", "inflammation": "4–8 weeks"},
    },
    {
        "name": "Magnesium Glycinate",
        "dose": "400mg",
        "timing": "30 min before sleep",
        "note": "Best form for sleep quality and anxiety relief.",
        "timeline": {"sleep quality": "1–2 weeks", "anxiety/stress": "2–4 weeks"},
    },
    {
        "name": "Biotin",
        "dose": "5000mcg",
        "timing": "with any meal",
        "note": "Hair and nail growth — results take months, not weeks.",
        "timeline": {"nail strength": "3–5 months", "hair thickness": "3–5 months"},
    },
    {
        "name": "Ashwagandha (KSM-66)",
        "dose": "600mg",
        "timing": "morning or night with meal",
        "note": "Adaptogen — reduces cortisol, supports testosterone.",
        "timeline": {"stress reduction": "2–4 weeks", "testosterone": "8–12 weeks"},
    },
]
