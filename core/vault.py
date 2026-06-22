import json
import os
from cryptography.fernet import Fernet

_DEFAULT_VAULT = os.path.join("data", "vault.enc")
_DEFAULT_KEY = os.path.join("data", "vault.key")


class Vault:
    """Fernet-encrypted key-value store for service credentials.

    Stored locally at data/vault.enc — never sent to any API.
    """

    def __init__(self, vault_path: str = _DEFAULT_VAULT, key_path: str = _DEFAULT_KEY):
        self._vault_path = vault_path
        self._key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get(self, service: str) -> dict | None:
        """Return credentials dict for service, or None if not stored."""
        return self._load().get(service)

    def set(self, service: str, credentials: dict) -> None:
        """Store (or overwrite) credentials for service."""
        data = self._load()
        data[service] = credentials
        self._save(data)

    def delete(self, service: str) -> None:
        """Remove credentials for service. No-op if not present."""
        data = self._load()
        if service in data:
            data.pop(service)
            self._save(data)

    def list_services(self) -> list[str]:
        """Return names of all stored services."""
        return list(self._load().keys())

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _load_or_create_key(self) -> bytes:
        if os.path.exists(self._key_path):
            with open(self._key_path, "rb") as f:
                return f.read()
        os.makedirs(os.path.dirname(self._key_path) or ".", exist_ok=True)
        key = Fernet.generate_key()
        with open(self._key_path, "wb") as f:
            f.write(key)
        return key

    def _load(self) -> dict:
        if not os.path.exists(self._vault_path):
            return {}
        with open(self._vault_path, "rb") as f:
            return json.loads(self._fernet.decrypt(f.read()))

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self._vault_path) or ".", exist_ok=True)
        with open(self._vault_path, "wb") as f:
            f.write(self._fernet.encrypt(json.dumps(data).encode()))
