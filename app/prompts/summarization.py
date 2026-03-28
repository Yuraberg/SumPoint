"""
Prompt engineering for post summarization (Digest generation).

Techniques used (per spec):
  - Role Prompting
  - Delimiters (### / \"\"\")
  - Chain-of-Thought via <thought> block
"""


def build_summarization_prompt(post_text: str, channel_title: str) -> str:
    """Return a prompt that produces a concise summary preserving key facts."""
    return f"""\
You are a Professional Business Assistant with data analytics skills.
Your goal is to produce a concise summary of the Telegram post below,
preserving all key facts, numbers, dates, and links.
The summary must be 1-3 sentences, written in the same language as the post.

### SOURCE CHANNEL
{channel_title}

### POST CONTENT
\"\"\"
{post_text}
\"\"\"

First, use a <thought> block to identify the key facts.
Then write the final summary after </thought> with no extra commentary.

<thought>
"""


def build_digest_prompt(summaries: list[dict]) -> str:
    """
    Build a combined digest prompt from a list of
    {'channel': str, 'summary': str, 'category': str} dicts.
    Returns a structured markdown digest.
    """
    items = "\n".join(
        f"- [{item['category']}] {item['channel']}: {item['summary']}"
        for item in summaries
    )
    return f"""\
You are a Professional Business Assistant with data analytics skills.
Below is a list of summarised Telegram posts from today.
Produce a well-structured daily digest in Markdown format,
grouped by category. Keep each bullet concise.
Write in the same language as the majority of posts.

### POSTS
{items}

### DIGEST
"""
