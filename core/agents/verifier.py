"""
Warden -- El Fager's inspector.

Every agent in this system returns a bare string. Nothing in that string says
whether the work was actually done: "I could not find that file" and a finished
report are the same type. Warden reads the result against the task and its
acceptance criteria and returns a verdict, so the supervisor can retry or
escalate instead of marking failed work as done.

Two stages, cheapest first:
  1. Heuristic -- the failure shapes this codebase already emits are caught with
     no API call at all.
  2. One Haiku call for everything else.

Warden being broken must never fail an agent that worked: any error in the
inspection itself returns "unclear", which the supervisor treats as a pass.
"""
from collections import namedtuple

Verdict = namedtuple("Verdict", ["verdict", "reason"])  # pass | fail | unclear

_MODEL = "claude-haiku-4-5-20251001"

# Failure shapes emitted by core/brain.py, the tool layer, and the agents.
_FAILURE_PREFIXES = (
    "tool error (",
    "unknown tool:",
    "api error:",
    "error:",
    "no search results found",
    "[stopped after",
    "[response cut off",
)

_DEFAULT_ACCEPTANCE = (
    "the task as stated was actually carried out, not merely described, "
    "planned, or declined"
)

_PROMPT = """\
You are Warden, the inspector for El Fager's agents.

You can see ONLY the agent's own words below. You cannot open the calendar, the
inbox, the meal log, or any file, so you cannot confirm that an action left a
trace. Do not ask for evidence you have no way to check. Judge the result on its
face: does it read as work carried out, or as work not carried out?

FAIL only when the result:
  - says the agent could not do it, was blocked, or lacked a tool;
  - describes a plan, or what it WOULD do, instead of an outcome;
  - answers with generalities that contain none of what was asked for;
  - or visibly falls short of a stated acceptance criterion (the criterion asks
    for three items and the result names one).

Otherwise PASS. In particular:
  - A plain confirmation is enough for an action task. "Done." or "Logged."
    means the agent did it. It is not your job to doubt that.
  - Extra detail beyond what was asked is never a defect.
  - You cannot know whether an answer is exhaustive. Judge what is there, not
    what might be missing.
  - Style, length, and tone are not your concern.

TASK: {task}

ACCEPTANCE CRITERIA: {acceptance}

AGENT RESULT:
{result}

Reply with exactly one line: "PASS" or "FAIL: <short reason>".
"""


def _heuristic(result: str) -> Verdict | None:
    """Catch obvious failures without spending an API call."""
    if result is None or not result.strip():
        return Verdict("fail", "the agent returned nothing")
    stripped = result.strip()
    # Deliberately no minimum length: "Done." is a legitimate result for an
    # action task, and auto-failing it would retry work that already happened.
    # Short results go to Warden to judge.
    lowered = stripped.lower()
    for prefix in _FAILURE_PREFIXES:
        if lowered.startswith(prefix):
            return Verdict("fail", stripped[:150])
    return None


def verify(task: str, acceptance: str | None, result: str) -> Verdict:
    """Judge one agent result. Never raises."""
    early = _heuristic(result)
    if early is not None:
        return early

    try:
        import anthropic
        from core.telemetry import instrument_client

        client = instrument_client(anthropic.Anthropic(), "warden")
        response = client.messages.create(
            model=_MODEL,
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": _PROMPT.format(
                    task=task,
                    acceptance=acceptance or _DEFAULT_ACCEPTANCE,
                    result=result[:4000],
                ),
            }],
        )
        text = response.content[0].text.strip()
    except Exception as e:
        # The inspector is down -- do not punish the agent for that.
        return Verdict("unclear", f"inspection unavailable: {e}")

    upper = text.upper()
    if upper.startswith("PASS"):
        return Verdict("pass", "")
    if upper.startswith("FAIL"):
        reason = text.split(":", 1)[1].strip() if ":" in text else text
        return Verdict("fail", reason[:200] or "did not meet the acceptance criteria")
    # An answer in neither shape is not evidence of failure.
    return Verdict("unclear", f"unrecognised verdict: {text[:100]}")
