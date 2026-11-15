"""Verify release contents and detect the configured credential without printing it."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from contract_app.storage import Credentials


def verify():
    path = ROOT / "dist/HopDongAI-Windows.zip"
    key = Credentials().get().encode("utf-8")
    forbidden = []
    found_key = False
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        for info in archive.infolist():
            name = info.filename.lower().replace("\\", "/")
            parts = name.split("/")
            if any(part in ("private", "processing_cache", "client-preview-data", "template_sources", "library_sources", "imported_contracts") for part in parts):
                forbidden.append(info.filename)
            if name.endswith((".sqlite3", ".onnx", ".traineddata", "/settings.json", "/.source-url", "/.env")):
                forbidden.append(info.filename)
            if key:
                previous = b""
                with archive.open(info) as handle:
                    while chunk := handle.read(1_048_576):
                        if key in previous + chunk:
                            found_key = True
                        previous = chunk[-len(key):]
        damaged = archive.testzip()
    assert "HopDongAI/HopDongAI.exe" in names
    assert any(name.startswith("HopDongAI/_internal/") for name in names)
    assert not forbidden and not found_key and damaged is None
    report = {"status": "ok", "files": len(names), "size_mb": round(path.stat().st_size / 1024**2, 1),
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "private_or_model_files": len(forbidden),
              "configured_key_found": found_key, "credential_scan": "checked" if key else "no configured credential"}
    (ROOT / "artifacts/release-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    path.with_suffix(".zip.sha256").write_text(report["sha256"] + "  " + path.name + "\n", encoding="ascii")
    print(json.dumps(report))


if __name__ == "__main__":
    verify()
