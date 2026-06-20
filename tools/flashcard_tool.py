"""
Anki flashcard export — Phase 5D.
Claude generates Q&A pairs; this tool saves them to a CSV file for Anki import.

Anki import steps (one-time setup):
  File → Import → select the CSV → set Type=Basic, Fields separated by Comma.
  Subsequent imports append without duplicating if "Allow HTML" is off.
"""

import csv
import os
from pathlib import Path

DEFAULT_OUTPUT = "data/flashcards.csv"


def save_flashcards(
    cards: list,
    output_path: str = DEFAULT_OUTPUT,
    deck_name: str = "El Fager",
) -> str:
    """
    Append flashcard Q&A pairs to a CSV file for Anki import.

    cards       — list of {"front": "question", "back": "answer"} dicts
    output_path — where to write the CSV (appends if file already exists)
    deck_name   — Anki deck name written as a header comment
    """
    if not cards:
        return "No flashcards provided — pass a list of {front, back} dicts."

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.exists() and path.stat().st_size > 0

    valid = [
        c for c in cards
        if isinstance(c, dict) and c.get("front", "").strip() and c.get("back", "").strip()
    ]
    if not valid:
        return "All cards were empty or malformed — nothing saved."

    with open(path, "a", newline="", encoding="utf-8") as f:
        if not file_exists:
            f.write(f"#deck:{deck_name}\n")
            f.write("#separator:Comma\n")
            f.write("#html:false\n")
            f.write("#notetype:Basic\n")
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        for c in valid:
            writer.writerow([c["front"].strip(), c["back"].strip()])

    abs_path = str(path.resolve())
    return (
        f"Saved {len(valid)} flashcard(s) to:\n{abs_path}\n\n"
        f"To import into Anki:\n"
        f"  1. Open Anki > File > Import\n"
        f"  2. Select the CSV file above\n"
        f"  3. Set Note Type = Basic, Fields separated by Comma\n"
        f"  4. Click Import"
    )
