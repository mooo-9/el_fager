"""Lower other apps' audio while El Fager listens, and put it back after.

On 2026-09-05 Mo asked for a song, and for the next ten turns the mic heard
the song instead of him: Whisper transcribed it back as "I'm sorry, I'm
sorry…" and El Fager answered it. Ducking every other app's volume session
while the mic is open keeps the room quiet enough to hear him — Spotify, a
browser playing YouTube, anything with a Windows audio session.

El Fager's own session is never touched, nor System Sounds. Each app is put
back to exactly the level it had, unless it was changed by hand meanwhile.
Ducking is never a gate: if Windows audio can't be reached, listening goes on.
"""
import contextlib
import json
import os
from pathlib import Path

# Other apps sit at this fraction of their own level while the mic is open:
# low enough that Whisper hears a voice over them, loud enough to still know
# the song is playing.
DUCK_TO = 0.15


def _enabled() -> bool:
    """Settings key `duck_while_listening`, on by default."""
    # The suite must never reach real audio sessions — a test run would turn
    # down whatever Mo is listening to.
    if os.getenv("EL_FAGER_TEST_MODE"):
        return False
    try:
        settings = json.loads(Path("data/settings.json").read_text(encoding="utf-8"))
    except Exception:
        return True
    return bool(settings.get("duck_while_listening", True))


def _sessions():
    """Every Windows audio session, via pycaw. The caller's thread needs COM,
    and the pipeline records on a QThread, so it is initialised here."""
    import comtypes
    from pycaw.pycaw import AudioUtilities

    try:
        comtypes.CoInitialize()
    except OSError:
        pass                        # already initialised on this thread
    return AudioUtilities.GetAllSessions()


@contextlib.contextmanager
def ducked():
    """Other apps are low inside the block and back to their levels after,
    however the block ends."""
    lowered = []                    # (volume interface, original, what we set)
    if _enabled():
        try:
            own = os.getpid()
            for session in _sessions():
                process = session.Process
                if process is None or process.pid == own:
                    continue        # System Sounds, and El Fager's own voice
                volume = session.SimpleAudioVolume
                original = volume.GetMasterVolume()
                quiet = original * DUCK_TO
                volume.SetMasterVolume(quiet, None)
                lowered.append((volume, original, quiet))
        except Exception:
            pass                    # listening matters more than quiet
    try:
        yield
    finally:
        for volume, original, quiet in lowered:
            try:
                # Changed by hand while we listened: that level is the one to keep.
                if abs(volume.GetMasterVolume() - quiet) < 0.005:
                    volume.SetMasterVolume(original, None)
            except Exception:
                pass
