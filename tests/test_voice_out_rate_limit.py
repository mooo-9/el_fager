"""When Groq's voice hits its daily limit, El Fager goes straight to Edge.

It always fell back to Edge per sentence, but only after asking Groq first:
three requests a sentence (the SDK retries twice), about 1.6 s each before
Edge even started, for the hours until the limit reset. These run a real Groq
client against a fake server — no network, no quota.
"""
import httpx
import pytest

from core import voice_out

LIMIT = {"error": {
    "message": "Rate limit reached for model `canopylabs/orpheus-v1-english` in organization "
               "`org_x` service tier `on_demand` on tokens per day (TPD): Limit 3600, "
               "Used 3285, Requested 1579. Please try again in 8h25m36s.",
    "type": "tokens", "code": "rate_limit_exceeded"}}


class FakeGroqServer:
    def __init__(self):
        self.requests = 0
        self.reply = lambda: httpx.Response(200, content=b"RIFFwav")

    def __call__(self, request):
        self.requests += 1
        return self.reply()


@pytest.fixture
def server(monkeypatch, tmp_path):
    from groq import Groq
    fake = FakeGroqServer()
    client = Groq(api_key="gsk_test", http_client=httpx.Client(transport=httpx.MockTransport(fake)))
    from core import groq_client
    monkeypatch.setattr(groq_client, "get", lambda: client)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(voice_out, "_groq_tts_until", 0.0)
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(voice_out, "_now", lambda: clock["now"])
    fake.clock = clock
    return fake


@pytest.fixture
def vo(monkeypatch):
    out = voice_out.VoiceOutput.__new__(voice_out.VoiceOutput)
    out._backend = "auto"
    out._voice_en = "en-US-GuyNeural"
    monkeypatch.setattr(out, "_synth_edge", lambda text: "edge.mp3")
    return out


def _cleanup(path):
    import os
    if path and path.endswith(".wav"):
        os.unlink(path)


class TestRateLimit:
    def test_a_rate_limited_sentence_asks_groq_once_then_uses_edge(self, server, vo):
        server.reply = lambda: httpx.Response(429, json=LIMIT, headers={"retry-after": "30336"})
        assert vo._synthesize("Hello there.") == "edge.mp3"
        assert server.requests == 1, "the SDK's retries doubled and tripled the wait"

    def test_the_rest_of_the_limit_goes_straight_to_edge(self, server, vo):
        server.reply = lambda: httpx.Response(429, json=LIMIT)
        vo._synthesize("First sentence.")
        for sentence in ("Second.", "Third.", "Fourth."):
            assert vo._synthesize(sentence) == "edge.mp3"
        assert server.requests == 1

    def test_groq_is_tried_again_once_the_limit_resets(self, server, vo):
        server.reply = lambda: httpx.Response(429, json=LIMIT)
        vo._synthesize("Before.")
        server.clock["now"] += 8 * 3600 + 25 * 60 + 36 - 5     # just before the reset
        vo._synthesize("Still limited.")
        assert server.requests == 1
        server.clock["now"] += 10                              # just after it
        server.reply = lambda: httpx.Response(200, content=b"RIFFwav")
        path = vo._synthesize("After.")
        assert server.requests == 2 and path.endswith(".wav")
        _cleanup(path)

    def test_the_retry_after_header_is_used_when_the_message_gives_no_time(self, server, vo):
        server.reply = lambda: httpx.Response(
            429, json={"error": {"message": "Rate limit reached.", "code": "rate_limit_exceeded"}},
            headers={"retry-after": "120"})
        vo._synthesize("One.")
        server.clock["now"] += 119
        vo._synthesize("Two.")
        assert server.requests == 1
        server.clock["now"] += 2
        vo._synthesize("Three.")
        assert server.requests == 2

    def test_with_no_time_given_it_waits_a_sensible_default(self, server, vo):
        server.reply = lambda: httpx.Response(
            429, json={"error": {"message": "Rate limit reached.", "code": "rate_limit_exceeded"}})
        vo._synthesize("One.")
        server.clock["now"] += voice_out.GROQ_TTS_DEFAULT_COOLDOWN - 1
        vo._synthesize("Two.")
        assert server.requests == 1

    def test_any_other_failure_does_not_bench_groq(self, server, vo):
        server.reply = lambda: httpx.Response(500, json={"error": {"message": "boom"}})
        assert vo._synthesize("One.") == "edge.mp3"
        vo._synthesize("Two.")
        assert server.requests == 2, "a one-off server error must not skip Groq for hours"

    def test_a_working_groq_still_speaks_first(self, server, vo):
        path = vo._synthesize("Hello.")
        assert path.endswith(".wav") and server.requests == 1
        _cleanup(path)


class TestParseWait:
    @pytest.mark.parametrize("message,seconds", [
        ("Please try again in 8h25m36s.", 8 * 3600 + 25 * 60 + 36),
        ("Please try again in 21m12s.", 21 * 60 + 12),
        ("Please try again in 4m48s.", 4 * 60 + 48),
        ("Please try again in 13h5m59.999999999s.", 13 * 3600 + 5 * 60 + 60),
        ("Please try again in 2.5s.", 3),
        ("no time in here", None),
    ])
    def test_it_reads_groqs_own_wording(self, message, seconds):
        assert voice_out._retry_in_seconds(message) == seconds
