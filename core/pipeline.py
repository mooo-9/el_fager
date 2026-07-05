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

# Conversation mode: after El Fager replies, keep listening this long for a
# follow-up before ending the conversation. Context persists across turns.
FOLLOWUP_WINDOW_SEC = 6.0
MAX_TURNS_PER_CONVERSATION = 10

# Phrases that end the conversation immediately (no follow-up window).
END_PHRASES = (
    "thanks", "thank you", "that's all", "bye", "goodbye", "stop",
    "خلاص", "شكرا", "مع السلامة", "باي",
)


def _is_screenshot_trigger(text: str) -> bool:
    text_lower = text.lower().strip()
    return any(t in text_lower for t in SCREENSHOT_TRIGGERS)


def _is_end_phrase(text: str) -> bool:
    words = text.lower().strip().rstrip(".!،").split()
    return len(words) <= 3 and any(p in text.lower() for p in END_PHRASES)


class PipelineWorker(QThread):
    """
    Runs the full voice interaction loop in a background thread.
    Signals drive all overlay state changes — never touch Qt widgets directly from here.

    Voice input runs in conversation mode: after each spoken reply, the mic
    reopens for FOLLOWUP_WINDOW_SEC and Brain context persists, so Mo can say
    "and tomorrow?" without repeating himself. The conversation (and context)
    ends on silence, an end phrase, or MAX_TURNS_PER_CONVERSATION.
    Text input stays single-turn (the text box has its own history UX).

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
                if transcript:
                    self._one_turn(transcript)
                    self.brain.reset_conversation()
                return

            if not self.voice_in.is_ready():
                self.state_update.emit("processing", "Loading Whisper model...", "")
                loaded = self.voice_in.wait_until_ready(timeout=180)
                if not loaded:
                    self.error.emit("Whisper model failed to load. Check your internet connection and try again.")
                    return

            try:
                for turn in range(MAX_TURNS_PER_CONVERSATION):
                    self.state_update.emit("listening", "", "")
                    audio = self.voice_in.record_audio(
                        start_timeout_sec=FOLLOWUP_WINDOW_SEC if turn > 0 else None
                    )
                    if audio is None:
                        if turn == 0:
                            return
                        break  # follow-up window closed — conversation over

                    self.state_update.emit("processing", "Transcribing...", "")
                    transcript = self.voice_in.transcribe(audio)
                    if not transcript:
                        if turn == 0:
                            self.error.emit("Nothing heard — please try again")
                            return
                        break

                    self._one_turn(transcript)
                    if _is_end_phrase(transcript):
                        break
            finally:
                self.brain.reset_conversation()

        except Exception as e:
            self.error.emit(f"Pipeline error: {e}")
            print(f"[El Fager] Pipeline exception: {e}")

        finally:
            self.done.emit()

    def _one_turn(self, transcript: str) -> None:
        """Process one utterance: think, remember, speak."""
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

        self.memory.store_conversation_summary(transcript, response)
        self.state_update.emit("speaking", transcript, response)
        self.voice_out.speak(response)
