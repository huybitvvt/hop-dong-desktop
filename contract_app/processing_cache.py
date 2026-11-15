"""Versioned local results, keyed by content and task; no credentials or prompts."""
from pathlib import Path
import hashlib
import json
import uuid


class ProcessingCache:
    def __init__(self, folder: Path):
        self.folder = folder

    @staticmethod
    def digest(value: bytes | str):
        return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()

    def get(self, key: str):
        path = self.folder / (self.digest(key) + ".json")
        try:
            if path.stat().st_size > 8_000_000:
                return None
            envelope = json.loads(path.read_text(encoding="utf-8"))
            payload = envelope["payload"]
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            if envelope.get("version") == 1 and envelope.get("checksum") == self.digest(encoded):
                return payload
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def put(self, key: str, value):
        temporary = self.folder / (uuid.uuid4().hex + ".tmp")
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
            envelope = {"version": 1, "checksum": self.digest(encoded), "payload": value}
            temporary.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.folder / (self.digest(key) + ".json"))
        except OSError:
            pass
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
