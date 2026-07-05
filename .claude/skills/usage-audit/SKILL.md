---
name: usage-audit
description: Audit El Fager's real usage vs. built features — synthetic-data contamination, Whisper garbage rate, tool leaderboard, skill run counts, API cost. Run before deciding what to build next.
---

# Usage audit

Answers "am I building the right thing?" from real data instead of plans.

## Run

```powershell
python -X utf8 scripts/usage_audit.py
```

## How to read the report

- **Turns per day** — the ground truth of whether El Fager is actually being
  used. Days with 0–5 turns mean features are outrunning usage.
- **Synthetic contamination** — exact phrases repeated ≥10× are test loops,
  not habits. If any appear: quarantine them into `data/conversations_test/`
  and always set `EL_FAGER_TEST_MODE=1` when running test sessions, otherwise
  HabitMiner proposes fake skills from them.
- **Transcription garbage rate** — user turns containing Hangul/Hebrew/
  Cyrillic/CJK or Icelandic ð/þ are Whisper hallucinations. If this is above
  ~5%, the voice front door is broken; fix STT before building features
  (see `ALLOWED_LANGUAGES` / `NO_SPEECH_MAX` in `core/voice_in.py`).
- **Tool usage vs. skills** — tools with high counts deserve investment;
  skills with `runs=0` weeks after creation should be deleted or surfaced
  better, not added to.
- **Telemetry cost** — sanity-check against `data/budget.json` limits.

## After the audit

State 1–3 concrete conclusions ("X is unused — remove or promote it",
"garbage rate up — check mic/VAD"), not a data dump. If contamination is
found, offer to quarantine it (move lines to `data/conversations_test/`,
mark mined proposals dismissed — never delete).
