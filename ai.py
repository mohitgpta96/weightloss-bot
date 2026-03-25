import os
import base64
import json
import re
from groq import AsyncGroq
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import CALORIE_GOAL

# B8: validate API key at import time
if not os.getenv("GROQ_API_KEY"):
    raise EnvironmentError("GROQ_API_KEY not set in .env")

client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY"))

TEXT_MODEL = "llama-3.3-70b-versatile"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

_FOOD_SYSTEM = """You are a precise Indian food nutrition analyzer. Return ONLY valid JSON.
Estimate for standard Indian home portions.

Key references:
- 1 roti/chapati: 70 kcal, 2.5g protein, 15g carbs, 1g fat
- 1 cup cooked dal: 180 kcal, 12g protein, 30g carbs, 2g fat
- 1 cup cooked rice: 200 kcal, 4g protein, 44g carbs, 0.4g fat
- 1 paratha with butter: 300 kcal, 6g protein, 35g carbs, 15g fat
- 1 serving chicken curry: 250 kcal, 28g protein, 8g carbs, 12g fat
- 1 egg (boiled): 77 kcal, 6g protein, 0.6g carbs, 5g fat
- 1 glass milk: 150 kcal, 8g protein, 12g carbs, 8g fat
- 1 samosa: 250 kcal, 5g protein, 32g carbs, 12g fat"""

_RETRY_KWARGS = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


@retry(**_RETRY_KWARGS)
async def analyze_food_text(text: str) -> dict:
    """Parse a food description into calorie + macro data."""
    prompt = f"""Analyze this food and return ONLY JSON:
"{text}"

{{
  "food_name": "clean name",
  "calories": 350,
  "protein": 25.5,
  "carbs": 40.0,
  "fat": 8.0,
  "is_restaurant": false,
  "confidence": "medium",
  "serving_notes": "what portion this covers"
}}

Rules:
- is_restaurant: true if from dhaba/restaurant/delivery/takeaway
- confidence: "high" (common item), "medium" (mixed/estimated), "low" (unusual)
- Estimate for reasonable Indian portion size"""

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": _FOOD_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return json.loads(response.choices[0].message.content)


@retry(**_RETRY_KWARGS)
async def analyze_food_photo(image_bytes: bytes) -> dict:
    """Analyze a food photo using a vision model."""
    b64 = base64.standard_b64encode(image_bytes).decode()
    prompt = """Look at this food photo and return ONLY this JSON (no other text):
{
  "food_name": "dish name",
  "components": ["item1", "item2"],
  "calories": 400,
  "protein": 20.0,
  "carbs": 50.0,
  "fat": 12.0,
  "is_restaurant": false,
  "confidence": "medium",
  "portion_notes": "what you see on the plate"
}

List every component you can identify. Estimate for the visible portion."""

    response = await client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        temperature=0.1,
    )
    return _extract_json(response.choices[0].message.content)


@retry(**_RETRY_KWARGS)
async def check_food_safety(food_query: str, remaining_calories: int, remaining_protein: int) -> dict:
    """Decide if a food fits the daily budget; always include 3 alternatives."""
    prompt = f"""Indian user on {CALORIE_GOAL} kcal/day asks: "{food_query}"
Remaining budget: {remaining_calories} kcal, needs {remaining_protein}g more protein.

Return ONLY JSON:
{{
  "is_safe": true,
  "food": "detected food name",
  "estimated_calories": 350,
  "estimated_protein": 15,
  "reason": "one sentence",
  "recommendation": "what/how much to order",
  "alternatives": [
    {{"name": "option 1", "calories": 200, "protein": 25, "why": "high protein, fits budget"}},
    {{"name": "option 2", "calories": 150, "protein": 20, "why": "lighter choice"}},
    {{"name": "option 3", "calories": 180, "protein": 18, "why": "good balance"}}
  ]
}}

is_safe = true only if estimated_calories <= {int(remaining_calories * 0.95)}
Always give 3 alternatives from same cuisine/restaurant type even if is_safe = true."""

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a calorie-aware Indian food advisor. Return only valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return json.loads(response.choices[0].message.content)


