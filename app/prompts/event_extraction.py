"""
Prompt engineering for event / calendar entity extraction.

Techniques used:
  - Role Prompting
  - Delimiters
  - Chain-of-Thought via <thought> block
  - Structured JSON output
"""


def build_event_extraction_prompt(post_text: str) -> str:
    """
    Extract calendar events from a Telegram post.
    Returns a prompt whose output is a JSON array of events or [].
    """
    return f"""\
You are a Professional Business Assistant with data analytics skills.
Extract all calendar events mentioned in the Telegram post below.

For each event return a JSON object with these exact keys:
  "date"      — ISO 8601 date (YYYY-MM-DD) or null
  "time"      — HH:MM (24h) or null
  "name"      — short event name (string)
  "type"      — event type in Russian, one of: "конференция", "митап", "вебинар", "воркшоп", "выставка", "концерт", "спектакль", "дегустация", "форум", "фестиваль", "курс", "другое"
  "location"  — city and/or address as a string, or null
  "speakers"  — list of speaker/presenter names (strings), or []
  "partners"  — list of partner/sponsor company names (strings), or []
  "topics"    — list of 2-5 short topic keywords in Russian (e.g. ["вино", "сыр", "дегустация"]), or []
  "link"      — URL if present, else null

If there are no events, return an empty JSON array: []
Output ONLY valid JSON — no markdown, no extra text.

### POST
\"\"\"
{post_text}
\"\"\"

<thought>
Does the post mention any event names, dates, times, or links to events?
What is the event type, location, who are the speakers, partners, and what topics does it cover?
</thought>

JSON:
"""
