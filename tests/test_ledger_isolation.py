"""The suite must never write to the real Trust Ledger."""
from pathlib import Path


def test_the_ledger_a_test_sees_is_not_the_real_one():
    from core import ledger
    assert Path(ledger._LEDGER).resolve() != Path("data/action_ledger.jsonl").resolve()


def test_a_confirmed_send_in_a_test_leaves_the_real_ledger_alone():
    import hashlib
    from core import staging
    real = Path("data/action_ledger.jsonl")
    before = hashlib.sha256(real.read_bytes()).hexdigest() if real.exists() else None
    staging.reset()
    staging.stage(medium="gmail", target="isolation@test", body="hi")
    staging.resolve("sent")
    staging.reset()
    after = hashlib.sha256(real.read_bytes()).hexdigest() if real.exists() else None
    assert before == after
