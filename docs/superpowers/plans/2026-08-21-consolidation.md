# El Fager — Consolidation Plan

**Date:** 2026-08-21
**Status:** Phase 1 delivered (see below); Phases 2-6 proposed
**Theme:** Stop adding tools. Make the 378 that exist trustworthy.

---

## The meta-problem

Every prior plan in `docs/superpowers/plans/` is a *capability* plan. The last one
states its goal as "adding ~36 tools to reach ~344 total." That worked — El Fager
now has 378 tools across 69 modules. But nothing in the roadmap ever paid down what
that growth cost:

| Signal | Measured today |
|---|---|
| `core/brain.py` | 6,793 lines (400 prompt + ~4,200 tool JSON + 377-branch dispatch) |
| Tool modules | 69 |
| Test files touching `tools/` | 6 |
| Test suite on `master` | **478 passed, 22 failed** |
| CI | none |
| Atomic writes across 46 JSON persistence sites | **0** |
| `except Exception:` blocks | 265 (119 followed by `pass`) |
| Modules using `logging` | 2 (vs. 103 `print()` calls) |
| Routing keywords / Arabic routing keywords | 592 / ~62 (10%) |

The next feature is not what's limiting El Fager. Being able to trust it is.

Everything below was verified against the tree at `568e83c`.

---

## P0 — Reliability & data integrity

### 0.1 State writes are not crash-safe

**Evidence:** `grep -c 'os.replace'` across `core/` and `tools/` returns **0**. All 46
persistence sites use bare `write_text` / `json.dump`. There are 43 distinct state
files under `data/` (trades, skills, missions, health logs, telemetry, portfolio…),
each with its own hand-rolled load/save, no locking, and a `_load()` that ends in
`except Exception: return {}`.

Three threads write concurrently: the Qt UI thread, the `ProactiveEngine` (60s
cycle), and the `APScheduler` thread. `core/dashboard.py` reads the same files.
Only `tools/browser_tool.py` holds a lock, and it's unrelated.

**Failure mode:** power loss or a crash mid-write truncates the file. On next load
the broad `except` silently returns `{}` — so a corrupt `trades.json` doesn't error,
it reports *zero trades*. Silent, total, unrecoverable.

**Fix:** one `core/state.py` — `load_json(path, default)` / `save_json(path, data)`
with tmp-file + `os.replace`, a module-level `RLock`, and rename-to-`.corrupt`
+ log instead of silent-default on parse failure. Migrate all 46 call sites.

- **verify:** kill -9 a loop writing `trades.json` 1000× → file always parses
- **verify:** no `write_text`/`json.dump` on a `data/` path outside `core/state.py`

### 0.2 Production runs blind

**Evidence:** `watchdog.py:87` sets `stdout=subprocess.DEVNULL`. The app ships
launched by `pythonw` (`run.bat`, `setup_watchdog.ps1`), which has no console.
All 103 `print()` calls — every `[El Fager]` status line and every caught-exception
message — go nowhere. Only unhandled tracebacks reach stderr, and 119
`except: pass` blocks ensure most failures never get that far.

**Consequence:** when El Fager misbehaves on Mo's laptop there is no way to find out
why. This is the single cheapest fix in this document.

**Fix:** `core/logging_setup.py` with a `RotatingFileHandler` on
`data/logs/elfager.log`. Route `print()` through it via a small shim so the 103 call
sites don't all need editing. Then sweep the 119 `except: pass` blocks and give each
a `log.debug`/`log.warning` — no behaviour change, just a breadcrumb.

- **verify:** run under `pythonw`, trigger a tool failure, find it in the log
- **verify:** `grep -c 'except Exception:$' -A1 | grep -c 'pass'` trends to 0

### 0.3 The app only works from one directory

**Evidence:** 85 relative `data/...` paths in `core/` and `tools/`. `watchdog.py`
already does it right (`_ROOT = Path(__file__).resolve().parent`) — the pattern
exists, it just isn't applied anywhere else.

