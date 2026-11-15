from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import html
import os
from pathlib import Path
import shutil

from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from .bootstrap import bootstrap
from .customers import read_customers
from .contract_import import GeminiDocumentExtractor
from .customer_review import CustomerImportReview
from .customer_editor import CustomerEditor
from .customer_fields import CUSTOMER_BASE_FIELDS, customer_field_key, extra_context, field_label
from .documents import document_text, template_fields
from .gemini import GeminiExtractor
from .library_ui import LibraryPage
from .models import ContractResult, FIELD_LABELS, Intent, PendingContract, UserError
from .money import format_money
from .service import ContractService
from .storage import Credentials, DEFAULT_MODEL, Store, desktop_directory, resource_path
from .theme import STYLE
from .template_builder import GeminiTemplateBuilder, template_metadata
from .template_review import TemplateChoiceDialog, TemplateReview, TemplateSourceDialog
from .template_selection import confident_template, rank_templates
from .processing_cache import ProcessingCache


DEMO_PROMPT = "Tạo hợp đồng với anh Thông, công ty X, số tiền 1 tỷ, nội dung thi công dự án Y."
PROMPT_HINT = "Ví dụ: Tạo hợp đồng với anh Thông, công ty X, số tiền 1 tỷ, nội dung thi công dự án Y…"


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, slot=None, primary=False):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        widget.setObjectName("Primary")
    if slot:
        widget.clicked.connect(slot)
    return widget


def card():
    widget = QFrame()
    widget.setObjectName("Card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    return widget, layout


class PromptEdit(QPlainTextEdit):
    """Hide the hint on focus, before the Windows/Vietnamese IME starts drawing."""

    def __init__(self, hint, parent=None):
        super().__init__(parent)
        self._hint = hint
        self.textChanged.connect(self._update_hint)
        self._update_hint()

    def _update_hint(self):
        empty = self.document().isEmpty() and not self.hasFocus()
        self.setPlaceholderText(self._hint if empty else "")
        self.viewport().update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._update_hint()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._update_hint()


class Worker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, task, parent=None):
        super().__init__(parent)
        self.task = task
        self.cancel_requested = False

    def run(self):
        try:
            self.completed.emit(self.task())
        except UserError as exc:
            self.failed.emit(str(exc))
        except Exception:
            self.failed.emit("Thao tác chưa hoàn tất. Kiểm tra dữ liệu và thử lại; chưa ghi đè file hiện có.")


class CustomerDialog(QDialog):
    def __init__(self, candidates, parent):
        super().__init__(parent)
        self.setWindowTitle("Chọn đúng đối tác")
        self.resize(670, 380)
        layout = QVBoxLayout(self)
        layout.addWidget(label("Cần xác nhận khách hàng", "SectionTitle"))
        layout.addWidget(label("Có tên trùng hoặc tên gần đúng. Chọn bản ghi cần dùng; người đại diện sẽ lấy từ bản ghi đó.", "Muted", True))
        self.list = QListWidget()
        self.list.setAccessibleName("Các khách hàng được tìm thấy")
        for candidate in candidates:
            c = candidate.customer
            self.list.addItem(f"{c.company_name}\nLiên hệ: {c.contact_name or 'Chưa có'}  |  MST: {c.tax_code or 'Chưa có'}\nĐại diện: {c.representative or 'Chưa có'}")
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Dùng khách hàng này")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        self.list.currentRowChanged.connect(lambda row: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(row >= 0))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MissingDialog(QDialog):
    def __init__(self, names, parent, labels=None):
        super().__init__(parent)
        self.field_labels = dict(labels or {})
        self.required_names = set(names)
        self.added_fields = {}
        self.setWindowTitle("Bổ sung thông tin hợp đồng")
        available = self.screen().availableGeometry()
        self.resize(min(700, available.width() - 50), min(available.height() - 70, max(500, 340 + len(names) * 60)))
        layout = QVBoxLayout(self)
        layout.addWidget(label("Cần thêm thông tin để điền mẫu", "SectionTitle"))
        layout.addWidget(label("Các giá trị này chỉ được dùng trên máy để điền hợp đồng. Ứng dụng không tự suy đoán dữ liệu bị thiếu.", "Muted", True))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("FormContent")
        form = QFormLayout(content)
        self.form = form
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.inputs = {}
        for name in names:
            field = QLineEdit()
            field.setAccessibleName(field_label(name, self.field_labels))
            field.setMaxLength(4000 if name in ("work_description", "payment_terms") else 1000)
            if name == "amount":
                field.setPlaceholderText("Ví dụ: 1 tỷ hoặc 1.000.000.000")
            form.addRow(label(field_label(name, self.field_labels), wrap=True), field)
            self.inputs[name] = field
        scroll.setWidget(content)
        layout.addWidget(scroll)
        self.add_information_button = button("+ Thêm thông tin", self.add_information)
        layout.addWidget(self.add_information_button)
        layout.addWidget(label("Thông tin thêm chưa có ô trong mẫu sẽ ghi vào mục Thông tin bổ sung cuối file Word. Các mục thêm có thể để trống nếu không dùng.", "Muted", True))
        self.error = label("", "Warning", True)
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Tạo hợp đồng")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def validate(self):
        for name, field in self.inputs.items():
            if name in self.required_names and not field.text().strip():
                self.error.setText("Cần điền: " + field_label(name, self.field_labels))
                self.error.show()
                field.setFocus()
                return
        self.accept()

    def values(self):
        result = {name: field.text().strip() for name, field in self.inputs.items() if name in self.required_names or field.text().strip()}
        added = {name: title for name, title in self.added_fields.items() if name in result}
        if added:
            result["__additional_fields__"] = added
        return result

    def add_information(self):
        choices = {field_label(name, self.field_labels): name for name in (FIELD_LABELS.keys() | self.field_labels.keys()) if name not in self.inputs and name != "amount_words"}
        name, accepted = QInputDialog.getItem(self, "Thêm thông tin hợp đồng", "Chọn một trường hoặc nhập tên thông tin mới:", sorted(choices), 0, True)
        if not accepted:
            return
        try:
            key = choices.get(name) or customer_field_key(name)
            if key in self.inputs:
                self.inputs[key].setFocus()
                return
            field = QLineEdit()
            field.setMaxLength(4000)
            field.setAccessibleName(name.strip())
            self.form.addRow(label(name.strip(), wrap=True), field)
            self.inputs[key] = field
            self.added_fields[key] = name.strip()
            self.field_labels[key] = name.strip()
            field.setFocus()
            self.error.hide()
        except UserError as exc:
            self.error.setText(str(exc))
            self.error.show()


