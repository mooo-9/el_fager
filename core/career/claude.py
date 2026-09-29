"""The one way the career pipeline talks to Claude. Every call is recorded by
telemetry under "career", so the daily cost shows in the usage audit."""
import json
import time

MODEL = "claude-sonnet-5"
# The Big 4, and the companies Mo picked ("opus" in companies.json), are the
# goal: scoring, interview prep and referral notes aimed at them get the
# stronger model. Cover letters get it for the Big 4 only (tailor.py).
PREMIUM_MODEL = "claude-opus-5"

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        from core.telemetry import instrument_client
        _client = instrument_client(anthropic.Anthropic(), "career")
    return _client


def model_for(company: str) -> str:
    from core.career import companies
    target = companies.match(company)
    return PREMIUM_MODEL if target and target in companies.premium() else MODEL


def _params(prompt: str, *, system: str, schema: "dict | None" = None,
            effort: str = "medium", max_tokens: int = 8000, model: str = MODEL) -> dict:
    output_config: dict = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    return {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "output_config": output_config,
        "messages": [{"role": "user", "content": prompt}],
    }


def _answer(message, schema: "dict | None"):
    if message.stop_reason == "refusal":
        return None
    text = next((b.text for b in message.content if b.type == "text"), "")
    return json.loads(text) if schema else text.strip()


def ask(prompt: str, *, system: str, schema: "dict | None" = None,
        effort: str = "medium", max_tokens: int = 8000, model: str = MODEL):
    """Claude's answer: parsed JSON when `schema` is given, text otherwise.
    None when the model declines."""
    response = _get_client().messages.create(**_params(
        prompt, system=system, schema=schema, effort=effort,
        max_tokens=max_tokens, model=model))
    return _answer(response, schema)


# Most batches end within minutes; the API guarantees an end within 24 hours.
_BATCH_POLL_SECONDS = 30


def ask_batch(asks: "list[dict]") -> list:
    """ask() for many prompts at once, as one Message Batch: half the price,
    answered in minutes rather than seconds. Each item holds ask()'s keyword
    arguments, with the prompt under "prompt". Answers come back in the same
    order; None for any that was declined, failed or couldn't be read."""
    if not asks:
        return []
    from core.telemetry import check_budget, record_api_usage
    check_budget()
    client = _get_client()
    batch = client.messages.batches.create(requests=[
        {"custom_id": str(i), "params": _params(**a)} for i, a in enumerate(asks)])
    started = time.monotonic()
    while batch.processing_status != "ended":
        time.sleep(_BATCH_POLL_SECONDS)
        batch = client.messages.batches.retrieve(batch.id)
    waited_ms = (time.monotonic() - started) * 1000
    answers: list = [None] * len(asks)
    # Results arrive in any order: matched back by custom_id.
    for entry in client.messages.batches.results(batch.id):
        if entry.result.type != "succeeded":
            continue
        i = int(entry.custom_id)
        message = entry.result.message
        record_api_usage("career", message.model, message.usage, waited_ms, batch=True)
        try:
            answers[i] = _answer(message, asks[i].get("schema"))
        except ValueError:
            pass    # one unreadable answer mustn't cost the rest of the run
    return answers
