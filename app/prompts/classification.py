"""
Prompt engineering for Telegram post classification.

Techniques used (per spec):
  - Role Prompting
  - Few-Shot (3 annotated examples)
  - Delimiters (### to separate instructions from content)
  - Chain-of-Thought via <thought> block
"""

CATEGORIES = [
    "Технологии",   # IT, AI, гаджеты
    "Разработка",   # программирование, dev, open source
    "Бизнес",       # карьера, управление, предпринимательство
    "Вакансии",     # поиск работы, найм, HR
    "События",      # конференции, вебинары, мероприятия
    "Политика",     # законы, регулирование, государство
    "Развлечения",  # кино, музыка, игры, спорт
    "Умный дом",    # IoT, Home Assistant, автоматизация жилья
    "Наука",        # исследования, discovery, образование
    "Рынки",        # финансовые рынки, акции, крипто, экономика
    "Покупки",      # скидки, промокоды, товары, маркетплейсы
    "Личное",       # блоги, мнения, лайфстайл
    "Реклама",      # спонсорские интеграции, платные посты
    "Прочее",       # всё, что не подходит под остальные
]

_FEW_SHOT_EXAMPLES = """
### EXAMPLE 1
Post: "BTC пробил $70k — исторический максимум. Объём торгов за сутки составил $45 млрд."
<thought>Речь идёт о цене Bitcoin и торговых объёмах. Это финансовый контент.</thought>
Category: Рынки

### EXAMPLE 2
Post: "🔥 СКИДКА 50% на AirPods Pro только сегодня! Промокод: SAVE50. Ссылка: t.me/shop"
<thought>Пост содержит промокод и призыв к покупке — типичная реклама/Покупки.</thought>
Category: Покупки

### EXAMPLE 3
Post: "OpenAI выпустила GPT-5 с поддержкой видео в реальном времени. Модель доступна в API."
<thought>Речь о новой AI-модели и её возможностях. Тема — технологии.</thought>
Category: Технологии
"""


def build_classification_prompt(post_text: str) -> str:
    """Build a few-shot classification prompt for a single Telegram post."""
    available = ", ".join(CATEGORIES)
    return f"""\
You are a Professional Business Assistant with data analytics skills. \
Your task is to classify Telegram channel posts into exactly one category.
Use ONLY the category names listed above — do not invent new ones.

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
