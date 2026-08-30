"""
Supervisor -- El Fager's chain of command.

Nothing in this system used to check an agent's work: a mission step was marked
done whenever the call returned without raising, so an agent that answered "I
couldn't do that" counted as success. The supervisor is the fix. Every
assignment goes: budget gate -> execute (with a timeout) -> Warden inspects ->
retry once on failure -> escalate. Every attempt lands in the ledger.

Threading note: specialist agents build their own anthropic client and hold no
shared state, so they run on a worker thread with a wall-clock budget.
brain.chat does NOT -- it mutates conversation_history and the live-trading
state machine -- so a brain.chat executor is called on the calling thread and
its timeout is left to the API client.
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutureTimeout
from dataclasses import dataclass
from typing import Callable

from core.agents import ledger, registry

_MAX_ATTEMPTS = 2  # 1 try + 1 retry, matching core/missions.py

_RETRY_SUFFIX = (
    "\n\nYour previous attempt was rejected: {reason}\n"
    "Correct it this time and actually complete the task."
)


@dataclass
class AgentReport:
    callsign: str
    verdict: str          # pass | fail | unclear | blocked
    result: str
    reason: str = ""
    attempts: int = 1
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        """'unclear' passes: a broken inspector must not fail working agents."""
        return self.verdict in ("pass", "unclear")

    @property
    def speech(self) -> str:
        """cp1252-safe line for TTS."""
        if self.ok:
            return self.result
        return (f"{self.callsign} could not finish that. {self.reason}"
                if self.reason else f"{self.callsign} could not finish that.")


def _run_with_timeout(fn: Callable[[], str], timeout_s: int) -> str:
    """Run fn on a worker thread, raising TimeoutError past timeout_s."""
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except _FutureTimeout:
        raise TimeoutError(f"timed out after {timeout_s}s")
    finally:
        # The worker may still be running; don't block the caller waiting on it.
        executor.shutdown(wait=False)


def assign(agent: str, task: str, *, acceptance: str | None = None,
           verify: bool = True, source: str = "voice",
           executor: Callable[[str], str] | None = None,
           max_attempts: int = _MAX_ATTEMPTS) -> AgentReport:
    """Assign one task and hold the agent to it.

    agent        -- tool name or callsign; ignored when `executor` is given.
    verify       -- False for live voice turns (Mo reads the answer himself).
    executor     -- run the task through this callable instead of a registry
                    agent (used for mission steps that have no named agent,
                    which run through brain.chat).
    max_attempts -- 1 disables the retry. Callers that own their own retry loop
                    pass 1 so a failing step is not executed four times: mission
                    steps are requeued by MissionManager across cycles.
    """
    import time

    spec = registry.resolve(agent) if agent else None
    if executor is None and spec is None:
        return AgentReport(agent or "unknown", "fail",
                           f"No agent named '{agent}'.",
                           reason="unknown agent")

    callsign = spec.callsign if spec else registry.COMMANDER
    timeout_s = spec.timeout_s if spec else 0

    from core.telemetry import over_budget
    over, spent, budget = over_budget()
    if over:
        reason = (f"daily API budget reached -- ${spent:.2f} spent against a "
                  f"${budget:.2f} cap")
        ledger.record(callsign, task, "blocked", reason=reason, source=source,
                      acceptance=acceptance)
        return AgentReport(callsign, "blocked",
                           f"I did not start {callsign}: {reason}. "
                           f"Raise api_daily_budget_usd to continue.",
                           reason=reason)

    attempt_task = task
    last = AgentReport(callsign, "fail", "", reason="not attempted")

    max_attempts = max(1, int(max_attempts))
    for attempt in range(1, max_attempts + 1):
        token = ledger.start_run(callsign, attempt_task, source)
        started = time.monotonic()
        try:
            if executor is not None:
                result = executor(attempt_task)
            else:
                agent_obj = registry.load(spec.tool_name)
                result = _run_with_timeout(
                    lambda: agent_obj.run(attempt_task), timeout_s
                )
            result = result or ""
            error = None
        except Exception as e:
            result, error = "", str(e)
        finally:
            duration = time.monotonic() - started
            ledger.finish_run(token)

        if error is not None:
            verdict, reason = "fail", error
        elif not verify:
            verdict, reason = "pass", ""
        else:
            from core.agents.verifier import verify as inspect
            verdict, reason = inspect(task, acceptance, result)

        ledger.record(callsign, attempt_task, verdict, reason=reason,
                      attempt=attempt, duration_s=duration, source=source,
                      result=result, acceptance=acceptance)

        last = AgentReport(callsign, verdict, result, reason=reason,
                           attempts=attempt, duration_s=round(duration, 1))
        if last.ok:
            return last
        if attempt < max_attempts:
            attempt_task = task + _RETRY_SUFFIX.format(reason=reason or "unclear")

    return last
