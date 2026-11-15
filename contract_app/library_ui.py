"""Document catalog page. Import/index operations use the main window's worker."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .library import DocumentLibrary
from .template_review import text_label

STATUS_LABELS = {
    "archive": "Trong ZIP; chưa tải", "scan": "Bản scan", "text": "Đã đọc chữ",
    "encrypted": "PDF có mật khẩu", "long": "Cần tách trang", "complex": "PDF phức tạp",
    "unreadable": "Cần kiểm tra", "template": "Đã tạo mẫu", "large": "Trên 40 MB; cần tách",
}


class LibraryPage(QWidget):
    template_requested = Signal(int)
    customer_requested = Signal(int)
    open_requested = Signal(int)

    def __init__(self, store, run_job, progress, cancelled, parent=None):
        super().__init__(parent)
        self.library = DocumentLibrary(store)
        self.run_job, self.progress, self.cancelled = run_job, progress, cancelled
        self.rows = []
        self.busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.addWidget(text_label("Bộ hồ sơ của bạn", "SectionTitle"), 1)
        self.import_folder_button = QPushButton("Nhập thư mục")
        self.import_folder_button.clicked.connect(self.import_folder)
        top.addWidget(self.import_folder_button)
        self.import_zip_button = QPushButton("Nhập ZIP")
        self.import_zip_button.clicked.connect(self.import_zip)
        top.addWidget(self.import_zip_button)
        self.import_drive_button = QPushButton("Nhập ZIP từ Drive")
        self.import_drive_button.clicked.connect(self.import_drive)
        top.addWidget(self.import_drive_button)
        layout.addLayout(top)
        layout.addWidget(text_label("Nhập cả bộ hồ sơ để tìm theo tên hoặc nội dung đã đọc. Việc lập danh mục không gửi tài liệu đến AI. Chỉ hồ sơ được chọn mới được gửi khi đọc khách hàng hoặc chuẩn bị mẫu.", "Muted"))
        self.search = QLineEdit()
        self.search.setAccessibleName("Tìm trong thư viện hồ sơ")
        self.search.setPlaceholderText("Tìm tên đối tác, loại hợp đồng, tên file hoặc nội dung đã đọc…")
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(200)
        self.search_timer.timeout.connect(self.refresh)
        self.search.textChanged.connect(lambda _: self.search_timer.start())
        layout.addWidget(self.search)
        self.table = QTableWidget(0, 4)
        self.table.setAccessibleName("Hồ sơ trong thư viện")
        self.table.setHorizontalHeaderLabels(["Hồ sơ", "Dung lượng", "Trang", "Trạng thái"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(3, 160)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self.update_selection)
        self.table.doubleClicked.connect(lambda _: self.emit_selected(self.open_requested))
        layout.addWidget(self.table, 1)
        self.details = text_label("Chọn hồ sơ để mở, lấy khách hàng hoặc tạo mẫu tái sử dụng.", "Muted")
        self.details.setMaximumHeight(90)
        layout.addWidget(self.details)
        actions = QHBoxLayout()
        self.open_button = QPushButton("Mở hồ sơ")
        self.open_button.clicked.connect(lambda: self.emit_selected(self.open_requested))
        actions.addWidget(self.open_button)
        self.customer_button = QPushButton("Lấy thông tin khách hàng")
        self.customer_button.clicked.connect(lambda: self.emit_selected(self.customer_requested))
        actions.addWidget(self.customer_button)
        actions.addStretch()
        self.template_button = QPushButton("Tạo mẫu từ hồ sơ")
        self.template_button.setObjectName("Primary")
        self.template_button.clicked.connect(lambda: self.emit_selected(self.template_requested))
        actions.addWidget(self.template_button)
        layout.addLayout(actions)
        self.summary = text_label("", "Muted")
        layout.addWidget(self.summary)
        self.refresh()

    def controls(self):
        return [self.import_folder_button, self.import_zip_button, self.import_drive_button,
                self.open_button, self.customer_button, self.template_button]

    def set_busy(self, active):
        self.busy = active
        for control in self.controls():
            control.setEnabled(not active)
        self.update_selection()

    def refresh(self):
        previous = self.selected_id()
        self.rows = self.library.documents(self.search.text())
        self.table.setRowCount(len(self.rows))
        for index, item in enumerate(self.rows):
            values = [item["name"], f"{item['size'] / 1024**2:.2f} MB", str(item["pages"] or "—"),
                      STATUS_LABELS.get(item["status"], item["status"])]
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setToolTip(item["member"] or item["path"])
                self.table.setItem(index, col, cell)
            if item["id"] == previous:
                self.table.selectRow(index)
        self.summary.setText(f"{len(self.rows)} hồ sơ trong danh sách. PDF scan tìm được theo tên; sau khi chuẩn bị mẫu, có thể tìm cả nội dung đã đọc.")
        self.update_selection()

    def selected_id(self):
        row = self.table.currentRow()
        return self.rows[row]["id"] if 0 <= row < len(self.rows) else None

    def emit_selected(self, signal):
        identity = self.selected_id()
        if identity is not None:
            signal.emit(identity)

    def update_selection(self):
        row = self.table.currentRow()
        item = self.rows[row] if 0 <= row < len(self.rows) else None
        self.open_button.setEnabled(bool(item) and not self.busy)
        contract = bool(item) and Path(item["name"]).suffix.lower() in (".pdf", ".docx")
        self.customer_button.setEnabled(contract and not self.busy)
        self.template_button.setEnabled(contract and not self.busy)
        if item:
            location = item["member"] or item["path"]
            self.details.setText(location + ("\nMẫu: " + item["template_path"] if item["template_path"] else ""))
        else:
            self.details.setText("Chọn hồ sơ để mở, lấy khách hàng hoặc tạo mẫu tái sử dụng.")

    def imported(self, result):
        self.refresh()
        message = f"Đã thêm {result.added} hồ sơ; bỏ qua {result.skipped} hồ sơ đã có."
        if result.cancelled:
            message = "Đã dừng. " + message
        if result.errors:
            message += f"\n{len(result.errors)} file cần kiểm tra: " + "\n".join(result.errors[:5])
        self.details.setText(message)
        self.progress(message.split("\n")[0])

    def import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục hồ sơ PDF/Word/Excel")
        if folder:
            self.run_job(lambda: self.library.index_folder(Path(folder), progress=self.progress, cancelled=self.cancelled),
                         self.imported, "Đang lập danh mục thư mục hồ sơ…")

    def import_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn ZIP hồ sơ", "", "ZIP (*.zip)")
        if path:
            self.run_job(lambda: self.library.index_zip(Path(path), progress=self.progress, cancelled=self.cancelled),
                         self.imported, "Đang đọc danh mục ZIP; chưa giải nén toàn bộ…")

    def import_drive(self):
        link, accepted = QInputDialog.getText(self, "Nhập ZIP từ Drive", "Link chia sẻ công khai của file ZIP:")
        if accepted and link.strip():
            self.run_job(lambda: self.library.index_zip(drive_link=link, progress=self.progress, cancelled=self.cancelled),
                         self.imported, "Đang đọc danh mục ZIP trên Drive…")