**Failure mode:** launched from any cwd but the repo root, El Fager writes a fresh
empty `data/` next to wherever it started and Mo's history appears to vanish.
Scheduled-task and autostart launches are exactly where cwd is not guaranteed.

**Fix:** `core/paths.py` exporting `ROOT` and `DATA`; replace the 85 literals.

- **verify:** `cd / && python /path/to/main.py` reads the same state as `run.bat`

---

## P1 — Security

The dashboard shipped two commits ago and widened the attack surface considerably.

### 1.1 `/api/status` is unauthenticated on `0.0.0.0:8765`

**Evidence:** `core/dashboard.py` `do_GET` has no token check. Default
`dashboard_host` is `0.0.0.0`, `dashboard_enabled` defaults to **true**.

The snapshot's docstring claims "no secrets," but it serves recent trades with
symbol/side/qty/price, daily and weekly API spend, mission goal text, autonomous
task descriptions, and skill names. On university or café wifi that is a live feed
of Mo's finances and activity to anyone who port-scans the subnet.

**Fix:** require the bearer token on `/api/status` too; default `dashboard_host` to
`127.0.0.1` and make LAN exposure opt-in with an explicit setting.

### 1.2 The command channel is RCE-grade, guarded by a comparison that leaks

**Evidence:** `do_POST` compares with `supplied != f"Bearer {expected}"` — a
non-constant-time compare. There is no rate limit, no lockout, and no TLS, so the
token also crosses shared wifi in plaintext on every poll.

What it guards: `queue_command` → `AutonomousTaskManager.add` → `ProactiveEngine`
→ `brain.chat(description)` → all 378 tools, including `run_command` (PowerShell),
`type_text`/`mouse_click`, and the trading tools. Whoever holds that token owns
the laptop.

**Fix:** `secrets.compare_digest`; per-IP rate limit with backoff; append every
queued command to an audit log; and gate remote-queued tasks to a reduced tool set
(no shell, no input synthesis, no live trading) rather than full `brain.chat`.

### 1.3 `run_command`'s safety switch is model-controlled

**Evidence:** `core/brain.py:507` exposes `safe_mode` as a boolean **in the tool
schema**. The model can set it to `false` and lift its own guardrail.

The blocklist it toggles is substring-based and incomplete — `tools/system_tool.py:32`
blocks `"rm "` but not PowerShell's actual `Remove-Item`, and `"shutdown"` but not
`Stop-Computer`.

**Fix:** drop `safe_mode` from the schema; make it caller-side only. Move to an
allowlist of read-only cmdlets for autonomous/remote paths, requiring explicit
voice confirmation for anything else.

### 1.4 The vault is cosmetic, and there are two credential systems

**Evidence:** `core/vault.py` writes `data/vault.key` in plaintext next to
`data/vault.enc`, with no file-permission hardening. Anyone who can read one can
read the other. Meanwhile only `core/agents/browser_agent.py` uses the Vault at all,
while 38 secrets live in `.env`.

**Fix:** pick one. Either derive the key from an OS keyring / DPAPI, or retire the
Vault and standardise on `.env`. Two half-used credential paths is worse than
either alone.

---

## P2 — Cost

### 2.1 Prompt caching is priced but never enabled

**Evidence:** `core/telemetry.py` already computes `_CACHE_READ_MULT = 0.1` and
`_CACHE_WRITE_MULT = 1.25` and logs `cache_read_input_tokens`. But
`grep -rn 'cache_control'` across the repo returns **nothing**. The measurement
was built; the saving was never taken.

Measured prefix re-sent uncached on every single turn:

| Component | Size |
|---|---|
| `SYSTEM_PROMPT` | 41,546 chars ≈ **10,400 tokens** |
| Slimmed tool schemas (all 378) | 97,257 chars ≈ 24,300 tokens |
| Slimmed tool schemas (core-only turn) | ≈ 2,500 tokens |

