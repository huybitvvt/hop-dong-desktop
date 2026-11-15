import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from contract_app.bootstrap import bootstrap
from contract_app.storage import Store


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "data")
    bootstrap(instance)
    config = instance.config()
    config["output_directory"] = str(tmp_path / "output")
    instance.save_config(config)
    return instance


@pytest.fixture(scope="session")
def qt_app():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    from contract_app.storage import resource_path
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont(str(resource_path("fonts/NotoSans.ttf")))
    yield app
    # Dispose native windows while QApplication is alive. PySide on Windows can
    # otherwise tear down cached widgets after the platform plugin at shutdown.
    from PySide6.QtCore import QCoreApplication, QEvent, QThread
    for widget in app.topLevelWidgets():
        for thread in widget.findChildren(QThread):
            if thread.isRunning():
                thread.requestInterruption()
                thread.wait(5000)
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
