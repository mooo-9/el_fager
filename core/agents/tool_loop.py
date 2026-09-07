"""
Shared tool-use loop for El Fager's task agents.

The four task agents (Herald, Chronos, Abacus, Forge) differ only in their
system prompt and their tool set: each runs a small Claude loop over its OWN
tools rather than the brain's ~380, which is both cheaper and more accurate
than routing the same work through core/brain.py.

Agents that see the vision-driven desktop (Argus) or drive a browser (Nomad)
have their own loops -- this is for agents whose tools are plain Python calls.
"""
import json

_MODEL = "claude-haiku-4-5-20251001"
_MAX_STEPS = 6          # a task needing more than this belongs in a mission
_MAX_TOKENS = 900
_MAX_RESULT_CHARS = 3000


def run_tool_loop(source: str, system: str, tools: list[dict],
                  dispatch: dict, task: str,
                  max_steps: int = _MAX_STEPS) -> str:
    """Run `task` through a Claude tool-use loop bounded to `tools`.

    source   -- telemetry label, e.g. "comms_agent"
    dispatch -- {tool_name: callable(**kwargs) -> str}; a name absent from this
                map is refused, which is how the confirm_before gate is
                enforced (the tool is simply not there to call).
    Returns the agent's final text, or a plain error string the supervisor's
    inspector will read as a failure.
    """
    import anthropic
    from core.telemetry import instrument_client

    try:
        client = instrument_client(anthropic.Anthropic(), source)
    except Exception as e:
        return f"Error: {source} could not start ({e})."

    messages: list[dict] = [{"role": "user", "content": task}]
    last_text = ""

    for _ in range(max_steps):
        try:
            response = client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=system,
                tools=tools,
                messages=messages,
            )
        except Exception as e:
            return f"Error: {source} API call failed ({e})."

        text = next((b.text for b in response.content if b.type == "text"), "")
        if text:
            last_text = text

        if response.stop_reason != "tool_use":
            return last_text or "No answer produced."

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": _call(dispatch, block.name, block.input),
            })
        messages.append({"role": "user", "content": results})

    return (last_text + " " if last_text else "") + \
        f"[{source} stopped after {max_steps} steps without finishing]"


def _call(dispatch: dict, name: str, args: dict) -> str:
    """Invoke one tool. A name missing from dispatch is refused, not guessed."""
    fn = dispatch.get(name)
    if fn is None:
        return (f"Tool '{name}' is not available for this task. "
                f"Do not retry it; report that you could not do that part.")
    try:
        result = fn(**(args or {}))
    except Exception as e:
        return f"Tool error ({name}): {e}"
    if isinstance(result, str):
        return result[:_MAX_RESULT_CHARS]
    return json.dumps(result, ensure_ascii=False, default=str)[:_MAX_RESULT_CHARS]


def tool(name: str, description: str,
         properties: dict[str, tuple[str, str]] | None = None,
         required: list[str] | None = None) -> dict:
    """Build one tool schema. properties: {name: (json_type, description)}."""
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {
                pname: {"type": ptype, "description": pdesc}
                for pname, (ptype, pdesc) in (properties or {}).items()
            },
            "required": required or [],
        },
    }
