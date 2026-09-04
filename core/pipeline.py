from PyQt6.QtCore import QThread, pyqtSignal

from core.brain import Brain
from core.memory import Memory
from core.voice_in import VoiceInput
from core.voice_out import VoiceOutput

SCREENSHOT_TRIGGERS = (
    "what's on my screen", "what is on my screen",
    "look at my screen", "what do you see",
    "read this", "what's this", "what is this",
    "شوف شاشتي", "إيه ده", "اقرا ده", "شوف ده",
)


def _is_screenshot_trigger(text: str) -> bool:
    text_lower = text.lower().strip()
    return any(t in text_lower for t in SCREENSHOT_TRIGGERS)


class PipelineWorker(QThread):
    """
    Runs the full voice interaction loop in a background thread.
    Signals drive all overlay state changes — never touch Qt widgets directly from here.

    state_update(state, transcript, response):
      state ∈ {"listening", "processing", "speaking"}
      transcript: what Mo said (empty while listening)
      response: El Fager's reply (empty until speaking)
    """

    state_update = pyqtSignal(str, str, str)
    done = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        voice_in: VoiceInput,
        brain: Brain,
        voice_out: VoiceOutput,
        memory: Memory,
        text_input: "str | None" = None,
    ):
        super().__init__()
        self.voice_in = voice_in
        self.brain = brain
        self.voice_out = voice_out
        self.memory = memory
        self.text_input = text_input

    def run(self):
        try:
            if self.text_input:
                transcript = self.text_input.strip()
                if not transcript:
                    return
            else:
                if not self.voice_in.is_ready():
                    self.state_update.emit("processing", "Loading Whisper model...", "")
                    loaded = self.voice_in.wait_until_ready(timeout=180)
                    if not loaded:
                        self.error.emit("Whisper model failed to load. Check your internet connection and try again.")
                        return

                self.state_update.emit("listening", "", "")
                audio = self.voice_in.record_audio()

                if audio is None:
                    return

                self.state_update.emit("processing", "Transcribing...", "")
                transcript = self.voice_in.transcribe(audio)

                if not transcript:
                    self.error.emit("Nothing heard — please try again")
                    return

            self.state_update.emit("processing", transcript, "")

            memory_context = self.memory.get_recent_context(transcript)

            if _is_screenshot_trigger(transcript):
                from tools.screen_tool import capture_screenshot, delete_temp_screenshot
                b64, tmp_path = capture_screenshot()
                if b64 is None:
                    self.error.emit("Screenshot failed — couldn't capture screen")
                    return
                response = self.brain.chat_with_screenshot(transcript, b64, memory_context)
                delete_temp_screenshot(tmp_path)
            else:
                response = self.brain.chat(transcript, memory_context)

            # History is NOT reset here - follow-ups ("and tomorrow?", "do that
            # again") need the previous turns. It holds only the user and
            # assistant text, not tool results, and lives until quit or a
            # tray -> Clear all memory.
            self.memory.store_conversation_summary(transcript, response)

            self.state_update.emit("speaking", transcript, response)
            self.voice_out.speak(response)

        except Exception as e:
            self.error.emit(f"Pipeline error: {e}")
            print(f"[El Fager] Pipeline exception: {e}")

        finally:
            self.done.emit()
