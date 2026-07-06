"""
El Fager — Full-screen JARVIS HUD powered by QWebEngineView.

Renders ui/assets/hud.html (the Claude Design standalone export) and
bridges Python state into the running React component via a JS fiber walk.

Scene indices (match the design's bottom nav order):
  0 Boot  1 Standby  2 Voice  3 Vision  4 Devices
  5 (unused — was Stocks)  6 Inbox  7 Agenda  8 Memory  9 Briefing
  10 Food  11 Gym
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

_ASSETS = Path(__file__).parent / "assets"
_HUD_HTML = _ASSETS / "hud.html"
_CACHE_DIR = Path(__file__).parent.parent / "data" / "web_cache"

# Scene indices (index 5 is the design's retired stocks scene — never routed to)
SCENE_BOOT = 0
SCENE_STANDBY = 1
SCENE_VOICE = 2
SCENE_VISION = 3
SCENE_DEVICES = 4
SCENE_INBOX = 6
SCENE_AGENDA = 7
SCENE_MEMORY = 8
SCENE_BRIEFING = 9
SCENE_FOOD = 10
SCENE_GYM = 11

# JS injected once the page finishes loading.
# Uses React fiber traversal to grab the DCLogic component instance and
# exposes a stable window._elf object for Python to call into.
# Retries for up to ~40 seconds to handle CDN latency on first launch.
_BRIDGE_JS = r"""
(function installBridge() {
  // _logic: the DCLogic Component instance (class Component extends DCLogic).
  // Captured by patching DCLogic.prototype.setState — the 1-second tick calls
  // setState so _logic is available within ≤1 s of install.
  var _logic = null;

  function patchDCLogic() {
    if (!window.DCLogic || window.DCLogic._elfPatched) return;
    window.DCLogic._elfPatched = true;
    var orig = window.DCLogic.prototype.setState;
    window.DCLogic.prototype.setState = function(patch) {
      if (!_logic) {
        _logic = this;

        // ── Voice scene: seed state fields & patch renderVals ──────────────
        _logic.state.voiceQuery = _logic.state.voiceQuery || '';
        _logic.state.voiceReply = _logic.state.voiceReply || '';
        _logic.state.voiceCaption = _logic.state.voiceCaption || '';
        var origRV = _logic.renderVals.bind(_logic);
        _logic.renderVals = function() {
          var v = origRV();
          v.voiceQuery  = _logic.state.voiceQuery  || '';
          v.voiceReply  = _logic.state.voiceReply  || '';
          v.voiceCaption = _logic.state.voiceCaption || '';
          return v;
        };

        // ── Proactive banner: patch buildProactive to use Python messages ──
        var origBP = _logic.buildProactive.bind(_logic);
        _logic.buildProactive = function(sc) {
          var pmap = _logic.state._proMap;
          if (pmap && pmap[sc]) {
            var pm = pmap[sc];
            var h = React.createElement;
            var hl = function(t) { return h('span', { style: { color: '#ff9d3a' } }, t); };
            var parts = [];
            if (pm.prefix)    parts.push(pm.prefix);
            if (pm.highlight) parts.push(hl(pm.highlight));
            if (pm.suffix)    parts.push(pm.suffix);
            return { msg: h(React.Fragment, null, parts), tag: pm.tag || '' };
          }
          return origBP(sc);
        };

        // ── Food scene: patch buildNutri to use real profile targets ──────
        var origBN = _logic.buildNutri.bind(_logic);
        _logic.buildNutri = function() {
          var rn = _logic.state._realNutri;
          if (!rn) return origBN();
          var n = _logic.state.nutri || {};
          var kcal = rn.logged_kcal || 0;
          var target = rn.kcal || 2995;
          var ringDeg = Math.round(Math.min(100, kcal / target * 100) * 3.6);
          var macros = [
            { label: 'PROTEIN', cur: rn.logged_protein || 0, tgt: rn.protein || 200, hex: '#7CFFB0', rgb: '124,255,176' },
            { label: 'CARBS',   cur: rn.logged_carbs   || 0, tgt: rn.carbs   || 412, hex: '#36cfff', rgb: '54,207,255' },
            { label: 'FAT',     cur: rn.logged_fat     || 0, tgt: rn.fat     || 83,  hex: '#ff9d3a', rgb: '255,157,58' }
          ].map(function(m) {
            return Object.assign({}, m, {
              grams: m.cur + ' / ' + m.tgt + 'g',
              barOuter: 'height:6px;border-radius:3px;margin-top:7px;background:rgba(' + m.rgb + ',.14);overflow:hidden;',
              barInner: 'height:100%;border-radius:3px;transition:width .3s ease;width:' + Math.min(100, Math.round(m.cur / m.tgt * 100)) + '%;background:' + m.hex + ';box-shadow:0 0 8px ' + m.hex + ';',
              labelStyle: 'font-size:11px;letter-spacing:2px;color:rgba(205,238,251,.55);',
              gramStyle: "font-family:'Share Tech Mono',monospace;font-size:13px;color:" + m.hex + ';'
            });
          });
          var base = origBN();
          base.kcalText = kcal + ' / ' + target + ' kcal';
          base.ringDeg  = ringDeg;
          base.macros   = macros;
          base.kcalCur  = kcal;
          base.kcalTgt  = target;
          return base;
        };

        // Replay any queued proactive / nutri calls that arrived early
        var pendingScenes = Object.keys(_pendingPro);
        if (pendingScenes.length) {
          pendingScenes.forEach(function(sc) {
            var pp = _pendingPro[sc];
            _applyProactive(parseInt(sc), pp.prefix, pp.highlight, pp.suffix, pp.tag);
          });
          _pendingPro = {};
        }
        if (_pendingNutri) {
          var pn = _pendingNutri; _pendingNutri = null;
          _applyNutri(pn);
        }

        console.log('[bridge] DCLogic captured, scene=' + this.state.scene);
      }
      return orig ? orig.call(this, patch) : undefined;
    };
  }

  function doGoto(scene) {
    if (_logic && typeof _logic.goto === 'function') { _logic.goto(scene); return; }
    // Fallback: click the nav button (React normalises style so try both forms)
    var nav = document.querySelector('[style*="bottom:28px"]') ||
              document.querySelector('[style*="bottom: 28px"]');
    if (nav) {
      var btns = nav.querySelectorAll('button');
      if (scene >= 0 && scene < btns.length) { btns[scene].click(); return; }
    }
    var allBtns = Array.from(document.querySelectorAll('button'));
    var navBtns = allBtns.filter(function(b) {
      return Array.from(b.querySelectorAll('span')).some(function(s) {
        return /^0[1-9]$|^1[0-2]$/.test((s.textContent || '').trim());
      });
    });
    if (scene >= 0 && scene < navBtns.length) { navBtns[scene].click(); return; }
    console.log('[bridge] goto(' + scene + ') deferred — logic not yet captured');
  }

  function doSetState(patch) {
    if (_logic && typeof _logic.setState === 'function') {
      _logic.setState(patch);
      return;
    }
    console.log('[bridge] setState deferred — logic not yet captured');
  }

  // Pending queues for calls that arrive before _logic is captured.
  var _pendingPro    = {};            // { scene: { prefix, highlight, suffix, tag } }
  var _pendingNutri  = null;          // realNutri object

  function _applyProactive(scene, prefix, highlight, suffix, tag) {
    var pmap = Object.assign({}, _logic.state._proMap || {});
    pmap[scene] = { prefix: prefix, highlight: highlight, suffix: suffix, tag: tag };
    _logic.setState({ _proMap: pmap });
  }

  function _applyNutri(rn) {
    _logic.setState({ _realNutri: rn });
  }

  function doSetNutri(rn) {
    if (!_logic) { _pendingNutri = rn; return; }
    _applyNutri(rn);
  }

  // Inject a Python-driven proactive banner for a specific scene.
  function doSetProactive(scene, prefix, highlight, suffix, tag) {
    if (!_logic) { _pendingPro[scene] = { prefix: prefix, highlight: highlight, suffix: suffix, tag: tag }; return; }
    _applyProactive(scene, prefix, highlight, suffix, tag);
  }

  function tryInstall() {
    if (!document.getElementById('dc-root')) return false;
    if (!document.querySelector('.sc-host')) return false;
    if (!window.DCLogic && typeof window.__dcSetProps !== 'function') return false;

    patchDCLogic();

    window._elf = {
      goto:          doGoto,
      setState:      doSetState,
      setProactive:  doSetProactive,
      setNutri:      doSetNutri,
      getState:      function() { return _logic ? _logic.state : null; },
      getScene:      function() { return _logic ? _logic.state.scene : -1; },
    };
    console.log('[bridge] _elf installed. DCLogic patched=' + !!window.DCLogic._elfPatched);
    return true;
  }

  let tries = 0;
  const iv = setInterval(function() {
    if (tryInstall() || ++tries > 200) clearInterval(iv);
  }, 200);
})();
"""


class _DebugPage(QWebEnginePage):
    """WebEnginePage that prints JS console messages to stdout."""

    def javaScriptConsoleMessage(self, level, message, line, source):
        level_str = {0: "LOG", 1: "WARN", 2: "ERR", 3: "INFO"}.get(level, str(level))
        src = source.split("/")[-1] if source else ""
        print(f"[HUD-JS] {level_str} {src}:{line}  {message}", flush=True)


class HudWebView(QWebEngineView):
    """Full-screen JARVIS HUD rendered in a WebEngine view."""

    ready = pyqtSignal()  # emitted once the bridge is installed

    def __init__(self, parent=None):
        super().__init__(parent)

        # Enable disk cache on the default profile so React/DC assets are
        # cached after first launch — subsequent starts skip the CDN entirely.
        _profile = QWebEngineProfile.defaultProfile()
        _profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _profile.setCachePath(str(_CACHE_DIR))

        self.setPage(_DebugPage(self))

        # Allow the file:// page to fetch React and other scripts from CDN
        s = self.page().settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

        self._bridge_ready = False
        self._pending_js: list[str] = []

        self.loadFinished.connect(self._on_load_finished)
        self._load_hud()

    def _load_hud(self):
        if _HUD_HTML.exists():
            self.load(QUrl.fromLocalFile(str(_HUD_HTML)))
        else:
            self.setHtml(
                "<body style='background:#000;color:#ff6060;font-family:monospace'>"
                "hud.html not found</body>"
            )

    def _on_load_finished(self, ok: bool):
        if not ok:
            return
        self.page().runJavaScript(_BRIDGE_JS, self._on_bridge_injected)

    def _on_bridge_injected(self, _result):
        self._poll_bridge()

    def _poll_bridge(self, tries: int = 0):
        self.page().runJavaScript(
            "typeof window._elf !== 'undefined'",
            lambda ok: self._on_poll(ok, tries),
        )

    def _on_poll(self, ok, tries: int):
        if ok:
            if not self._bridge_ready:
                self._bridge_ready = True
                print("[HUD] Bridge ready — DC globals connected", flush=True)
                self.ready.emit()
                for js in self._pending_js:
                    self.page().runJavaScript(js)
                self._pending_js.clear()
        elif tries < 150:
            QTimer.singleShot(300, lambda: self._poll_bridge(tries + 1))

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def _js(self, code: str):
        if self._bridge_ready:
            self.page().runJavaScript(code)
        else:
            self._pending_js.append(code)

    def goto_scene(self, index: int):
        self._js(f"window._elf && window._elf.goto({index})")

    def set_state(self, patch: dict):
        self._js(f"window._elf && window._elf.setState({json.dumps(patch)})")

    def push_telemetry(self, cpu: int, ram: int, net: float):
        """Update left-rail telemetry bars with live system values."""
        self._js(
            f"window._elf && window._elf.setState({{cpu:{cpu},ram:{ram},net:{round(net,1)}}})"
        )

    def push_voice_result(self, heard: str, response: str):
        """Switch to Voice scene and show the heard text + response."""
        self.goto_scene(SCENE_VOICE)
        patch = json.dumps({
            "voiceQuery": heard,
            "voiceReply": response,
            "voiceCaption": "",
            "processing": False,
        })
        self._js(f"window._elf && window._elf.setState({patch})")

    def push_proactive(
        self,
        scene: int,
        prefix: str,
        highlight: str,
        suffix: str,
        tag: str,
    ):
        """
        Inject a dynamic proactive banner message for the given scene index.
        Renders as: "{prefix}{ORANGE highlight}{suffix}  TAG"
        """
        self._js(
            f"window._elf && window._elf.setProactive("
            f"{scene}, {json.dumps(prefix)}, {json.dumps(highlight)}, "
            f"{json.dumps(suffix)}, {json.dumps(tag)})"
        )

    def push_nutrition(
        self,
        kcal: int,
        protein: int,
        carbs: int,
        fat: int,
        logged_kcal: int = 0,
        logged_protein: int = 0,
        logged_carbs: int = 0,
        logged_fat: int = 0,
    ):
        """
        Push real nutrition targets (and today's logged totals) to the Food scene.
        Patches buildNutri() to use real profile data instead of hardcoded defaults.
        """
        rn = json.dumps({
            "kcal": kcal, "protein": protein, "carbs": carbs, "fat": fat,
            "logged_kcal": logged_kcal, "logged_protein": logged_protein,
            "logged_carbs": logged_carbs, "logged_fat": logged_fat,
        })
        self._js(f"window._elf && window._elf.setNutri({rn})")

    def enter_standby(self):
        self.goto_scene(SCENE_STANDBY)

    def enter_boot(self):
        self.goto_scene(SCENE_BOOT)
