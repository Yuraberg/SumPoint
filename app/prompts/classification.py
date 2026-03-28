"""
Prompt engineering for Telegram post classification.

Techniques used (per spec):
  - Role Prompting
  - Few-Shot (3 annotated examples)
  - Delimiters (### to separate instructions from content)
  - Chain-of-Thought via <thought> block
"""

CATEGORIES = [
    "Market",       # финансовые рынки, акции, крипто
    "Technology",   # IT, AI, гаджеты
    "Shopping",     # скидки, промокоды, товары
    "Events",       # конференции, вебинары, мероприятия
    "Politics",     # политика, законодательство
    "Science",      # наука, исследования
    "Entertainment",# кино, музыка, игры
    "Personal",     # личные блоги, мнения
    "Ads",          # реклама, спонсорские интеграции
    "Other",        # всё остальное
]

_FEW_SHOT_EXAMPLES = """
### EXAMPLE 1
Post: "BTC пробил $70k — исторический максимум. Объём торгов за сутки составил $45 млрд."
<thought>Речь идёт о цене Bitcoin и торговых объёмах. Это финансовый контент.</thought>
Category: Market

### EXAMPLE 2
Post: "🔥 СКИДКА 50% на AirPods Pro только сегодня! Промокод: SAVE50. Ссылка: t.me/shop"
<thought>Пост содержит промокод и призыв к покупке — типичная реклама/Shopping.</thought>
Category: Shopping

### EXAMPLE 3
Post: "OpenAI выпустила GPT-5 с поддержкой видео в реальном времени. Модель доступна в API."
<thought>Речь о новой AI-модели и её возможностях. Тема — технологии.</thought>
Category: Technology
"""


def build_classification_prompt(post_text: str) -> str:
    """Build a few-shot classification prompt for a single Telegram post."""
    available = ", ".join(CATEGORIES)
    return f"""\
You are a Professional Business Assistant with data analytics skills. \
Your task is to classify Telegram channel posts into exactly one category.

Available categories: {available}

Use a <thought> block to reason briefly before giving the final answer.
Output ONLY the category name on the last line — nothing else.

{_FEW_SHOT_EXAMPLES}

### POST TO CLASSIFY
\"\"\"
{post_text}
\"\"\"
<thought>
"""
