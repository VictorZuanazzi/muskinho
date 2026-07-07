"""Encrypted phone number registry persisted to a volume file."""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel

REGISTER_PREFIX = "register number "


class RegistryData(BaseModel):
    """jid -> number. O(1) lookup."""
    numbers: dict[str, str] = {}

    @property
    def jids(self) -> list[str]:
        return list(self.numbers.keys())

    def __getitem__(self, jid: str) -> str | None:
        return self.numbers.get(jid)

    def __setitem__(self, jid: str, number: str) -> None:
        self.numbers[jid] = number


class PhoneNumberRegistry:
    """Stores jid -> phone number mappings, encrypted on disk. Survives restarts."""

    @classmethod
    def from_env(cls) -> "PhoneNumberRegistry":
        path = os.getenv("REGISTRY_FILE", "./data/registry.enc")
        key = os.getenv("REGISTRY_SECRET_KEY")
        return cls(path, key)

    def __init__(self, file_path: str | Path, secret_key: str) -> None:
        self._path = Path(file_path)
        self._fernet = Fernet(secret_key.encode())
        self._data: RegistryData | None = None

    @property
    def data(self) -> RegistryData:
        if self._data is None:
            self._load()
        return self._data

    def _load(self) -> RegistryData:
        try:
            raw = self._path.read_bytes()
            decrypted = self._fernet.decrypt(raw)
            self._data = RegistryData.model_validate_json(decrypted.decode())
        except (InvalidToken, ValueError, FileNotFoundError):
            self._data = RegistryData()
        return self._data

    def _save(self, data: RegistryData) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = data.model_dump_json().encode()
        self._path.write_bytes(self._fernet.encrypt(payload))

    def register(self, jid: str, number: str) -> None:
        self.data[jid] = number
        self._save(self.data)

    def try_register(self, jid: str, msg: str) -> tuple[str | None, bool]:
        """If message is 'register number X', register and return (number, is_new). Else None."""
        if (not msg.lower().startswith(REGISTER_PREFIX)) or not (number:= msg[len(REGISTER_PREFIX):].strip()) or not (is_new:= jid not in self.data.jids):
            return None, False

        self.data[jid] = number
        self._save(self.data)
        return (number, is_new)

    def get_number(self, jid: str) -> str | None:
        """Return the phone number for jid, or None if not registered."""
        return self.data[jid]