class MainWindow(QMainWindow):
    job_progress = Signal(str)

    def __init__(self, store: Store | None = None, credentials: Credentials | None = None):
        super().__init__()
        self.store = store or Store()
        bootstrap(self.store)
        self.credentials = credentials or Credentials()
        self.service = ContractService(self.store)
        self.processing_cache = ProcessingCache(self.store.directory / "processing_cache")
        self.workers = []
        self.last_result = None
        self.messages = []
        self.setWindowTitle("Hợp Đồng — Trợ lý hợp đồng trên máy")
        self.resize(1260, 840)
        self.setMinimumSize(980, 680)
        self.setStyleSheet(STYLE)
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.build_sidebar())
        area = QWidget()
        main = QVBoxLayout(area)
        main.setContentsMargins(30, 25, 30, 15)
        main.setSpacing(18)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.title = label("Tạo hợp đồng", "Title")
        self.subtitle = label("", "Subtitle")
        self.subtitle.hide()
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        self.connection_badge = label("Chưa nhập API key", "Badge")
        header.addWidget(self.connection_badge, 0, Qt.AlignmentFlag.AlignTop)
        main.addLayout(header)
        self.demo_notice = label("Dữ liệu minh họa đang được sử dụng. Nhập danh sách khách hàng và mẫu Word của bạn trước khi tạo hợp đồng thực tế.", "Warning", True)
        main.addWidget(self.demo_notice)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.build_chat())
        self.pages.addWidget(self.build_customers())
        self.pages.addWidget(self.build_templates())
        self.pages.addWidget(self.build_history())
        self.pages.addWidget(self.build_settings())
        self.library_page = LibraryPage(self.store, self.run_job, self.job_progress.emit, self.job_cancelled, self)
        self.library_page.template_requested.connect(self.template_from_library)
        self.library_page.customer_requested.connect(self.customer_from_library)
        self.library_page.open_requested.connect(self.open_library_document)
        self.pages.addWidget(self.library_page)
        main.addWidget(self.pages, 1)
        layout.addWidget(area, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Sẵn sàng. Mẫu và dữ liệu khách hàng được xử lý trên máy.")
        self.job_progress.connect(self.statusBar().showMessage)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(160)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.cancel_job_button = button("Dừng tác vụ", self.cancel_job)
        self.cancel_job_button.hide()
        self.statusBar().addPermanentWidget(self.cancel_job_button)
        self.refresh()
        self.add_message("assistant", "Chào anh, em sẽ giúp điền mẫu hợp đồng từ danh sách khách hàng trên máy.\n\nNhập yêu cầu bên dưới, hoặc chọn “Chạy ví dụ” để thử tạo Word mà chưa cần API key.")
        self.shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self.shortcut.activated.connect(self.submit)

    def build_sidebar(self):
        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(218)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(18, 30, 18, 24)
        layout.setSpacing(8)
        layout.addWidget(label("Hợp Đồng", "Brand"))
        layout.addWidget(label("TRỢ LÝ TÀI LIỆU", "BrandSub"))
        layout.addSpacing(36)
        layout.addWidget(label("KHÔNG GIAN LÀM VIỆC", "NavCaption"))
        self.nav = QButtonGroup(self)
        for i, title in enumerate(["Tạo hợp đồng", "Khách hàng", "Mẫu hợp đồng", "Lịch sử", "Cài đặt", "Thư viện hồ sơ"]):
            btn = button(title)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked=False, index=i: self.navigate(index))
            self.nav.addButton(btn, i)
            layout.addWidget(btn)
        self.nav.button(0).setChecked(True)
        layout.addStretch()
        return side

    def build_chat(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        context = QHBoxLayout()
        context.addWidget(label("Mẫu sử dụng"))
        self.template_combo = QComboBox()
        self.template_combo.setAccessibleName("Chọn mẫu hợp đồng Word")
        self.template_combo.currentIndexChanged.connect(self.refresh_template_hint)
        context.addWidget(self.template_combo, 1)
        self.auto_template = QCheckBox("Tự chọn mẫu")
        self.auto_template.setAccessibleName("Tự chọn mẫu theo yêu cầu")
        self.auto_template.setToolTip("Tìm mẫu trên máy theo loại hợp đồng trong câu chat. Có nhiều mẫu phù hợp sẽ hỏi lại.")
        self.auto_template.toggled.connect(lambda checked: self.template_combo.setEnabled(not checked))
        self.auto_template.setChecked(True)
        context.addWidget(self.auto_template)
        context.addWidget(button("Quản lý mẫu", lambda: self.navigate(2)))
        layout.addLayout(context)
        split = QSplitter(Qt.Orientation.Horizontal)
        left, content = card()
        heading = QHBoxLayout()
        heading.addWidget(label("Trao đổi với trợ lý", "SectionTitle"))
        heading.addStretch()
        heading.addWidget(button("Cuộc trò chuyện mới", self.clear_chat))
        content.addLayout(heading)
        self.chat = QTextBrowser()
        self.chat.setAccessibleName("Nội dung trò chuyện")
        self.chat.setOpenExternalLinks(False)
        self.chat.setOpenLinks(False)
        content.addWidget(self.chat, 1)
        self.prompt = PromptEdit(PROMPT_HINT)
        self.prompt.setAccessibleName("Nhập yêu cầu tạo hợp đồng")
        self.prompt.setFixedHeight(105)
        self.prompt.textChanged.connect(self.update_count)
        content.addWidget(self.prompt)
        actions = QHBoxLayout()
        self.counter = label("Ctrl + Enter để tạo", "Muted")
        actions.addWidget(self.counter)
        actions.addStretch()
        self.demo_button = button("Chạy ví dụ", self.run_demo)
        self.submit_button = button("Tạo hợp đồng", self.submit, True)
        actions.addWidget(self.demo_button)
        actions.addWidget(self.submit_button)
        content.addLayout(actions)
        split.addWidget(left)
        right, info = card()
        right.setMinimumWidth(245)
        info.addWidget(label("Thông tin hợp đồng", "SectionTitle"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlainText("Thông tin sẽ xuất hiện sau khi xử lý yêu cầu.")
        self.preview.setAccessibleName("Thông tin hợp đồng vừa tạo")
        self.preview.setStyleSheet("QPlainTextEdit { border: none; background: transparent; padding: 0; color: #43566E; }")
        info.addWidget(self.preview, 1)
        info.addWidget(label("Cách hoạt động", "SectionTitle"))
        for text in ["1   Hiểu yêu cầu trong câu chat", "2   Tìm đúng bản ghi khách hàng", "3   Điền mẫu và lưu file Word"]:
            info.addWidget(label(text, "Muted", True))
        info.addSpacing(10)
        self.open_result = button("Mở file Word", self.open_last)
        self.open_result.setEnabled(False)
        info.addWidget(self.open_result)
        info.addWidget(button("Mở thư mục xuất", self.open_output))
        split.addWidget(right)
        split.setSizes([760, 280])
        layout.addWidget(split, 1)
        return page

    def build_customers(self):
        page, layout = card()
        actions = QHBoxLayout()
        self.customer_count = label("Danh sách khách hàng", "SectionTitle")
        actions.addWidget(self.customer_count, 1)
        self.import_customer_button = button("Nhập Excel", self.import_customers, True)
        self.import_contract_button = button("Nhập hợp đồng", self.import_customer_contract, True)
        actions.addWidget(button("Tải Excel mẫu", self.save_sample_excel))
        actions.addWidget(self.import_customer_button)
        actions.addWidget(self.import_contract_button)
        layout.addLayout(actions)
        edit_actions = QHBoxLayout()
        self.add_customer_button = button("Thêm khách hàng", self.add_customer)
        self.edit_customer_button = button("Xem / sửa thông tin", self.edit_customer)
        edit_actions.addWidget(self.add_customer_button)
        edit_actions.addWidget(self.edit_customer_button)
        edit_actions.addStretch()
        layout.addLayout(edit_actions)
        self.customer_source = label("", "Muted", True)
        layout.addWidget(self.customer_source)
        self.customer_table = self.make_table(["Người liên hệ", "Công ty", "Mã số thuế", "Người đại diện", "Địa chỉ"])
        self.customer_table.setAccessibleName("Khách hàng và các trường thông tin bổ sung")
        self.customer_table.cellDoubleClicked.connect(lambda *_: self.edit_customer())
        layout.addWidget(self.customer_table, 1)
        layout.addWidget(label("Excel có thể thêm cột theo hồ sơ; thông tin không bắt buộc có thể để trống. Nhấp đúp khách hàng để xem, sửa hoặc thêm trường. Nhập hợp đồng dùng Gemini đọc file đã chọn và có bước kiểm tra trước khi lưu.", "Muted", True))
        return page

    def build_templates(self):
        page, layout = card()
        actions = QHBoxLayout()
        actions.addWidget(label("Mẫu Word của bạn", "SectionTitle"), 1)
        actions.addWidget(button("Mở thư mục mẫu", lambda: self.open_path(self.store.templates)))
        self.import_template_button = button("Nhập mẫu có biến", self.import_template)
        self.build_template_button = button("Tạo mẫu từ Word/PDF", self.prepare_template, True)
        layout.addLayout(actions)
        imports = QHBoxLayout()
        imports.addStretch()
        imports.addWidget(self.import_template_button)
        imports.addWidget(self.build_template_button)
        layout.addLayout(imports)
        layout.addWidget(label("Chọn Word/PDF trống chưa có biến hoặc hợp đồng đã điền để tạo mẫu tái sử dụng. Kiểm tra các vùng tự điền rồi lưu; file gốc được giữ nguyên. Mẫu đã có biến có thể nhập trực tiếp.", "Muted", True))
        self.template_list = QListWidget()
        self.template_list.setAccessibleName("Danh sách mẫu Word")
        self.template_list.currentRowChanged.connect(self.show_template)
        layout.addWidget(self.template_list)
        self.template_details = QPlainTextEdit()
        self.template_details.setReadOnly(True)
        self.template_details.setAccessibleName("Các biến và nội dung mẫu")
        layout.addWidget(self.template_details, 1)
        layout.addWidget(label("Word được giữ định dạng chữ và bảng. PDF được dựng lại thành Word chỉnh sửa được, cần đối chiếu nội dung và bố cục. Ảnh dấu/chữ ký được bỏ khỏi mẫu mới.", "Muted", True))
        return page

    def build_history(self):
        page, layout = card()
        row = QHBoxLayout()
        row.addWidget(label("Các hợp đồng đã tạo", "SectionTitle"), 1)
        row.addWidget(button("Mở file được chọn", self.open_history))
        layout.addLayout(row)
        self.history_table = self.make_table(["Thời điểm", "Khách hàng", "Giá trị (VND)", "Loại dữ liệu", "Tên file"])
        self.history_table.doubleClicked.connect(self.open_history)
        layout.addWidget(self.history_table, 1)
        layout.addWidget(label("Mỗi lần tạo dùng tên file riêng. Ứng dụng không ghi đè hợp đồng cũ.", "Muted"))
        return page

    def build_settings(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 5, 0)
        api, content = card()
        content.addWidget(label("Kết nối Gemini", "SectionTitle"))
        form = QFormLayout()
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setAccessibleName("Gemini API key")
        self.key_input.setPlaceholderText("Dán API key từ Google AI Studio")
        self.model_input = QLineEdit(DEFAULT_MODEL)
        self.model_input.setAccessibleName("Gemini model ID")
        form.addRow("API key", self.key_input)
        form.addRow("Model ID", self.model_input)
        content.addLayout(form)
        self.remember_key = QCheckBox("Ghi nhớ API key trong kho thông tin xác thực của Windows")
        self.remember_key.setChecked(True)
        content.addWidget(self.remember_key)
        self.key_status = label("", "Muted", True)
        content.addWidget(self.key_status)
        self.test_api_button = button("Kiểm tra kết nối", self.test_connection)
        row = QHBoxLayout()
        row.addWidget(button("Lưu kết nối", self.save_connection, True))
        row.addWidget(self.test_api_button)
        row.addWidget(button("Xóa key đã lưu", self.forget_key))
        row.addStretch()
        content.addLayout(row)
        content.addWidget(label("Key không được ghi vào mã nguồn hoặc settings.json. Model không tự đổi khi hết quota. Nội dung chat đi qua API; đây không phải chế độ offline.", "Muted", True))
        layout.addWidget(api)
        output, content = card()
        content.addWidget(label("Nơi lưu hợp đồng", "SectionTitle"))
        self.output_input = QLineEdit()
        self.output_input.setAccessibleName("Thư mục xuất hợp đồng")
        self.output_input.setPlaceholderText("Để trống để dùng Desktop thực tế của Windows")
        row = QHBoxLayout()
        row.addWidget(self.output_input, 1)
        row.addWidget(button("Chọn thư mục", self.choose_output))
        content.addLayout(row)
        self.output_hint = label("", "Muted", True)
        content.addWidget(self.output_hint)
        layout.addWidget(output)
        seller, content = card()
        content.addWidget(label("Thông tin công ty của bạn", "SectionTitle"))
        form = QFormLayout()
        self.seller_inputs = {}
        for key in ("seller_company", "seller_tax_code", "seller_address", "seller_representative", "seller_position",
                    "seller_contact_name", "seller_phone", "seller_email", "seller_bank_account", "seller_bank_name"):
            field = QLineEdit()
            field.setAccessibleName(FIELD_LABELS[key])
            self.seller_inputs[key] = field
            form.addRow(FIELD_LABELS[key], field)
        content.addLayout(form)
        layout.addWidget(seller)
        layout.addWidget(button("Lưu cài đặt tài liệu", self.save_document_settings, True))
        layout.addWidget(button("Mở thư mục dữ liệu ứng dụng", lambda: self.open_path(self.store.directory)))
        layout.addStretch()
        scroll.setWidget(page)
        return scroll

    @staticmethod
    def make_table(headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(44)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        return table

    def navigate(self, index):
        titles = [("Tạo hợp đồng", ""), ("Khách hàng", ""), ("Mẫu hợp đồng", "Quản lý các mẫu Word được dùng để điền dữ liệu."), ("Lịch sử", "Tìm và mở lại hợp đồng đã tạo."), ("Cài đặt", "Kết nối AI, thông tin công ty và nơi lưu tài liệu."), ("Thư viện hồ sơ", "Tìm, mở và chuẩn bị mẫu từ bộ hồ sơ có sẵn.")]
        self.pages.setCurrentIndex(index)
        self.nav.button(index).setChecked(True)
        self.title.setText(titles[index][0])
        self.subtitle.setText(titles[index][1])
        self.subtitle.setVisible(bool(titles[index][1]))

    def refresh(self):
        cfg = self.store.config()
        customers = self.store.customers()
        self.demo_notice.setVisible(bool(cfg.get("demo_data")))
        self.connection_badge.setText("Đã có API key" if self.credentials.get() else "Chưa nhập API key")
        self.key_status.setText("Đã có key. Có thể bấm Kiểm tra kết nối để xác minh model." if self.credentials.get() else "Chưa có key; anh vẫn có thể dùng Chạy ví dụ để thử luồng Word.")
        self.model_input.setText(cfg["model"])
        self.output_input.setText(cfg.get("output_directory", ""))
        try:
            self.output_hint.setText("Desktop Windows: " + str(desktop_directory()) + ". Nếu thư mục thuộc OneDrive, file có thể được OneDrive đồng bộ.")
        except UserError as exc:
            self.output_hint.setText(str(exc))
        for name, field in self.seller_inputs.items():
            field.setText(cfg.get("seller", {}).get(name, ""))
        self.customer_count.setText(f"{len(customers)} khách hàng" + (" · Minh họa" if cfg.get("demo_data") else ""))
        contract_count = len(self.store.contract_customers())
        source_text = "Excel: " + (cfg.get("customer_source") or "Chưa nhập")
        if contract_count:
            source_text += f"\nTừ hợp đồng / nhập tay đã xác nhận: {contract_count} khách hàng"
        self.customer_source.setText(source_text)
        self.customer_rows = customers
        custom_labels = self.store.customer_field_labels()
        core = ["contact_name", "company_name", "tax_code", "representative", "address"]
        more = [name for name in CUSTOMER_BASE_FIELDS if name not in core and any(getattr(customer, name) for customer in customers)]
        names = core + more + sorted(custom_labels, key=lambda key: custom_labels[key])
        self.customer_table.setColumnCount(len(names))
        self.customer_table.setHorizontalHeaderLabels([field_label(name, custom_labels) if name != "company_name" else "Công ty" for name in names])
        self.customer_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.customer_table.horizontalHeader().setStretchLastSection(False)
        for column, name in enumerate(names):
            self.customer_table.setColumnWidth(column, 260 if name in ("company_name", "address") else 180)
        self.customer_table.setRowCount(len(customers))
        for row, customer in enumerate(customers):
            extras = extra_context(customer)
            for col, name in enumerate(names):
                value = extras.get(name, "") if name in custom_labels else getattr(customer, name)
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                item.setData(Qt.ItemDataRole.UserRole, customer.id)
                self.customer_table.setItem(row, col, item)
        selected = self.template_combo.currentData()
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_list.clear()
        for path in sorted(self.store.templates.glob("*.docx")):
            metadata = template_metadata(path)
            self.template_combo.addItem(metadata.get("title") or path.stem, str(path))
            self.template_list.addItem(path.name)
        if selected:
            index = self.template_combo.findData(selected)
            self.template_combo.setCurrentIndex(max(0, index))
        self.template_combo.blockSignals(False)
        self.refresh_template_hint()
        if self.template_list.count():
            self.template_list.setCurrentRow(0)
        self.history_rows = self.store.history()
        self.history_table.setRowCount(len(self.history_rows))
        for row, item in enumerate(self.history_rows):
            values = [item["created"].replace("T", " "), item["company"], format_money(item["amount"]) if item["amount"] else "Theo đơn hàng", "Bản thử" if item["demo"] else "Khách hàng", Path(item["path"]).name]
            for col, value in enumerate(values):
                self.history_table.setItem(row, col, QTableWidgetItem(value))

    def refresh_template_hint(self):
        if self.template_combo.currentData():
            self.template_combo.setToolTip(self.template_combo.currentData())

    def update_count(self):
        count = len(self.prompt.toPlainText())
        self.counter.setText(f"{count:,}/6.000 ký tự" if count else "Ctrl + Enter để tạo")
        self.counter.setToolTip("Nhấn Ctrl + Enter để tạo hợp đồng")

    def add_message(self, role, text):
        self.messages.append((role, text))
        blocks = []
        for kind, message in self.messages:
            heading = "BẠN" if kind == "user" else "TRỢ LÝ" if kind == "assistant" else "CẦN KIỂM TRA"
            color = "#1D4ED8" if kind == "user" else "#9A3412" if kind == "error" else "#43566E"
            background = "#EDF3FF" if kind == "user" else "#FFF7ED" if kind == "error" else "#F4F7FB"
            escaped = html.escape(message).replace("\n", "<br>")
            blocks.append(f'<table width="100%" cellspacing="0" cellpadding="13" style="background-color:{background};margin-bottom:14px"><tr><td><span style="color:{color};font-size:10px;font-weight:600">{heading}</span><br><span style="font-size:13px;line-height:1.6;color:#17243B">{escaped}</span></td></tr></table><br>')
        self.chat.setHtml("".join(blocks))
        self.chat.moveCursor(QTextCursor.MoveOperation.End)

    def clear_chat(self):
        self.messages.clear()
        self.chat.clear()
        self.prompt.clear()
        self.add_message("assistant", "Nhập khách hàng, số tiền và nội dung công việc để tạo hợp đồng mới.")

    def show_error(self, message):
        self.statusBar().showMessage(message)
        if self.pages.currentIndex() == 0:
            self.add_message("error", message)
        else:
            QMessageBox.warning(self, "Cần kiểm tra", message)

    def busy(self, active, message="Đang xử lý…"):
        for control in [self.submit_button, self.demo_button, self.import_customer_button, self.import_contract_button, self.test_api_button,
                        self.build_template_button, self.import_template_button, self.add_customer_button, self.edit_customer_button]:
            control.setEnabled(not active)
        self.library_page.set_busy(active)
        self.progress.setVisible(active)
        self.cancel_job_button.setVisible(active)
        self.cancel_job_button.setEnabled(active)
        self.statusBar().showMessage(message if active else "Sẵn sàng.")

    @staticmethod
    def job_cancelled():
        thread = QThread.currentThread()
        return getattr(thread, "cancel_requested", False) or thread.isInterruptionRequested()

    def cancel_job(self):
        for worker in self.workers:
            worker.cancel_requested = True
            worker.requestInterruption()
        self.cancel_job_button.setEnabled(False)
        self.statusBar().showMessage("Sẽ dừng sau bước đọc đang chạy. Các hồ sơ đã lập danh mục được giữ lại.")

    def run_job(self, task, callback, message):
        if self.workers:
            return
        self.busy(True, message)
        worker = Worker(task, self)
        self.workers.append(worker)
        outcome = {}
        worker.completed.connect(lambda value: outcome.update(value=value))
        worker.failed.connect(lambda error: outcome.update(error=error))
        def finished():
            cancelled = worker.cancel_requested or worker.isInterruptionRequested()
            self.workers.remove(worker)
            self.busy(False)
            worker.deleteLater()
            # Release the finished worker before opening a review dialog or
            # starting the next stage (ZIP download -> AI -> review).
            if cancelled:
                if "value" in outcome and hasattr(outcome["value"], "cancelled"):
                    outcome["value"].cancelled = True
                    callback(outcome["value"])
                else:
                    self.statusBar().showMessage("Đã dừng tác vụ. Chưa lưu mẫu/khách hàng hoặc tạo hợp đồng mới.")
            elif "error" in outcome:
                self.show_error(outcome["error"])
            elif "value" in outcome:
                callback(outcome["value"])
        worker.finished.connect(finished)
        worker.start()

    def submit(self):
        if self.workers:
            return
        text = self.prompt.toPlainText().strip()
        template = self.template_combo.currentData()
        if not text:
            self.prompt.setFocus()
            return
        if not template:
            self.show_error("Chưa chọn mẫu. Mở Mẫu hợp đồng để thêm file .docx.")
            return
        if self.auto_template.isChecked():
            matches = rank_templates(text, sorted(self.store.templates.glob("*.docx")))
            chosen = confident_template(matches)
            if chosen is None and matches:
                dialog = TemplateChoiceDialog(matches, template, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                chosen = dialog.selected_path()
            if chosen:
                template = str(chosen)
                self.template_combo.setCurrentIndex(self.template_combo.findData(template))
        try:
            extractor = GeminiExtractor(self.credentials.get(), self.store.config()["model"], cache=self.processing_cache)
        except UserError as exc:
            self.show_error(str(exc))
            self.navigate(4)
            self.key_input.setFocus()
            return
        self.add_message("user", text)
        self.run_job(lambda: extractor.extract(text), lambda intent: self.handle_intent(intent, text, Path(template)), "Gemini đang đọc yêu cầu; chưa gửi danh sách khách hàng hoặc mẫu Word…")

    def run_demo(self):
        if self.workers:
            return
        if not self.store.config().get("demo_data"):
            self.show_error("Chạy ví dụ dành cho danh sách minh họa. Anh đang dùng dữ liệu khách hàng; hãy nhập yêu cầu và dùng Gemini.")
            return
        sample = self.store.templates / "Mau-thi-cong-minh-hoa.docx"
        if not sample.exists():
            self.show_error("Không tìm được mẫu minh họa đi kèm.")
            return
        self.prompt.setPlainText(DEMO_PROMPT)
        self.add_message("user", DEMO_PROMPT)
        self.add_message("assistant", "Đang chạy ví dụ minh họa đã chuẩn bị sẵn, không gọi Gemini và không tính phí API.")
        intent = Intent(contact_name="Thông", company_name="Công ty X", amount_text="1 tỷ", work_description="Thi công dự án Y", currency="VND")
        self.handle_intent(intent, DEMO_PROMPT, sample, True)

    def handle_intent(self, intent, prompt, template, demo=False):
        try:
            pending = self.service.prepare(intent, prompt, template, demo)
            if pending.customer is None:
                dialog = CustomerDialog(pending.candidates, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    self.add_message("assistant", "Đã dừng theo lựa chọn của anh. Chưa tạo file.")
                    return
                pending.customer = pending.candidates[dialog.list.currentRow()].customer
            extra = {}
            missing = self.service.missing(pending)
            if missing:
                # amount_words is derived; ask for amount once instead.
                missing = [name for name in missing if name not in ("amount_words", "day", "month", "year")]
                labels = self.store.customer_field_labels() | template_metadata(template).get("field_labels", {})
                dialog = MissingDialog(missing, self, labels)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    self.add_message("assistant", "Chưa đủ thông tin nên chưa tạo hợp đồng. Anh có thể bổ sung trong câu yêu cầu tiếp theo.")
                    return
                extra = dialog.values()
            self.statusBar().showMessage("Đang điền mẫu Word và lưu file…")
            result = self.service.generate(pending, extra)
            self.generated(result)
        except UserError as exc:
            self.show_error(str(exc))
        except Exception:
            self.show_error("Chưa hoàn tất tạo hợp đồng. Kiểm tra mẫu và dữ liệu đầu vào.")

    def generated(self, result: ContractResult):
        self.last_result = result
        self.open_result.setEnabled(True)
        amount_text = format_money(result.amount) + " đồng" if result.amount else "Theo từng đơn hàng; không có tổng cố định"
        self.preview.setPlainText(f"{'BẢN THỬ / MẪU NHÁP' + chr(10) + chr(10) if result.demo else ''}{result.customer.company_name}\n\nNgười liên hệ\n{result.customer.contact_name or 'Chưa cung cấp'}\n\nNgười đại diện\n{result.customer.representative or 'Đã bổ sung khi tạo'}\n\nGiá trị\n{amount_text}\n\nCông việc\n{result.work}\n\nMẫu\n{result.template_name}")
        self.add_message("assistant", f"Đã tạo {'bản thử' if result.demo else 'hợp đồng'} thành công.\n\nKhách hàng: {result.customer.company_name}\nGiá trị: {amount_text}\n\nFile: {result.path}\n\nBấm “Mở file Word” để xem tài liệu.")
        self.refresh()
        self.statusBar().showMessage("Đã lưu: " + str(result.path))

    def import_customers(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn danh sách khách hàng", "", "Excel (*.xlsx)")
        if not path:
            return
        def imported(customers):
            self.store.replace_excel_customers(customers, path)
            cfg = self.store.config()
            cfg.update(customer_source=path, source_signature=None, demo_data=False)
            # Remove fictional seller fields instead of carrying them into real contracts.
            cfg["seller"] = {k: v for k, v in cfg.get("seller", {}).items() if "minh họa" not in v.lower() and not v.startswith("DEMO-")}
            self.store.save_config(cfg)
            self.refresh()
            QMessageBox.information(self, "Đã nhập danh sách", f"Đã kiểm tra và nhập {len(customers)} khách hàng. File Excel gốc được giữ nguyên.\n\nHãy kiểm tra thông tin công ty của bạn trong Cài đặt.")
        self.run_job(lambda: read_customers(Path(path)), imported, "Đang kiểm tra và đọc danh sách khách hàng…")

    def add_customer(self):
        if self.workers:
            return
        dialog = CustomerEditor(self.store, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.statusBar().showMessage("Đã thêm khách hàng.")

    def edit_customer(self):
        if self.workers:
            return
        row = self.customer_table.currentRow()
        if row < 0 or row >= len(self.customer_rows):
            self.statusBar().showMessage("Chọn một khách hàng trong bảng trước khi xem hoặc sửa.")
            return
        dialog = CustomerEditor(self.store, self.customer_rows[row], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()
            self.statusBar().showMessage("Đã lưu thông tin và các trường bổ sung của khách hàng.")

    def import_customer_contract(self):
        try:
            extractor = GeminiDocumentExtractor(self.credentials.get(), self.store.config()["model"], cache=self.processing_cache)
        except UserError as exc:
            self.show_error(str(exc))
            self.navigate(4)
            self.key_input.setFocus()
            return
        path, _ = QFileDialog.getOpenFileName(self, "Chọn hợp đồng để lấy thông tin khách hàng", "", "Hợp đồng PDF hoặc Word (*.pdf *.docx)")
        if path:
            self.run_job(lambda: extractor.extract_file(Path(path), self.job_progress.emit, self.job_cancelled), self.review_customer_import, "Đang đọc hợp đồng được chọn…")

    def review_customer_import(self, result):
        dialog = CustomerImportReview(self.store, result, self)
        answer = dialog.exec()
        if dialog.retry_with_vision:
            extractor = GeminiDocumentExtractor(self.credentials.get(), self.store.config()["model"], cache=self.processing_cache)
            self.run_job(lambda: extractor.extract_file(result.document.path, cancelled=self.job_cancelled, force_refresh=True),
                         self.review_customer_import, "Đang dùng Gemini đối chiếu PDF gốc…")
            return
        if answer == QDialog.DialogCode.Accepted:
            self.refresh()
            saved = dialog.saved_customer
            for row, customer in enumerate(self.store.customers()):
                if customer.id == saved.id:
                    self.customer_table.selectRow(row)
                    break
            self.statusBar().showMessage("Đã lưu khách hàng: " + saved.company_name + ". Có thể chuyển sang Tạo hợp đồng để sử dụng.")
        else:
            self.statusBar().showMessage("Đã hủy. Chưa lưu thêm hoặc cập nhật khách hàng.")

    def save_sample_excel(self):
        path, _ = QFileDialog.getSaveFileName(self, "Lưu Excel mẫu", "Khach-hang-mau.xlsx", "Excel (*.xlsx)")
        if path:
            try:
                shutil.copy2(resource_path("Khach-hang-minh-hoa.xlsx"), path)
                self.statusBar().showMessage("Đã lưu Excel mẫu. Thay các dòng minh họa bằng khách hàng thực tế trước khi nhập.")
            except OSError:
                self.show_error("Không lưu được Excel mẫu vào vị trí đã chọn.")

    def import_template(self):
        source, _ = QFileDialog.getOpenFileName(self, "Chọn mẫu Word hoặc hợp đồng có sẵn", "", "Word/PDF (*.docx *.pdf)")
        if not source:
            return
        try:
            path = Path(source)
            if path.suffix.lower() == ".pdf":
                self.start_prepare_template(path)
                return
            names = template_fields(path)
            if not names:
                self.start_prepare_template(path)
                return
            destination = self.store.templates / path.name
            if destination.exists():
                destination = self.store.templates / f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}"
            shutil.copy2(path, destination)
            self.refresh()
            self.template_combo.setCurrentIndex(self.template_combo.findData(str(destination)))
            self.statusBar().showMessage("Đã thêm mẫu: " + path.name)
        except UserError as exc:
            self.show_error(str(exc))
        except OSError:
            self.show_error("Không sao chép được mẫu Word; kiểm tra quyền truy cập thư mục.")

    def prepare_template(self):
        source, _ = QFileDialog.getOpenFileName(self, "Chọn hợp đồng để tạo mẫu tái sử dụng", "", "Word/PDF (*.docx *.pdf)")
        if source:
            self.start_prepare_template(Path(source))

    def start_prepare_template(self, path, library_id=None):
        if self.workers:
            return
        try:
            builder = GeminiTemplateBuilder(self.credentials.get(), self.store.config()["model"], cache=self.processing_cache,
                                            customer_fields=self.store.customer_field_labels())
        except UserError as exc:
            self.show_error(str(exc))
            self.navigate(4)
            self.key_input.setFocus()
            return
        dialog = TemplateSourceDialog(path, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        role = dialog.role.currentText()
        force_refresh = dialog.vision.isChecked()
        self.run_job(lambda: builder.prepare(path, role, self.job_progress.emit, self.job_cancelled, force_refresh),
                     lambda draft: self.review_template(draft, library_id), "Đang chuẩn bị mẫu từ hồ sơ được chọn…")

    def review_template(self, draft, library_id=None):
        dialog = TemplateReview(self.store, draft, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.statusBar().showMessage("Đã hủy. Chưa lưu mẫu hoặc thay đổi dữ liệu khách hàng.")
            return
        if library_id is not None:
            self.library_page.library.attach_template(library_id, draft, dialog.saved_path)
            self.library_page.refresh()
        self.refresh()
        self.template_combo.setCurrentIndex(self.template_combo.findData(str(dialog.saved_path)))
        self.navigate(2)
        self.statusBar().showMessage("Đã lưu mẫu tái sử dụng: " + dialog.saved_path.name)

    def template_from_library(self, identity):
        self.run_job(lambda: self.library_page.library.materialize(identity, self.job_progress.emit),
                     lambda path: self.start_prepare_template(path, identity), "Đang lấy hồ sơ để chuẩn bị mẫu…")

    def customer_from_library(self, identity):
        def read_customer(path):
            try:
                extractor = GeminiDocumentExtractor(self.credentials.get(), self.store.config()["model"], cache=self.processing_cache)
            except UserError as exc:
                self.show_error(str(exc))
                return
            self.run_job(lambda: extractor.extract_file(path, self.job_progress.emit, self.job_cancelled), self.review_customer_import,
                         "Đang gửi hồ sơ được chọn đến Gemini để đọc thông tin khách hàng…")
        self.run_job(lambda: self.library_page.library.materialize(identity, self.job_progress.emit),
                     read_customer, "Đang lấy hồ sơ được chọn…")

    def open_library_document(self, identity):
        self.run_job(lambda: self.library_page.library.materialize(identity, self.job_progress.emit),
                     self.open_path, "Đang lấy hồ sơ được chọn…")

    def show_template(self, row):
        if row < 0:
            return
        item = self.template_list.item(row)
        if not item:
            return
        path = self.store.templates / item.text()
        try:
            names = template_fields(path)
            metadata = template_metadata(path)
            detail = ""
            if metadata:
                detail = (metadata.get("title", "") + "\n" + metadata.get("summary", "") + "\nNguồn: " + metadata.get("source_name", "")
                          + "\nĐối tác cần thay: " + metadata.get("customer_role", "")
                          + ("\nTrạng thái: Mẫu nháp" if metadata.get("is_draft") else "\nTrạng thái: Đã kiểm tra") + "\n\n")
            labels = self.store.customer_field_labels() | template_metadata(path).get("field_labels", {})
            self.template_details.setPlainText(detail + "CÁC TRƯỜNG TỰ ĐIỀN\n" + ", ".join(field_label(name, labels) for name in sorted(names)) + "\n\nNỘI DUNG VĂN BẢN (không thể hiện định dạng Word)\n\n" + document_text(path)[:18000])
        except UserError as exc:
            self.template_details.setPlainText(str(exc))

    def save_connection(self):
        try:
            model = self.model_input.text().strip()
            key = self.key_input.text().strip()
            if not key:
                key = self.credentials.get()
            GeminiExtractor(key, model)
            self.credentials.set(key, self.remember_key.isChecked())
            cfg = self.store.config()
            cfg["model"] = model
            self.store.save_config(cfg)
            self.key_input.clear()
            self.refresh()
            self.statusBar().showMessage("Đã lưu kết nối. Chưa xác minh key; bấm Kiểm tra kết nối để kiểm tra.")
        except UserError as exc:
            self.show_error(str(exc))

    def test_connection(self):
        key = self.key_input.text().strip() or self.credentials.get()
        try:
            extractor = GeminiExtractor(key, self.model_input.text().strip())
        except UserError as exc:
            self.show_error(str(exc))
            return
        def tested(_):
            self.key_status.setText("Kết nối thành công với " + extractor.model + ". Lưu kết nối nếu anh vừa thay key hoặc model.")
            self.connection_badge.setText("Gemini đã phản hồi")
        self.run_job(lambda: extractor.extract("Tạo hợp đồng với công ty minh họa, số tiền 1 đồng, nội dung kiểm tra kết nối."), tested, "Đang gửi yêu cầu nhỏ để kiểm tra Gemini…")

    def forget_key(self):
        try:
            self.credentials.forget()
            self.key_input.clear()
            self.refresh()
            self.statusBar().showMessage("Đã xóa key do ứng dụng lưu. Biến môi trường GEMINI_API_KEY, nếu có, vẫn thuộc cấu hình máy.")
        except UserError as exc:
            self.show_error(str(exc))

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất hợp đồng")
        if path:
            self.output_input.setText(path)

    def save_document_settings(self):
        cfg = self.store.config()
        cfg["output_directory"] = self.output_input.text().strip()
        if cfg["output_directory"] and not Path(cfg["output_directory"]).is_absolute():
            self.show_error("Thư mục xuất cần là đường dẫn đầy đủ, ví dụ C:\\Users\\Ten\\Desktop.")
            return
        cfg["seller"] = {key: field.text().strip() for key, field in self.seller_inputs.items()}
        try:
            self.store.save_config(cfg)
            self.statusBar().showMessage("Đã lưu thông tin công ty và thư mục xuất.")
        except (OSError, UserError):
            self.show_error("Không lưu được cài đặt. Kiểm tra thư mục dữ liệu ứng dụng.")

    def open_path(self, path):
        path = Path(path)
        if not path.exists():
            self.show_error("Không tìm thấy file hoặc thư mục. File có thể đã được di chuyển hoặc đổi tên.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            self.show_error("Windows chưa mở được file. Kiểm tra ứng dụng Word hoặc mở trực tiếp bằng File Explorer.")

    def open_last(self):
        if self.last_result:
            self.open_path(self.last_result.path)

    def open_output(self):
        try:
            configured = self.store.config().get("output_directory")
            self.open_path(Path(configured) if configured else desktop_directory())
        except UserError as exc:
            self.show_error(str(exc))

    def open_history(self):
        row = self.history_table.currentRow()
        if row >= 0:
            self.open_path(Path(self.history_rows[row]["path"]))

    def closeEvent(self, event):
        if self.workers:
            self.statusBar().showMessage("Yêu cầu đang xử lý. Anh có thể đóng ứng dụng sau khi hoàn tất hoặc hết thời gian kết nối.")
            event.ignore()
        else:
            super().closeEvent(event)