So a typical turn spends ~13,000 tokens of fixed boilerplate before Mo says
anything — and every mission step and autonomous task pays it again.

**Fix:** `cache_control: {"type": "ephemeral"}` on the system prompt and the tool
block in `_create_message`. Telemetry will show the delta immediately.

- **verify:** `usage_report(1)` cost-per-turn drops ~80–90% on repeat turns

### 2.2 `conversation_history` grows without bound

**Evidence:** `Brain.chat` appends every turn and never trims. `reset_conversation()`
exists but is manual. For an always-on assistant this ends in a hard context-limit
failure after enough uptime.

*(The tool-loop compaction — keeping only final text in history — is a deliberate
and correct choice. Leave it.)*

**Fix:** cap history at N turns; summarise or drop the oldest.

### 2.3 Model pinning

`self._model` defaults to `claude-sonnet-4-6`. Worth re-benchmarking against the
current model line for the routing/dispatch workload before the next cost pass.

---

## P3 — The Arabic gap

This is the most user-visible defect in the product.

**Evidence:** `_GROUP_TRIGGERS` holds 592 keywords; ~62 are Arabic (10%).
Ten groups have **zero** Arabic triggers:

`clipboard` · `productivity` · `system` · `cloud` · `bizmath` · `macro` · `code` ·
`git` · `dev_utils` · `notifications` · `usage`

`productivity` is email, calendar, tasks, and pomodoro — the daily-driver group.

**Failure mode:** `_select_tools` matches substrings against the raw message. Ask
for your email in Egyptian Arabic and no group fires, so only `_CORE_NAMES` (~35
tools) is injected. Gmail is never offered to the model, and El Fager confidently
answers that it can't — for a capability it has. The `SYSTEM_PROMPT` opens by
insisting Arabic input gets Arabic output; the routing layer quietly makes Arabic a
second-class input.

**Two more routing defects in the same function:**
- The tool set is computed from the *first* message and frozen for all 15 loop
  iterations — a tool needed mid-task can never be reached.
