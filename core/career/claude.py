"""The one way the career pipeline talks to Claude. Every call is recorded by
telemetry under "career", so the daily cost shows in the usage audit."""
import json

MODEL = "claude-sonnet-5"
# The Big 4, and the companies Mo picked ("opus" in companies.json), are the
# goal: scoring, letters, interview prep and referral notes aimed at them get
# the stronger model.
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
