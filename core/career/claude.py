"""The one way the career pipeline talks to Claude. Every call is recorded by
telemetry under "career", so the daily cost shows in the usage audit."""
import json

MODEL = "claude-sonnet-5"
# The Big 4 are the goal: scoring, letters, interview prep and referral notes
# aimed at them get the stronger model. They're few (capped per firm a month).
BIG4_MODEL = "claude-opus-5"

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        from core.telemetry import instrument_client
        _client = instrument_client(anthropic.Anthropic(), "career")
    return _client


def model_for(tier: str) -> str:
    return BIG4_MODEL if tier == "big4" else MODEL


def model_for_company(name: str) -> str:
    from core.career import companies
    target = companies.match(name)
    return model_for(target["tier"] if target else "")


def ask(prompt: str, *, system: str, schema: "dict | None" = None,
        effort: str = "medium", max_tokens: int = 8000, model: str = MODEL):
    """Claude's answer: parsed JSON when `schema` is given, text otherwise.
    None when the model declines."""
    output_config: dict = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    response = _get_client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        output_config=output_config,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    return json.loads(text) if schema else text.strip()
