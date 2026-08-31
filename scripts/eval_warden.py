"""
Measure Warden's accuracy against a labelled set of realistic agent outputs.

Warden decides whether an agent actually did the work. Two error modes matter,
and they cost differently:

  false reject -- good work marked failed. The supervisor retries it, so a
                  side-effecting task (a logged meal, a sent message) may
                  happen twice. This is the expensive one.
  false accept -- unfinished work marked done. The mission moves on carrying a
                  gap. This is the failure the whole layer exists to stop.

Needs a real ANTHROPIC_API_KEY -- the cases are deliberately the ones the
heuristic cannot settle. Roughly 17 Haiku calls, well under a cent.

    python scripts/eval_warden.py            # all cases
    python scripts/eval_warden.py --offline  # heuristic-only cases, no API
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_CASES = Path(__file__).resolve().parent.parent / "tests" / "data" / "warden_cases.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true",
                        help="only the cases the heuristic settles; makes no API calls")
    args = parser.parse_args()

    from core.agents.verifier import verify

    cases = json.loads(_CASES.read_text(encoding="utf-8"))
    if args.offline:
        cases = [c for c in cases if c["heuristic"]]
    elif not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Run with --offline for the "
              "heuristic-only cases, or set the key for the full run.")
        return 2

    false_rejects, false_accepts, unclear, correct = [], [], [], 0

    for case in cases:
        verdict, reason = verify(case["task"], case["acceptance"], case["result"])
        # 'unclear' counts as a pass in the supervisor, so score it that way.
        effective = "pass" if verdict in ("pass", "unclear") else "fail"
        ok = effective == case["expect"]
        correct += ok
        if verdict == "unclear":
            unclear.append(case["id"])
        if not ok and case["expect"] == "pass":
            false_rejects.append((case["id"], reason))
        elif not ok:
            false_accepts.append((case["id"], reason))
        mark = "ok  " if ok else "MISS"
        print(f"  {mark} {case['id']:34} expected {case['expect']:4} "
              f"got {verdict}")

    total = len(cases)
    print(f"\n{correct}/{total} correct ({100 * correct // total}%)")
    print(f"  false rejects (good work retried):    {len(false_rejects)}")
    print(f"  false accepts (bad work marked done): {len(false_accepts)}")
    if unclear:
        print(f"  inspector unavailable on {len(unclear)}: {', '.join(unclear)}")
    for label, rows in (("FALSE REJECT", false_rejects), ("FALSE ACCEPT", false_accepts)):
        for case_id, reason in rows:
            print(f"  {label} {case_id}: {reason[:100]}")

    return 0 if not false_accepts and not false_rejects else 1


if __name__ == "__main__":
    raise SystemExit(main())
