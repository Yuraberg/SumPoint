"""
Prompt engineering for event / calendar entity extraction.

Techniques used (per spec):
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
  "date"  — ISO 8601 date (YYYY-MM-DD) or null
  "time"  — HH:MM (24h) or null
  "name"  — short event name (string)
  "link"  — URL if present, else null

If there are no events, return an empty JSON array: []
Output ONLY valid JSON — no markdown, no extra text.

### POST
\"\"\"
{post_text}
\"\"\"

<thought>
Does the post mention any event names, dates, times, or links to events?
</thought>

JSON:
"""
