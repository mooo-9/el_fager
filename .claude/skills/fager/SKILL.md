---
name: fager
description: Send a command or skill to the running El Fager assistant over its authenticated local command channel, and read back the result. Use when the user says "tell fager...", "have el fager do...", or wants an El Fager skill executed.
---

# El Fager command bridge

El Fager exposes an authenticated HTTP command channel on port 8765
(`core/dashboard.py`). Commands are queued as autonomous tasks and executed
by the ProactiveEngine through `brain.chat()` within ~60 seconds — all of El
Fager's tools and safety gates apply.

## Send a command

```powershell
$token = (Get-Content "C:\claude proj\el_fager\data\settings.json" | ConvertFrom-Json).dashboard_token
Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/command" -Method Post `
  -Headers @{Authorization = "Bearer $token"} `
  -ContentType "application/json" `
  -Body (@{text = "COMMAND HERE"} | ConvertTo-Json)
```

Constraints: `text` max 500 chars. The response is `{"queued": true, "task_id": "..."}`.

To run a stored El Fager skill by name, send: `run my skill '<skill name>'`.

## Read the result

Poll the status endpoint (no auth needed, read-only) and find the task by id
under the background-tasks section:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8765/api/status" | ConvertTo-Json -Depth 5
```

Tasks execute within ~60s of queuing; wait ~70s before declaring failure.

## If the channel is unreachable

El Fager isn't running. Say so, and offer either to start it
(`python main.py` from the repo root) or to execute the request directly
with your own tools instead.
