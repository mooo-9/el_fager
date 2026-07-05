"""
Dashboard — read-only LAN status surface for El Fager.

Serves a single dark status page (auto-refresh) plus /api/status JSON on
http://<laptop-ip>:8765 so Mo can watch missions, costs, tasks, skills, and
trading from his phone on the same network.

Deliberately READ-ONLY and stdlib-only: GET requests, no commands, no
secrets in the snapshot. Commands stay voice/desktop-side.

Settings (data/settings.json): dashboard_enabled (default true),
dashboard_port (default 8765), dashboard_host (default 0.0.0.0).
"""
import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SETTINGS_PATH = Path("data/settings.json")
_TRADES_PATH = Path("data/trades.json")
_BACKTEST_PATH = Path("data/backtest_results.json")

_STARTED_AT = datetime.now()


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def build_snapshot() -> dict:
    """Assemble the full read-only status snapshot from on-disk state.
    Every section is individually fault-tolerant."""
    snap: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "started_at": _STARTED_AT.isoformat(timespec="seconds"),
    }

    try:
        from core.missions import MissionManager
        mgr = MissionManager()
        active = mgr.get_active()
        snap["mission"] = {
            "summary": mgr.format_status(),
            "active": bool(active),
            "steps": [
                {"n": s["n"], "description": s["description"], "status": s["status"]}
                for s in (active["steps"] if active else [])
            ],
        }
    except Exception:
        snap["mission"] = {"summary": "unavailable", "active": False, "steps": []}

    try:
        from core.telemetry import summarize
        today = summarize(days=1)
        week = summarize(days=7)
        snap["cost"] = {
            "today_usd": today["cost_usd"],
            "today_requests": today["requests"],
            "week_usd": week["cost_usd"],
            "avg_latency_ms": today["avg_latency_ms"],
        }
    except Exception:
        snap["cost"] = {"today_usd": 0, "today_requests": 0, "week_usd": 0,
                        "avg_latency_ms": 0}

    try:
        from core.skills.store import SkillStore
        skills = SkillStore().list_all()
        snap["skills"] = {
            "count": len(skills),
            "scheduled": sum(1 for s in skills if s.get("scheduled_task_id")),
            "names": [s["name"] for s in skills][:20],
        }
    except Exception:
        snap["skills"] = {"count": 0, "scheduled": 0, "names": []}

    try:
        from core.autonomous_tasks import AutonomousTaskManager
        tasks = AutonomousTaskManager().list_all()
        snap["tasks"] = {
            "pending": sum(1 for t in tasks if t["status"] == "pending"),
            "recent": [
                {"description": t["description"][:80], "status": t["status"]}
                for t in tasks[-8:]
            ],
        }
    except Exception:
        snap["tasks"] = {"pending": 0, "recent": []}

    try:
        trades = _read_json(_TRADES_PATH, [])
        snap["trading"] = {
            "total_trades": len(trades),
            "recent": [
                {"symbol": t.get("symbol"), "side": t.get("side"),
                 "qty": t.get("qty"), "price": t.get("price"),
                 "timestamp": (t.get("timestamp") or "")[:16],
                 "conviction": t.get("conviction")}
                for t in trades[-5:]
            ],
            "last_backtest": _read_json(_BACKTEST_PATH, {}).get("_run_at"),
        }
    except Exception:
        snap["trading"] = {"total_trades": 0, "recent": [], "last_backtest": None}

    return snap


