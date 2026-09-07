# Command Center rebuild — brief

Written 2026-08-12 at the end of the design-integration session, so the next
session starts with the decisions and the verified APIs already in hand.

Reference: `docs/design/design_handoff_el_fager/mocks/El Fager Command Center Prototype.dc.html`
Current file: `ui/command_center.py` (33KB, working — Dawn palette, day-arc,
cache-first cards, command bar wired to the real pipeline).

## Decisions made by Mo

1. **Briefing prose: generate on every open.** Not the cached 7:30am one.
2. **Full restructure to the 12-col grid.** Not an in-place addition.

## The tension to resolve in (1)

"Generate every open" fights the design's own rule — cards paint from
`data/command_center_cache.json` before any live fetch finishes, and the
handoff is explicit that nothing may cost open latency.

**Resolve it the way the cards already do:** paint the greeting immediately,
show the briefing block in a loading state, run `brain.chat()` in a daemon
thread, and stream the prose in when it lands. The open path must never wait
on the model. Keep the last result cached so the block has something to show
in the first frame rather than an empty box.

`core/briefing.py` only provides `get_briefing_prompt()` — the prompt, not the
prose. The synthesis is a `brain.chat()` call with that prompt.

## Layout spec (from the handoff)

- 12 columns, 24px gutter, 48px margin, min width 1100px.
- Order: greeting + briefing prose → data cards (calendar, tasks, mail, news,
  health) → "it's getting to know me" row → global command bar.
- **Every card footer carries ONE voice-runnable action.**
- Health card: day-arc (already built, `ui/widgets.DayArc`) + macro bars +
  weight/sleep sparklines.
- Dawn palette (canon puts cyan in the Cockpit, not here).

## The "getting to know me" row — all sources verified present

| Piece | API | Notes |
|---|---|---|
| Learned facts as forgettable chips | `core.memory.Memory.get_all_facts(category=None)` → list; `delete_fact(fact_id)` | `delete_fact` is what makes a chip genuinely forgettable — wire the chip's × to it |
| Active skills | `core.skills.store.SkillStore().list_all()` → list[dict] | |
| One proposed automation needing a yes | `core.skills.miner.HabitMiner().pending()` → list; `set_status(proposal_id, status)` | Show one at a time; the yes must call `set_status`, not just hide the card |

Also available and already used elsewhere: `core.staging` (armed actions),
`core.progress` (step ledger), `core.ledger` (the Trust Ledger record).

## Rules that must survive the restructure

- Cache-first paint; no card blocks the open.
- Outbound actions keep stage → preview → confirm via `core.staging` — no
  second send path.
- The command bar keeps dispatching into the existing `PipelineWorker`.
- No QWebEngine on this surface (it is fully native today; keep it that way).
- `ui/command_center.py` imports `MessageBubble`, `_load_settings`,
  `_save_settings` from `ui/overlay.py` — those must keep working.

## Verification pattern used all session

Render the surface offscreen and look at it:

```python
os.environ["QT_QPA_PLATFORM"] = "offscreen"
# build the window with MagicMock() for voice_in/brain/voice_out/memory,
# call the refresh methods, then widget.grab().save(path)
```

Two recurring traps this catches: wrapped `QLabel`s clip unless the layout is
told to ask for their height (`sizePolicy.setHeightForWidth(True)`), and
`deleteLater()` leaves old rows painted over new ones — `setParent(None)`
first. Note that the offscreen platform does not reproduce Windows font
fallback, so missing-glyph tofu in a capture is usually an artifact; check
with `QFontMetricsF(...).inFont(ch)` before "fixing" it.
