---
name: verify-fager
description: Verify El Fager end-to-end before committing/pushing — full pytest, byte-compile check, watchdog task, and data-dir health. Run after any nontrivial change.
---

# Verify El Fager

Run these in order; stop and fix at the first failure.

## 1. Byte-compile everything (catches syntax/import-time errors fast)

```powershell
python -m compileall core tools ui main.py -q
```

## 2. Full test suite (the pre-push hook gates on this too)

```powershell
python -m pytest -q
```

All tests must pass — no skipping, no `-x` shortcuts on the final run.

## 3. Import smoke test (heavy modules load without a display)

```powershell
python -c "from core.brain import Brain; from core.voice_in import VoiceInput; print('imports OK')"
```

## 4. Environment health

```powershell
# Watchdog scheduled task still registered?
Get-ScheduledTask -TaskName "ElFagerWatchdog" -ErrorAction SilentlyContinue

# No stray shell artifacts in repo root (past quoting accidents)
Get-ChildItem -Name | Where-Object { $_ -match '^(=|Accept$|GET$|Host$|User-Agent$)' }

# Secrets still gitignored
git check-ignore .env data/vault.key data/token.json
```

Expected: watchdog task present, no stray files listed, all three secret
paths echoed back by check-ignore.

## 5. If the change touched voice, trading, or the HUD

Those paths need a live smoke test — launch `python main.py`, press
Ctrl+Space, say one sentence in Arabic and one in English, and confirm the
transcript is sane before calling the change verified. Tests alone don't
cover the microphone → Whisper → brain path.
