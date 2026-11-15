from PySide6.QtCore import QEventLoop, QTimer

from contract_app.ui import MainWindow


class Credentials:
    def get(self):
        return ""


def test_new_library_page_and_busy_controls(qt_app, store):
    window = MainWindow(store, Credentials())
    window.show()
    window.navigate(5)
    qt_app.processEvents()
    assert window.pages.currentWidget() is window.library_page
    assert window.library_page.import_drive_button.isVisible()
    window.busy(True)
    window.library_page.refresh()
    assert not window.library_page.import_drive_button.isEnabled()
    assert not window.library_page.template_button.isEnabled()
    window.busy(False)
    assert window.library_page.import_drive_button.isEnabled()
    window.close()


def test_worker_can_start_next_stage_after_finishing(qt_app, store):
    window = MainWindow(store, Credentials())
    loop = QEventLoop()
    results = []
    def second(value):
        results.append(value)
        loop.quit()
    def first(value):
        assert not window.workers
        results.append(value)
        window.run_job(lambda: "second", second, "second")
    window.run_job(lambda: "first", first, "first")
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert results == ["first", "second"]
    assert not window.workers
    window.close()


def test_cancel_does_not_start_a_followup_or_create_document(qt_app, store):
    window = MainWindow(store, Credentials())
    loop = QEventLoop()
    results = []
    window.run_job(lambda: "value", results.append, "read")
    worker = window.workers[0]
    window.cancel_job()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    qt_app.processEvents()
    assert not results
    assert not window.last_result
    window.close()