- No fallback when nothing matches, and substring matching over-fires ("generate a
  report" pulls in the whole image group).

**Fix:**
1. Arabic + Arabizi triggers for all 35 groups, prioritising `productivity`,
   `clipboard`, `system`, `cloud`.
2. Recompute tool selection each iteration, seeded by tools already used.
3. Widen to a larger default set when confidence is low, rather than falling back
   to core-only.

- **verify:** a fixture of ~50 real Arabic/Arabizi requests, one per group,
  asserting the right group is selected

---

## P4 — Engineering hygiene

### 4.1 There is no CI, and the local gate is red

`hooks/pre-push` runs `pytest tests/` and blocks on failure — but the suite fails on
`master` today, so the hook is either uninstalled or being skipped. Measured
baseline (`--ignore=tests/ui`): **478 passed, 22 failed in ~10s**.

Breakdown of the 22:
- **2 genuine stale tests.** `tests/test_backtester.py::test_simulate_tp_hit` and
  `::test_simulate_sl_hit` assert TP 12% / SL 5%. `core/risk_manager.py:13-14`
  defines 8% / 15%. The backtester is right; the tests were never updated when the
  risk defaults moved. This is the component that validates strategies *before real
  money is deployed* — its tests should not be red.
- **20 missing optional deps** (`pymupdf`, `python-docx`, `alpaca-py`, `playwright`).
  These should skip cleanly, not fail.

Good news for CI: only 3 test files import PyQt6 (all under `tests/ui/`). The other
~527 tests are pure logic and run headless on Linux in ~10 seconds.

**Fix:** GitHub Actions running `pytest --ignore=tests/ui` on push/PR;
`pytest.importorskip` for optional-dep tests; correct the two backtester tests.

### 4.2 The build has no declared contract

**Found while executing Phase 1 — not in the original audit:** four modules are
imported by shipped code but absent from `requirements.txt` entirely —
`playwright`, `yfinance`, `pyautogui`, `pdfplumber`. A fresh
`pip install -r requirements.txt` therefore produced an El Fager whose browser
agent, market analyst, screen/mouse control and PDF reading all failed at
runtime. `tools/bond_tool.py:6` and `tools/mouse_tool.py:8` import theirs at
module scope, so those modules would not even import. Now declared.


- `pytest` is **not in `requirements.txt`** despite 530 tests.
- No `pyproject.toml`, no `pytest.ini`, no declared Python floor.
- `tools/macro_tool.py:837` uses a PEP 701 nested-quote f-string that requires
  **Python 3.12+** — it is a `SyntaxError` on 3.11 and nothing anywhere says so.
- No `.env.example` for 38 environment variables; the README documents ~5.

**Fix:** `pyproject.toml` with `requires-python = ">=3.12"` and a `dev` extra;
generate `.env.example` from the 38 keys actually read.

### 4.3 The tool layer is untested

69 tool modules, 6 test files touching `tools/`. The 530 existing tests concentrate
on agents, trading, missions, and skills — the tool surface Mo actually uses daily
is the least covered part of the codebase.

**Fix:** a shared contract test asserting the invariants the plans already declare —
every tool returns `str`, never raises, errors formatted `[tool_name failed: reason]`.
One parametrised test covers all 69 modules cheaply.

### 4.4 Dead weight and footguns

- `core/brain.py.bak2` — 168 KB backup file, committed.
- `_full_audit.py` — stale; imports `_dispatch_tool` from `core.brain` as a module
  function, but it has been a `Brain` method for some time. It cannot run.
- `.gitignore` line `*.txt` silently swallows any new `.txt` file.
- `core/agents/file_agent.py:11-13` hardcodes `C:/Users/Mohab1/...` while
  `profile.json` already carries those paths for exactly this purpose.
  `setup_watchdog.ps1` hardcodes both the interpreter and the project path.

---

## P5 — Architecture

`core/brain.py` is 6,793 lines: a 400-line prompt, ~4,200 lines of inline tool JSON,
and a 1,400-line / 377-branch `if/elif` dispatch chain. Adding one tool means
touching five places (`TOOLS`, `_TOOL_GROUP_NAMES`, `_GROUP_TRIGGERS`,
`_dispatch_tool`, `SYSTEM_PROMPT`) — which is precisely why drift like the missing
Arabic triggers and the stale audit script accumulates.

**Fix (do this last, after CI is green and can protect the refactor):**
a `@tool` decorator registry. Each tool module declares its own schema and handler;
`brain.py` imports and assembles. `TOOLS`, the dispatch chain, and the group maps
all become derived data. Target: `brain.py` under 500 lines, one file touched per
new tool.

The 400-line `SYSTEM_PROMPT` deserves the same treatment — most of it is per-group
usage instructions that should live with their group and be injected only when that
group is selected. That also shrinks the cached prefix from P2.1.

---

## Suggested order

Each phase leaves the repo better even if the next never happens.

| Phase | Work | Why first |
|---|---|---|
| 1 ✅ | 4.1 CI + fix 2 stale tests, 4.2 build contract | **Done** — suite green (480 passed, 20 skipped), GitHub Actions gate on 3.12. 4.4 dead weight still open. |
| 2 | 0.2 logging, 0.1 atomic state, 0.3 paths | Stops silent data loss and makes every later bug diagnosable |
| 3 | 1.1–1.4 security | Bounded, high-severity, mostly small diffs |
| 4 | 2.1 prompt caching, 2.2 history cap | Biggest cost win for the least code |
| 5 | 3 Arabic routing + 4.3 tool contract tests | Most user-visible improvement |
| 6 | 5 brain.py registry refactor | Large; needs phases 1–2 in place to be safe |

**Explicitly not in this plan:** new tools. El Fager is at 378. The gap between what
it *can* do and what Mo can *rely on it doing* is the thing worth closing.
