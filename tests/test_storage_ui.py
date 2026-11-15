from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtWidgets import QApplication
import pytest

from contract_app.storage import Credentials, desktop_directory
from contract_app.ui import MainWindow


class MemoryCredentials:
    def get(self):
        return ""

    def forget(self):
        pass


def test_settings_never_store_api_key(store):
    config = store.config()
    config["api_key"] = "fake-sensitive-value"
    config["GEMINI_API_KEY"] = "fake-sensitive-value"
    store.save_config(config)
    assert "fake-sensitive-value" not in store.config_file.read_text(encoding="utf-8")


def test_windows_desktop_is_resolved_from_known_folder():
    assert desktop_directory().is_absolute()
    assert desktop_directory().exists()


def test_native_ui_demo_history_and_navigation(qt_app, store, tmp_path):
    window = MainWindow(store, MemoryCredentials())
    window.show()
    qt_app.processEvents()
    window.run_demo()
    qt_app.processEvents()
    assert window.last_result and window.last_result.path.exists()
    assert window.history_table.rowCount() == 1
    assert "Người đại diện" in window.preview.toPlainText()
    assert "1.000.000.000" in window.preview.toPlainText()
    for index in range(5):
        window.navigate(index)
        assert window.pages.currentIndex() == index
        assert window.nav.checkedId() == index
    window.navigate(0)
    window.resize(980, 680)
    qt_app.processEvents()
    assert window.submit_button.isVisible()
    assert window.prompt.isVisible()
    window.close()


def test_background_error_recovers_ui_without_exposing_exception(qt_app, store):
    window = MainWindow(store, MemoryCredentials())
    window.show()
    def fail():
        raise RuntimeError("secret-api-key")
    loop = QEventLoop()
    window.run_job(fail, lambda _: None, "Đang thử")
    window.workers[0].finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    qt_app.processEvents()
    assert not window.workers
    assert window.submit_button.isEnabled()
    assert "secret-api-key" not in window.chat.toPlainText()
    window.close()


def test_prompt_hint_is_hidden_on_focus_and_restored_only_when_empty_and_blurred(qt_app, store):
    window = MainWindow(store, MemoryCredentials())
    window.show()
    qt_app.processEvents()
    hint = window.prompt.placeholderText()
    assert hint
    window.prompt.setFocus()
    qt_app.processEvents()
    assert window.prompt.placeholderText() == ""
    QTest.keyClicks(window.prompt, "ggg")
    qt_app.processEvents()
    assert window.prompt.toPlainText() == "ggg"
    assert window.prompt.placeholderText() == ""
    QTest.keyClick(window.prompt, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(window.prompt, Qt.Key.Key_Backspace)
    qt_app.processEvents()
    assert window.prompt.toPlainText() == ""
    assert window.prompt.placeholderText() == ""
    window.submit_button.setFocus()
    qt_app.processEvents()
    assert window.prompt.placeholderText() == hint
    window.close()


@pytest.mark.parametrize("preedit", ["jjjjjj", "đang gõ tiếng Việt"])
def test_ime_preedit_hides_hint_before_text_is_committed(qt_app, store, preedit):
    window = MainWindow(store, MemoryCredentials())
    window.show()
    window.activateWindow()
    window.submit_button.setFocus()
    qt_app.processEvents()
    hint = window.prompt.placeholderText()
    assert hint
    window.prompt.setFocus()
    qt_app.processEvents()
    QApplication.sendEvent(window.prompt, QInputMethodEvent(preedit, []))
    qt_app.processEvents()
    assert window.prompt.hasFocus()
    assert window.prompt.toPlainText() == ""  # IME text is not committed yet.
    assert window.prompt.placeholderText() == ""
    commit = QInputMethodEvent()
    commit.setCommitString(preedit)
    QApplication.sendEvent(window.prompt, commit)
    qt_app.processEvents()
    assert window.prompt.hasFocus()
    assert window.prompt.toPlainText() == preedit
    assert window.prompt.placeholderText() == ""
    window.prompt.clear()
    assert window.prompt.placeholderText() == ""
    window.submit_button.setFocus()
    qt_app.processEvents()
    assert window.prompt.placeholderText() == hint
    window.close()


def test_cancel_ime_preedit_keeps_hint_hidden_until_leaving_the_empty_input(qt_app, store):
    window = MainWindow(store, MemoryCredentials())
    window.show()
    window.activateWindow()
    window.submit_button.setFocus()
    qt_app.processEvents()
    hint = window.prompt.placeholderText()
    assert hint
    window.prompt.setFocus()
    qt_app.processEvents()
    QApplication.sendEvent(window.prompt, QInputMethodEvent("đang gõ", []))
    assert window.prompt.placeholderText() == ""
    QApplication.sendEvent(window.prompt, QInputMethodEvent("", []))
    qt_app.processEvents()
    assert window.prompt.hasFocus()
    assert window.prompt.toPlainText() == ""
    assert window.prompt.placeholderText() == ""
    window.submit_button.setFocus()
    qt_app.processEvents()
    assert window.prompt.placeholderText() == hint
    window.close()
