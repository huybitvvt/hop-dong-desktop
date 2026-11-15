from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="Hợp Đồng — Windows local document assistant")
    parser.add_argument("--smoke-test", metavar="SCREENSHOT", help="Run UI and local demo offscreen, save screenshot, then exit")
    args = parser.parse_args()
    if args.smoke_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont, QFontDatabase, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Hợp Đồng")
    app.setOrganizationName("LocalContract")
    from contract_app.storage import resource_path
    font_path = resource_path("fonts/NotoSans.ttf")
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont("Noto Sans", 10))
    app.setWindowIcon(QIcon(str(resource_path("app.ico"))))
    from contract_app.ui import MainWindow
    try:
        window = MainWindow()
    except Exception:
        QMessageBox.critical(None, "Không mở được ứng dụng", "Không đọc được dữ liệu ứng dụng. Kiểm tra quyền truy cập thư mục %LOCALAPPDATA%\\HopDongAI.")
        return 1
    if not args.smoke_test and app.primaryScreen():
        available = app.primaryScreen().availableGeometry()
        window.resize(min(1260, available.width() - 40), min(840, available.height() - 50))
    window.show()
    if args.smoke_test:
        def smoke():
            try:
                # Import the real packaged SDK and credential backend without a network call.
                from google import genai
                from google.genai import types
                from contract_app.models import Intent
                import keyring
                import json
                probe = genai.Client(api_key="smoke-test-placeholder", vertexai=False)
                types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=Intent.model_json_schema())
                probe.close()
                backend = type(keyring.get_keyring()).__module__
                if os.name == "nt" and not backend.startswith("keyring.backends.Windows"):
                    raise RuntimeError("Windows credential backend not bundled")
                window.run_demo()
                if not window.last_result or not window.last_result.path.exists():
                    raise RuntimeError("Demo did not generate a document")
                destination = Path(args.smoke_test)
                destination.parent.mkdir(parents=True, exist_ok=True)
                window.grab().save(str(destination))
                destination.with_suffix(".json").write_text(json.dumps({"status": "ok", "gemini_sdk": "loaded without network", "credential_backend": backend, "word_file": str(window.last_result.path)}, ensure_ascii=False, indent=2), encoding="utf-8")
                print("SMOKE_OK " + str(window.last_result.path), flush=True)
                app.exit(0)
            except Exception as exc:
                import json
                destination = Path(args.smoke_test)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.with_suffix(".json").write_text(json.dumps({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)[:500]}), encoding="utf-8")
                print("SMOKE_FAILED", flush=True)
                app.exit(2)
        QTimer.singleShot(300, smoke)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