@retry(**_RETRY_KWARGS)
async def detect_intent(text: str) -> dict:
    """Classify intent of a user message."""
    prompt = f"""Classify this message from an Indian user. Return ONLY JSON:
"{text}"

{{
  "intent": "food_log|yesterday_log|water_log|weight_log|sleep|wake|food_question|supplement_log|ingredient_query|craving|social_eating|notification_control|chat",
  "details": {{}}
}}

Intent rules:
- food_log: ate/drank something TODAY ("kha liya", "khaya", food names, meal descriptions, "chai", "coffee")
- yesterday_log: wants to log food eaten YESTERDAY ("kal ka khana", "log yesterday", "yesterday I ate", "kal khaya tha", "forgot to log yesterday", "kal nahi daala")
- water_log: mentions pani/water + quantity ("5 glass pani", "4 glasses piya")
- weight_log: mentions kg + number ("90.5 kg", "weight 89", just "89.5")
- sleep: going to sleep ("so raha hoon", "goodnight", "gn", "neend aa rahi")
- wake: woke up ("uth gaya", "good morning", "gm")
- food_question: asking if can eat something ("kya main X kha sakta hoon", "can I eat X", "X safe hai kya")
- supplement_log: took a supplement ("b12 le liya", "iron kha liya", "supplements le liya")
- ingredient_query: listing ingredients they have ("X, Y, Z hai", "ghar pe X hai", "fridge mein X", "I have X and Y", "kya banaun")
- craving: craving food ("X khane ka mann hai", "X chahiye", "I'm craving X", "bhookh lag rahi")
- social_eating: eating out or social event ("bahar khana hai", "party hai", "restaurant ja raha", "kisi ke ghar khana")
- notification_control: managing message frequency ("quiet", "mute", "less messages", "more messages", "kam messages")
- chat: everything else — questions, venting, "I messed up", motivation, small talk, general conversation

For water_log: details = {{"glasses": 5}}
For weight_log: details = {{"weight": 90.5}}
For food_question: details = {{"query": "the food they asked about"}}
For supplement_log: details = {{"supplement": "supplement name"}}
For food_log: details = {{"food": "what they ate"}}
For ingredient_query: details = {{"ingredients": ["aloo", "pyaaz", "tamatar"]}}
For craving: details = {{"craving": "what they're craving"}}
For social_eating: details = {{"context": "brief description"}}
For notification_control: details = {{"action": "quiet|less|more"}}
For sleep/wake/chat/yesterday_log: details = {{}}"""

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": "Intent classifier. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    return json.loads(response.choices[0].message.content)


@retry(**_RETRY_KWARGS)
async def suggest_recipes(ingredients: list[str], remaining_calories: int, remaining_protein: int) -> list[dict]:
    """Suggest Indian recipes based on available ingredients, ranked by protein."""
    ingredients_str = ", ".join(ingredients)
    prompt = f"""Indian user has these ingredients: {ingredients_str}
Remaining calorie budget: {remaining_calories} kcal. Needs {remaining_protein}g more protein today.

Suggest 3-5 Indian recipes they can make RIGHT NOW. Return ONLY JSON array:
[
  {{
    "name": "Besan Chilla",
    "emoji": "🫓",
    "calories": 320,
    "protein": 18.0,
    "carbs": 35.0,
    "fat": 8.0,
    "cook_time_mins": 15,
    "tag": "high protein"
  }}
]

Rules:
- Use ONLY the listed ingredients (plus basic pantry staples: oil, salt, spices, onion if not listed)
- Rank by protein content (highest first)
- Include North Indian, South Indian, and quick options
- tag can be: "high protein", "quick", "light", "filling"
- Keep calories realistic for the recipe"""

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are an expert Indian home cook and nutritionist. Return only valid JSON array.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    raw = json.loads(response.choices[0].message.content)
    # Handle both {"recipes": [...]} and direct array responses
    if isinstance(raw, list):
        return raw
    return raw.get("recipes", raw.get("items", []))


@retry(**_RETRY_KWARGS)
async def generate_insights(weekly_data: dict, memory_context: str = "") -> str:
    """Generate AI weekly pattern analysis."""
    context_block = f"\nKnown patterns about this user:\n{memory_context}" if memory_context else ""
    prompt = f"""Analyze this Indian user's weight loss week data and give 3-5 bullet insights.{context_block}

Weekly data:
{json.dumps(weekly_data, indent=2)}

Return a plain text response with bullet points (use •). Be specific, actionable, encouraging.
Focus on: what worked, what didn't, one specific thing to improve next week.
Keep it under 200 words. Speak directly to the user."""

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a personal weight loss coach for an Indian user. Be warm, specific, and data-driven.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


