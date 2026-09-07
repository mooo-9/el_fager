"""Turning what the model wrote into what a surface should show.

The model is told to answer in plain spoken English, and mostly does — but on
a summary it reaches for markdown anyway and writes "**Personal facts:** ..."
Those asterisks then went straight into a QLabel, so the Cockpit displayed
literal `**` and the transcript read as a wall of syntax.

core/voice_out.py already strips markdown, but for the *ear*: it also expands
"e.g." to "for example" and turns dashes into pauses, which is wrong for text
on screen. This is the display-side counterpart.

`sections()` is the useful half. Rather than deleting the structure the model
reached for, it reads it: "**Academic:** you've finished..." becomes a labelled
section a surface can set as a kicker over body text, which is the shape the
design language already uses everywhere else.
"""
import re

# **bold**, __bold__, *italic*, _italic_ — captured rather than deleted so the
# words inside survive.
_BOLD = re.compile(r"\*{2,3}([^*]+)\*{2,3}|_{2}([^_]+)_{2}")
_ITALIC = re.compile(r"(?<!\w)[*_]([^*_\n]+)[*_](?!\w)")
_CODE = re.compile(r"`{1,3}([^`]*)`{1,3}")
_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_BULLET = re.compile(r"^[ \t]*[-*+]\s+", re.MULTILINE)
_NUMBERED = re.compile(r"^[ \t]*\d+\.\s+", re.MULTILINE)
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_RULE = re.compile(r"^[-_*]{3,}\s*$", re.MULTILINE)

# "**Label:** body" or "Label: body" at the start of a block. The label is
# short by definition — a heading, not a sentence that happens to have a colon.
_LABELLED = re.compile(r"^\s*(?:\*{2,3})?\s*([A-Z][^:*\n]{1,40}?)\s*(?:\*{2,3})?\s*:\s*(.*)$",
                       re.DOTALL)


def plain(text: str) -> str:
    """Markdown out, words intact. For display, not for speech."""
    if not text:
        return ""
    text = _HEADING.sub("", text)
    text = _LINK.sub(r"\1", text)
    # Two alternatives, so the replacement has to pick whichever matched —
    # r"\1" silently yields an empty string for the __bold__ branch.
    text = _BOLD.sub(lambda m: m.group(1) or m.group(2) or "", text)
    text = _CODE.sub(r"\1", text)
    text = _ITALIC.sub(r"\1", text)
    text = _RULE.sub("", text)
    text = _BULLET.sub("• ", text)
    text = _NUMBERED.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sections(text: str) -> "list[tuple[str, str]]":
    """Split an answer into (label, body) pairs.

    A block written as "**Academic:** you've finished ..." comes back as
    ("Academic", "you've finished ..."), so a surface can set the label as a
    kicker and the body as prose — the same kicker-over-value shape the rest
    of the design uses. A block with no label comes back with an empty one.

    Returns [] for empty input, never None, so callers can loop without a
    guard.
    """
    cleaned = plain(text)
    if not cleaned:
        return []

    out: list[tuple[str, str]] = []
    for block in re.split(r"\n\s*\n", cleaned):
        block = block.strip()
        if not block:
            continue
        match = _LABELLED.match(block)
        if match:
            label, body = match.group(1).strip(), match.group(2).strip()
            # A label is a heading, not the first half of a sentence: "Here's
            # what you've told me" has no colon, but "Note: I did x" would —
            # so require the body to be substantial and the label to be short.
            if body and len(label.split()) <= 5:
                out.append((label, " ".join(body.split())))
                continue
        out.append(("", " ".join(block.split())))
    return out
