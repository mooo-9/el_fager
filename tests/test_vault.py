import pytest
from core.vault import Vault

@pytest.fixture
def vault(tmp_path):
    return Vault(
        vault_path=str(tmp_path / "vault.enc"),
        key_path=str(tmp_path / "vault.key"),
    )

def test_set_and_get(vault):
    vault.set("google", {"email": "mo@gmail.com", "password": "secret"})
    assert vault.get("google") == {"email": "mo@gmail.com", "password": "secret"}

def test_get_missing_returns_none(vault):
    assert vault.get("nonexistent") is None

def test_delete_removes_entry(vault):
    vault.set("twitter", {"token": "abc"})
    vault.delete("twitter")
    assert vault.get("twitter") is None

def test_delete_nonexistent_is_safe(vault):
    vault.delete("never_set")  # should not raise

def test_list_services(vault):
    vault.set("a", {"x": 1})
    vault.set("b", {"y": 2})
    assert set(vault.list_services()) == {"a", "b"}

def test_update_overwrites(vault):
    vault.set("svc", {"token": "old"})
    vault.set("svc", {"token": "new"})
    assert vault.get("svc") == {"token": "new"}

def test_data_is_encrypted_on_disk(vault):
    vault.set("test", {"secret": "my_password"})
    with open(vault._vault_path, "rb") as f:
        raw = f.read()
    assert b"secret" not in raw
    assert b"my_password" not in raw

def test_key_persists_across_instances(vault):
    vault.set("svc", {"token": "abc"})
    vault2 = Vault(vault_path=vault._vault_path, key_path=vault._key_path)
    assert vault2.get("svc") == {"token": "abc"}
