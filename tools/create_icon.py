from pathlib import Path
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygon
from PySide6.QtCore import QPoint, QRectF, Qt


if __name__ == "__main__":
    app = QApplication([])
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#1D4ED8"))
    painter.drawRoundedRect(QRectF(4, 4, 248, 248), 48, 48)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawRoundedRect(QRectF(65, 40, 126, 176), 12, 12)
    painter.setPen(QPen(QColor("#1D4ED8"), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for y in (85, 115, 145):
        painter.drawLine(88, y, 167, y)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#0F766E"))
    painter.drawEllipse(QRectF(144, 152, 72, 72))
    painter.setPen(QPen(QColor("#FFFFFF"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPolyline(QPolygon([QPoint(161, 188), QPoint(175, 201), QPoint(199, 176)]))
    painter.end()
    destination = Path(__file__).resolve().parents[1] / "assets"
    if not image.save(str(destination / "app.ico")):
        raise RuntimeError("Unable to write app icon")
    image.save(str(destination / "app-icon.png"))
