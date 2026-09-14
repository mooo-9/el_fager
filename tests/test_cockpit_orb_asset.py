"""The Ember sphere's page, checked without a browser.

ui/assets/cockpit_orb.html is the one piece of the Cockpit the Python suite
cannot reach: a syntax error in it leaves the stage silently black, every
Python test still green, and cockpit.py's _orb_js() swallowing the failure.

Chromium cannot run under QT_QPA_PLATFORM=offscreen on this machine — it dies
with STATUS_STACK_BUFFER_OVERRUN — so the suite cannot drive the real widget.
These do the next best thing: parse the script with Node, and pin the API
surface ui/cockpit.py calls into.

Verified once by hand against real QWebEngine, for the record: the loop runs
at ~45 fps (67 frames in 1.5 s), the sphere draws (8,536 lit pixels in a
200x200 centre sample), idle is amber rgb(234,146,63) and listening is cyan
rgb(41,209,248), and speech moves the centroid 20 px across versus 2 px at
rest.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ORB = Path("ui/assets/cockpit_orb.html")


@pytest.fixture(scope="module")
def script() -> str:
    html = ORB.read_text(encoding="utf-8")
    match = re.search(r"<script>(.*)</script>", html, re.S)
    assert match, "no <script> block in the orb page"
    return match.group(1)


class TestItParses:
    @pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
    def test_the_javascript_has_no_syntax_error(self, script, tmp_path):
        # The failure this catches: a stray character makes the whole script
        # dead, the canvas never paints, and nothing else in the suite notices.
        js = tmp_path / "orb.js"
        js.write_text(script, encoding="utf-8")
        result = subprocess.run(["node", "--check", str(js)],
                                capture_output=True, text=True)
        assert result.returncode == 0, f"syntax error in orb script:\n{result.stderr}"


class TestTheApiCockpitDrivesStillExists:
    """ui/cockpit.py calls these through runJavaScript, where a missing name
    fails silently — there is no exception to catch on the Python side."""

    @pytest.mark.parametrize("member", [
        "setState", "setAmbient", "bloom", "start", "stop", "ready", "state", "setStage", "setLevel",
    ])
    def test_the_member_is_defined(self, script, member):
        assert re.search(rf"\b{member}\s*[({{:]", script), \
            f"window.orb.{member} is gone; ui/cockpit.py still calls it"

    def test_every_state_the_cockpit_pushes_has_a_colour(self, script):
        # cockpit.py is read as text rather than imported. Importing a Qt
        # module from this file reordered initialisation enough to segfault a
        # later Qt test under the offscreen platform, and nothing here needs
        # Qt: both sides of the comparison are literals in source.
        cockpit_src = Path("ui/cockpit.py").read_text(encoding="utf-8")
        table = re.search(r"_ORB_STATE\s*=\s*\{(.*?)\n\}", cockpit_src, re.S)
        assert table, "_ORB_STATE is gone from ui/cockpit.py"
        pushed = set(re.findall(r':\s*"(\w+)"', table.group(1)))
        assert pushed, "no states parsed out of _ORB_STATE"

        colours = re.search(r"const COLORS\s*=\s*\{(.*?)\}", script, re.S)
        assert colours, "the COLORS table is gone"
        defined = set(re.findall(r"(\w+)\s*:", colours.group(1)))
        for orb_state in pushed:
            assert orb_state in defined, \
                f"cockpit pushes '{orb_state}' but the orb has no colour for it"

    def test_the_loop_parks_itself_so_a_hidden_cockpit_costs_no_gpu(self, script):
        assert "cancelAnimationFrame" in script, \
            "stop() no longer cancels the frame; a cockpit in the tray would burn GPU"


def _colours(script) -> dict:
    table = re.search(r"const COLORS\s*=\s*\{(.*?)\}", script, re.S).group(1)
    return {name: tuple(int(v) for v in (r, g, b))
            for name, r, g, b in re.findall(r"(\w+):\s*\[\s*(\d+),\s*(\d+),\s*(\d+)\]", table)}


def _hue(rgb) -> float:
    import colorsys
    return colorsys.rgb_to_hsv(*(v / 255 for v in rgb))[0] * 360


class TestTheSphereIsBlue:
    """The reel's sphere is blue; El Fager's follows it (it was amber)."""

    @pytest.mark.parametrize("state", ["idle", "thinking", "speaking"])
    def test_rest_thinking_and_speech_are_blue(self, script, state):
        assert 205 <= _hue(_colours(script)[state]) <= 240, f"{state} is not blue"

    def test_listening_still_reads_apart_from_rest(self, script):
        colours = _colours(script)
        assert abs(_hue(colours["idle"]) - _hue(colours["listening"])) >= 25, \
            "listening would blur into the resting blue"

    def test_error_stays_red(self, script):
        hue = _hue(_colours(script)["error"])
        assert hue <= 15 or hue >= 345

    def test_it_opens_on_its_resting_colour(self, script):
        # The eased colour starts at `cur`; left amber, every open would fade
        # from gold to blue.
        cur = re.search(r"const cur = \{ r: (\d+), g: (\d+), b: (\d+) \}", script)
        assert cur, "the starting colour moved"
        assert tuple(int(v) for v in cur.groups()) == _colours(script)["idle"]


class TestMotionConstantsStayInRange:
    """Both of these shipped wrong once and were caught only by rendering."""

    def test_the_speech_ripple_cannot_deform_the_sphere_into_a_blob(self, script):
        # First attempt used 0.20/0.11 and turned it into a mushroom at volume.
        rip = re.search(r"rip1\s*=\s*env\s*\*\s*([\d.]+),\s*rip2\s*=\s*env\s*\*\s*([\d.]+)",
                        script)
        assert rip, "the ripple amplitudes moved; re-check them by rendering"
        assert float(rip.group(1)) <= 0.09, "ripple too strong to still read as a sphere"
        assert float(rip.group(2)) <= 0.06

    def test_the_envelope_never_falls_silent_mid_speech(self, script):
        # The floor matters more than the peak: an envelope returning to zero
        # between syllables reads as broken rather than as talking.
        floor = re.search(r"return Math\.min\(1,\s*\(([\d.]+)\s*\+", script)
        assert floor, "the speech envelope's floor term moved"
        assert float(floor.group(1)) >= 0.2, "the sphere would go still between syllables"


class TestTheSphereFillsTheStage:
    """The sphere centres on the middle column Python reports, not on the
    whole window, and sizes to it — the reel's fills the space between its
    panels, with larger, brighter clouds either side."""

    def test_it_centres_on_the_stage_it_is_given(self, script):
        assert re.search(r"stage\.x", script), "the sphere ignores the stage centre"

    def test_its_size_follows_the_free_space(self, script):
        assert re.search(r"stage\.w\s*\*", script), "the sphere ignores the stage width"
        assert re.search(r"stage\.h\s*\*", script), "the sphere ignores the stage height"

    def test_the_clouds_are_denser_and_brighter(self, script):
        counts = [int(n) for n in re.findall(r"buildCluster\((\d+),", script)]
        assert counts and min(counts) >= 220, f"clouds too sparse: {counts}"
        alpha = re.search(r"const a = \(([\d.]+) - d \* [\d.]+\) \* dim;", script)
        assert alpha and float(alpha.group(1)) >= 0.8, "clouds too faint"


# Runs the page's script under Node with a stub canvas that records every dot
# drawn, so a test can ask how the sphere *moves*, not just what it declares.
_HARNESS = r"""
const radii = [];
let alphaSum = 0, alphaN = 0;
const ctx = {
  setTransform() {}, clearRect() {}, beginPath() {}, fill() {}, fillRect() {},
  arc(x, y, r) { radii.push(r); },
  createLinearGradient() { return { addColorStop() {} }; },
  set fillStyle(v) {
    const m = /rgba\([^)]*,([\d.]+)\)$/.exec(v);
    if (m) { alphaSum += +m[1]; alphaN++; }
  },
  get fillStyle() { return ''; },
  globalAlpha: 1,
};
const canvas = { clientWidth: 800, clientHeight: 600, width: 0, height: 0, getContext: () => ctx };
globalThis.window = globalThis;
window.devicePixelRatio = 1;
window.addEventListener = () => {};
window.matchMedia = () => ({ matches: false });
globalThis.document = { getElementById: () => canvas };
let pending = null;
globalThis.requestAnimationFrame = cb => { pending = cb; return 1; };
globalThis.cancelAnimationFrame = () => {};
"""

_DRIVER = """
let now = 1000;
function run(frames) { for (let i = 0; i < frames; i++) { now += 1000 / 60; const cb = pending; pending = null; cb(now); } }
// level: fed before every frame, as the recorder does ~30 times a second;
// null feeds nothing.
function measure(state, ambient, level = null) {
  window.orb.setState(state);
  window.orb.setAmbient(ambient);
  const frames = [];                          // mean dot alpha, frame by frame
  const feed = n => {
    for (let i = 0; i < n; i++) {
      if (level !== null) window.orb.setLevel(level);
      const sum = alphaSum, count = alphaN;
      run(1);
      frames.push((alphaSum - sum) / (alphaN - count));
    }
  };
  feed(240);                                  // let colour and envelope settle
  radii.length = 0; alphaSum = 0; alphaN = 0; frames.length = 0;
  feed(180);
  // swing: brightest frame over dimmest; beats: rises through the mean
  const mean = frames.reduce((a, b) => a + b, 0) / frames.length;
  let beats = 0;
  for (let i = 1; i < frames.length; i++) if (frames[i - 1] < mean && frames[i] >= mean) beats++;
  return { radius: radii.reduce((a, b) => a + b, 0) / radii.length, alpha: alphaSum / alphaN,
           swing: Math.max(...frames) / Math.min(...frames), beats };
}
const results = {
  idle: measure('idle', false),
  thinking: measure('thinking', false),
  speaking: measure('speaking', false),
  ambient: measure('idle', true),
  listeningSilent: measure('listening', false, 0),
  listeningLoud: measure('listening', false, 0.8),
};
// The recorder stops reporting (the turn ended) but the state has not moved on yet.
results.listeningStale = measure('listening', false, null);
console.log(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def motion(script, tmp_path_factory) -> dict:
    if not shutil.which("node"):
        pytest.skip("node not installed")
    import json
    js = tmp_path_factory.mktemp("orb") / "motion.js"
    js.write_text(_HARNESS + script + _DRIVER, encoding="utf-8")
    result = subprocess.run(["node", str(js)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestRestIsACalmerSpeech:
    """Mo liked the sphere listening and speaking but not at rest, and chose
    for rest to look like speech turned down: the speaking blue, and a slow,
    soft version of its ripple rather than a still dark sphere."""

    def test_rest_wears_the_speaking_blue(self, script):
        colours = _colours(script)
        assert colours["idle"] == colours["speaking"]

    def test_the_sphere_moves_at_rest(self, motion):
        # Speech swells the dots with the envelope; a still sphere at rest draws
        # them exactly as thinking (which stays still) does.
        assert motion["idle"]["radius"] > motion["thinking"]["radius"] * 1.03, motion

    def test_rest_is_calmer_than_speech(self, motion):
        assert motion["speaking"]["radius"] > motion["idle"]["radius"] * 1.03, motion

    def test_the_quiet_fade_keeps_two_thirds_of_the_light(self, motion):
        # Ambient used to dim to a third, which read as dull; two-thirds still
        # says "resting" without the sphere going dark.
        ratio = motion["ambient"]["alpha"] / motion["idle"]["alpha"]
        assert 0.55 <= ratio <= 0.75, motion


class TestListeningFollowsTheVoice:
    """Mo chose for the sphere to swell and ripple with their voice while it
    listens, and to settle when they pause."""

    def test_silence_leaves_it_still(self, motion):
        assert motion["listeningSilent"]["radius"] < motion["thinking"]["radius"] * 1.01, motion

    def test_a_loud_voice_swells_it(self, motion):
        assert motion["listeningLoud"]["radius"] > motion["thinking"]["radius"] * 1.03, motion

    def test_a_level_that_stops_arriving_does_not_hold_it_swollen(self, motion):
        assert motion["listeningStale"]["radius"] < motion["thinking"]["radius"] * 1.01, motion


class TestWorkingPulses:
    """Mo asked for a steady pulse while it works: the sphere breathes in and
    out and brightens on each beat, the same whatever else is going on."""

    def test_it_pulses_while_thinking(self, motion):
        assert motion["thinking"]["swing"] > 1.2, motion["thinking"]

    def test_the_pulse_is_steady_about_once_a_second(self, motion):
        # Three seconds are measured: a beat a second is two to four rises.
        assert 2 <= motion["thinking"]["beats"] <= 4, motion["thinking"]

    @pytest.mark.parametrize("state", ["idle", "listeningSilent"])
    def test_only_working_pulses(self, motion, state):
        assert motion[state]["swing"] < 1.1, motion[state]