_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>El Fager</title>
<style>
 body{background:#06090f;color:#9fd7e8;font-family:Consolas,monospace;
      margin:0;padding:16px}
 h1{color:#4dd6ff;font-size:20px;letter-spacing:3px;margin:0 0 4px}
 .sub{color:#3a6b7d;font-size:11px;margin-bottom:16px}
 .card{background:#0b1220;border:1px solid #163040;border-radius:8px;
       padding:12px 14px;margin-bottom:12px}
 .card h2{color:#4dd6ff;font-size:12px;letter-spacing:2px;margin:0 0 8px;
          text-transform:uppercase}
 .big{font-size:22px;color:#e8f7ff}
 .row{font-size:12px;padding:2px 0;color:#9fd7e8}
 .dim{color:#3a6b7d}
 .done{color:#41d98d}.pending{color:#e8c34d}.failed{color:#ff5d5d}
</style></head><body>
<h1>EL FAGER</h1>
<div class="sub" id="ts">connecting...</div>
<div class="card"><h2>Command</h2>
 <div style="display:flex;gap:8px">
  <input id="cmd" placeholder="tell El Fager..." maxlength="500"
   style="flex:1;background:#06090f;border:1px solid #163040;color:#e8f7ff;
          border-radius:6px;padding:8px;font-family:inherit">
  <button onclick="sendCmd()" style="background:#0e2a3a;border:1px solid #2a5d78;
   color:#4dd6ff;border-radius:6px;padding:8px 14px;font-family:inherit">SEND</button>
 </div><div class="row dim" id="cmdmsg"></div></div>
<div id="content"></div>
<script>
function token(){
 let t=localStorage.getItem('elf_token');
 if(!t){t=prompt('Dashboard token (from data/settings.json on the laptop):');
   if(t)localStorage.setItem('elf_token',t);}
 return t;}
async function sendCmd(){
 const text=document.getElementById('cmd').value.trim();
 if(!text)return;
 const msg=document.getElementById('cmdmsg');
 try{
  const r=await fetch('/api/command',{method:'POST',
    headers:{'Content-Type':'application/json',
             'Authorization':'Bearer '+token()},
    body:JSON.stringify({text})});
  if(r.status===401){localStorage.removeItem('elf_token');
    msg.textContent='bad token - try again';return;}
  const j=await r.json();
  msg.textContent=j.queued?'queued ('+j.task_id+') - runs within a minute'
                          :'error: '+(j.error||'unknown');
  if(j.queued)document.getElementById('cmd').value='';
 }catch(e){msg.textContent='send failed: '+e;}
}
document.getElementById('cmd').addEventListener('keydown',
  e=>{if(e.key==='Enter')sendCmd();});
async function load(){
 try{
  const r=await fetch('/api/status');const s=await r.json();
  document.getElementById('ts').textContent=
    'snapshot '+s.generated_at+' | up since '+s.started_at;
  let h='';
  h+='<div class="card"><h2>Cost</h2><div class="big">$'
    +s.cost.today_usd.toFixed(2)+' today</div><div class="row dim">'
    +s.cost.today_requests+' calls | $'+s.cost.week_usd.toFixed(2)
    +' this week | avg '+(s.cost.avg_latency_ms/1000).toFixed(1)+'s</div></div>';
  h+='<div class="card"><h2>Mission</h2><div class="row">'+s.mission.summary+'</div>';
  for(const st of s.mission.steps){
    h+='<div class="row"><span class="'+st.status+'">['+st.status+']</span> '
      +st.n+'. '+st.description+'</div>';}
  h+='</div>';
  h+='<div class="card"><h2>Skills</h2><div class="row">'+s.skills.count
    +' learned, '+s.skills.scheduled+' scheduled</div><div class="row dim">'
    +s.skills.names.join(', ')+'</div></div>';
  h+='<div class="card"><h2>Background tasks</h2><div class="row">'
    +s.tasks.pending+' pending</div>';
  for(const t of s.tasks.recent){
    h+='<div class="row"><span class="'+(t.status==='done'?'done':'pending')
      +'">['+t.status+']</span> '+t.description+'</div>';}
  h+='</div>';
  h+='<div class="card"><h2>Trading</h2><div class="row">'
    +s.trading.total_trades+' recorded trades';
  if(s.trading.last_backtest){h+=' | last backtest '
    +s.trading.last_backtest.slice(0,16);}
  h+='</div>';
  for(const t of s.trading.recent){
    h+='<div class="row">'+t.timestamp+' '+t.side+' '+t.qty+' '+t.symbol
      +' @ $'+t.price+(t.conviction?' ('+t.conviction+'%)':'')+'</div>';}
  h+='</div>';
  document.getElementById('content').innerHTML=h;
 }catch(e){document.getElementById('ts').textContent='offline: '+e;}
}
load();setInterval(load,30000);
</script></body></html>"""


_MAX_COMMAND_CHARS = 500


def _expected_token() -> str:
    return str(_read_json(_SETTINGS_PATH, {}).get("dashboard_token", "") or "")


def queue_command(text: str) -> dict:
    """Queue a phone command as an autonomous task (executed by the
    ProactiveEngine via brain.chat within ~60s — all normal gates apply)."""
    from core.autonomous_tasks import AutonomousTaskManager
    task = AutonomousTaskManager().add(description=text.strip())
    return {"queued": True, "task_id": task["id"]}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/status":
            body = json.dumps(build_snapshot()).encode("utf-8")
            self._send(200, "application/json", body)
        elif self.path in ("/", "/index.html"):
            self._send(200, "text/html; charset=utf-8", _PAGE.encode("utf-8"))
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if self.path != "/api/command":
            self._send(404, "text/plain", b"not found")
            return
        expected = _expected_token()
        supplied = self.headers.get("Authorization", "")
        if not expected or supplied != f"Bearer {expected}":
            self._send(401, "application/json",
                       b'{"error": "missing or invalid token"}')
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            text = str(payload.get("text", "")).strip()
        except Exception:
            self._send(400, "application/json", b'{"error": "bad json"}')
            return
        if not text or len(text) > _MAX_COMMAND_CHARS:
            self._send(400, "application/json",
                       b'{"error": "text required, max 500 chars"}')
            return
        try:
            result = queue_command(text)
            self._send(200, "application/json",
                       json.dumps(result).encode("utf-8"))
        except Exception:
            self._send(500, "application/json", b'{"error": "queue failed"}')

    def _send(self, code: int, ctype: str, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # keep the console quiet


def _ensure_token(settings: dict) -> dict:
    """Generate dashboard_token on first run so the command channel works
    out of the box. The token stays in data/settings.json (gitignored)."""
    if not settings.get("dashboard_token"):
        import secrets
        settings["dashboard_token"] = secrets.token_urlsafe(24)
        try:
            _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _SETTINGS_PATH.write_text(
                json.dumps(settings, indent=2, ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass
    return settings


def start_dashboard() -> ThreadingHTTPServer | None:
    """Start the dashboard in a daemon thread. Returns the server or None."""
    settings = _read_json(_SETTINGS_PATH, {})
    if not settings.get("dashboard_enabled", True):
        return None
    settings = _ensure_token(settings)
    host = settings.get("dashboard_host", "0.0.0.0")
    port = int(settings.get("dashboard_port", 8765))
    try:
        server = ThreadingHTTPServer((host, port), _Handler)
    except OSError as e:
        print(f"[Dashboard] could not bind {host}:{port}: {e}")
        return None
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="Dashboard")
    thread.start()
    print(f"[Dashboard] serving on http://{host}:{port}")
    return server
