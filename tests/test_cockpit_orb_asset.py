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
        "setState", "setAmbient", "bloom", "start", "stop", "ready", "state",
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