@retry(**_RETRY_KWARGS)
async def generate_nightly_coaching(day_data: dict, memory_context: str = "") -> str:
    """Generate personalized end-of-day coaching message."""
    context_block = f"\nKnown patterns:\n{memory_context}" if memory_context else ""
    prompt = f"""Give a brief, warm end-of-day message for this Indian user's weight loss journey.{context_block}

Today's data:
{json.dumps(day_data, indent=2)}

Rules:
- Max 3 sentences
- One specific observation from today's data
- One actionable tip for tomorrow
- Warm and encouraging tone, not preachy
- If they had a bad day: focus on recovery, not failure"""

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a supportive personal health coach. Be concise, warm, and specific.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
    )
    return response.choices[0].message.content.strip()


@retry(**_RETRY_KWARGS)
async def generate_recovery_plan(overage_calories: int, food_logged: list[str]) -> str:
    """Generate a non-judgmental recovery plan after a heavy day."""
    foods = ", ".join(food_logged) if food_logged else "various foods"
    prompt = f"""Indian user went {overage_calories} kcal over their {CALORIE_GOAL} kcal goal today (ate: {foods}).

Give a brief, non-judgmental recovery message + tomorrow's plan. Return plain text:
1. One sentence: how much this actually sets them back (usually 1-2 days)
2. Tomorrow's simple meal plan to get back on track (3 meals, stay under {CALORIE_GOAL} kcal, hit 100g+ protein)
3. One encouraging sentence

Be warm. No shame. Max 100 words."""

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a compassionate weight loss coach. Never shame users.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


@retry(**_RETRY_KWARGS)
async def handle_craving(craving: str, remaining_calories: int) -> str:
    """Respond to a craving with science + healthy swaps."""
    prompt = f"""Indian user is craving: "{craving}"
Remaining calorie budget: {remaining_calories} kcal.

Return plain text response:
1. One sentence: WHY they're craving this (blood sugar dip, habit, stress, etc.)
2. Two healthy Indian swaps that actually satisfy the same need (with calories)
3. One sentence: if they really want it, here's how to fit it in

Be understanding, not preachy. Max 80 words."""

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a supportive Indian food and nutrition coach.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


@retry(**_RETRY_KWARGS)
async def handle_social_eating(context_desc: str, remaining_calories: int) -> str:
    """Give pre-event strategy for social eating situations."""
    prompt = f"""Indian user is going to: "{context_desc}"
Remaining calorie budget today: {remaining_calories} kcal.

Give a brief social eating strategy. Return plain text:
1. What to eat beforehand (if relevant)
2. Best choices at the event (2-3 options)
3. One mindset tip

Be practical for Indian social contexts (weddings, parties, restaurant, family dinners). Max 80 words."""

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a practical Indian lifestyle and nutrition coach.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


async def general_chat(text: str, user_context: dict) -> str:
    """Respond naturally to any message — questions, venting, small talk, etc."""
    name = user_context.get("name", "")
    calories = user_context.get("calories_today", 0)
    protein = user_context.get("protein_today", 0)
    streak = user_context.get("streak", 0)
    weight = user_context.get("weight", 0)

    system = f"""You are a friendly, warm Indian weight loss coach and accountability buddy.
You're talking to {name or 'the user'} who is on a 90kg → 70kg journey.
Today: {calories} kcal eaten, {protein}g protein, {streak}-day streak, current weight {weight}kg.

Rules:
- Respond in the same language as the user (Hindi/English/Hinglish)
- Keep responses SHORT — 2-4 sentences max
- Be human, warm, and direct — no corporate speak
- If they messed up, be supportive not preachy
- If they ask a question, answer it
- If they're frustrated, acknowledge it first then help
- NEVER say "I'm an AI" or "I cannot"
- Sign off responses naturally, not with bullet points"""

    response = await client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ],
        max_tokens=200,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


async def extract_name(text: str) -> str:
    """Extract a person's name from natural language (Hindi/English mix)."""
    try:
        resp = await client.chat.completions.create(
            model=TEXT_MODEL,
            messages=[{
                "role": "user",
                "content": (
                    "Extract ONLY the person's first name from this message. "
                    "Return just the name as a single word, no punctuation, no explanation. "
                    "Examples: 'Mohit hu' → Mohit, 'call me Rahul' → Rahul, 'mera naam Priya hai' → Priya. "
                    f"Message: \"{text}\""
                ),
            }],
            max_tokens=10,
            temperature=0,
        )
        # Strip all non-alpha characters (handles "Mohit.", "Mohit!", etc.)
        raw = resp.choices[0].message.content.strip()
        name = re.sub(r"[^a-zA-Z]", "", raw.split()[0]) if raw else ""
        return name.capitalize() if len(name) >= 2 else "Friend"
    except Exception:
        return "Friend"
