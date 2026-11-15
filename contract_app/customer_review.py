from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHeaderView, QInputDialog, QLabel, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .contract_import import ImportResult, save_imported_customer, validate_import_customer
from .models import Customer, FIELD_LABELS, UserError
from .customer_fields import CUSTOMER_BASE_FIELDS, clean_extra_fields, customer_field_key, extra_context

CUSTOMER_FIELDS = list(CUSTOMER_BASE_FIELDS)
LABELS = FIELD_LABELS | {"aliases": "Tên gọi ngắn / bí danh"}


def plain_label(text, wrap=True):
    item = QLabel(text)
    item.setTextFormat(Qt.TextFormat.PlainText)
    item.setWordWrap(wrap)
    return item


class CustomerImportReview(QDialog):
    def __init__(self, store, result: ImportResult, parent=None):
        super().__init__(parent)
        self.store, self.result = store, result
        self.saved_customer = None
        self.field_names = list(CUSTOMER_FIELDS)
        self.extra_labels = {}
        self.retry_with_vision = False
        self.setWindowTitle("Kiểm tra khách hàng từ hợp đồng")
        screen = self.screen().availableGeometry()
        self.resize(min(920, screen.width() - 60), min(790, screen.height() - 80))
        layout = QVBoxLayout(self)
        title = plain_label("Chọn công ty và kiểm tra trước khi lưu")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        if result.processing_note:
            layout.addWidget(plain_label(result.processing_note))
        layout.addWidget(plain_label("Sửa thông tin ở cột bên phải nếu cần. Ô trống sẽ giữ thông tin đã có; người liên hệ không tự lấy từ người đại diện."))
        self.party_selector = QComboBox()
        self.party_selector.setAccessibleName("Chọn công ty trong hợp đồng")
        self.party_selector.setPlaceholderText("Chọn Bên A hoặc Bên B cần lưu…")
        for party in result.extraction.parties:
            self.party_selector.addItem(f"{party.role} — {party.company_name}")
        self.party_selector.setCurrentIndex(-1)
        layout.addWidget(self.party_selector)
        self.table = QTableWidget(len(CUSTOMER_FIELDS), 3)
        self.table.setAccessibleName("Đối chiếu và sửa thông tin khách hàng")
        self.table.setHorizontalHeaderLabels(["Thông tin", "Đã lưu", "Từ hợp đồng — có thể sửa"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(42)
        for row, name in enumerate(CUSTOMER_FIELDS):
            for column, value in enumerate([LABELS.get(name, name), "", ""]):
                item = QTableWidgetItem(value)
                if column != 2:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        layout.addWidget(self.table, 1)
        add_field = QPushButton("+ Thêm trường thông tin")
        add_field.clicked.connect(self.add_extra)
        layout.addWidget(add_field)
        self.target = QComboBox()
        self.target.setAccessibleName("Bản ghi khách hàng sẽ được lưu hoặc cập nhật")
        layout.addWidget(self.target)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setAccessibleName("Trích dẫn và điểm cần đối chiếu từ hợp đồng")
        self.notes.setMaximumHeight(115)
        layout.addWidget(self.notes)
        open_source = QPushButton("Mở hợp đồng gốc để đối chiếu")
        open_source.clicked.connect(self.open_source)
        layout.addWidget(open_source)
        if result.document.path.suffix.lower() == ".pdf":
            retry = QPushButton("Đọc lại PDF gốc bằng Gemini")
            retry.setToolTip("Đọc lại khi thông tin các bên chưa đúng; thao tác này gửi PDF gốc qua API.")
            retry.clicked.connect(self.retry_source)
            layout.addWidget(retry)
        self.error = plain_label("")
        self.error.setObjectName("Warning")
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText("Lưu khách hàng")
        self.save_button.setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.save_customer)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.party_selector.currentIndexChanged.connect(self.choose_party)
        self.table.itemChanged.connect(self.edited)
        self.target.currentIndexChanged.connect(self.show_previous)
        self.table.setEnabled(False)
        if len(result.extraction.parties) == 1:
            self.party_selector.setCurrentIndex(0)

    def customer_value(self):
        values = {name: self.table.item(row, 2).text().strip() for row, name in enumerate(self.field_names)}
        extras = clean_extra_fields({self.extra_labels[name]: values.pop(name) for name in self.extra_labels})
        return Customer(id=0, extra_fields=extras, **values)

    def append_extra(self, label, value=""):
        key = customer_field_key(label)
        if key in self.field_names:
            return self.field_names.index(key)
        row = self.table.rowCount()
        self.field_names.append(key)
        self.extra_labels[key] = label
        self.table.insertRow(row)
        for col, text in enumerate((label, "", value)):
            item = QTableWidgetItem(text)
            if col != 2:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, col, item)
        return row

    def add_extra(self):
        if self.party_selector.currentIndex() < 0:
            return
        name, accepted = QInputDialog.getText(self, "Thêm trường khách hàng", "Tên thông tin, ví dụ Số CCCD hoặc Email kế toán:")
        if accepted:
            try:
                customer_field_key(name)
                self.table.blockSignals(True)
                row = self.append_extra(name.strip())
                self.table.blockSignals(False)
                self.table.setCurrentCell(row, 2)
                self.table.editItem(self.table.item(row, 2))
            except UserError as exc:
                self.error.setText(str(exc))
                self.error.show()

    def retry_source(self):
        self.retry_with_vision = True
        self.reject()

    def choose_party(self, index):
        self.error.hide()
        if index < 0:
            return
        party = self.result.extraction.parties[index]
        customer = party.customer()
        self.table.blockSignals(True)
        self.table.setRowCount(len(CUSTOMER_FIELDS))
        self.field_names = list(CUSTOMER_FIELDS)
        self.extra_labels = {}
        for row, name in enumerate(CUSTOMER_FIELDS):
            value = getattr(customer, name)
            self.table.item(row, 2).setText(value)
            self.table.item(row, 2).setToolTip(value)
        for label, value in customer.extra_fields.items():
            self.append_extra(label, value)
        self.table.blockSignals(False)
        self.table.setEnabled(True)
        notes = list(self.result.extraction.warnings)
        if party.notes:
            notes.append(party.notes)
        if party.signatory_name:
            notes.append("Người ký đọc được: " + party.signatory_name)
        if party.source_pages:
            notes.append("Trang nguồn: " + ", ".join(map(str, party.source_pages)))
        if party.evidence:
            notes.append("Trích từ nguồn:\n" + party.evidence)
        self.notes.setPlainText("\n\n".join(notes) or "Mở hợp đồng gốc để kiểm tra lại thông tin trước khi lưu.")
        self.match_existing()

    def edited(self, item):
        if item.column() == 2 and self.field_names[item.row()] in ("company_name", "tax_code"):
            self.match_existing()

    def match_existing(self):
        matches = self.store.matching_customers(self.customer_value())
        self.target.blockSignals(True)
        self.target.clear()
        if not matches:
            self.target.addItem("Thêm khách hàng mới — giữ các khách hàng hiện có", None)
        else:
            for customer in matches:
                self.target.addItem(f"Cập nhật khách hàng đã có #{customer.id}: {customer.company_name} · {customer.contact_name or 'Chưa có người liên hệ'}", customer.id)
            if len(matches) > 1:
                self.target.setCurrentIndex(-1)
                self.target.setPlaceholderText("Chọn bản ghi cần cập nhật để tránh tạo trùng…")
        self.target.blockSignals(False)
        self.show_previous()

    def show_previous(self, *_):
        target_id = self.target.currentData()
        existing = next((customer for customer in self.store.customers() if customer.id == target_id), None)
        self.table.blockSignals(True)
        if existing:
            for label in existing.extra_fields:
                self.append_extra(label)
        extras = extra_context(existing) if existing else {}
        for row, name in enumerate(self.field_names):
            value = (extras.get(name, "") if name in self.extra_labels else getattr(existing, name)) if existing else ""
            self.table.item(row, 1).setText(value)
            self.table.item(row, 1).setToolTip(value)
        self.table.blockSignals(False)
        self.save_button.setEnabled(self.party_selector.currentIndex() >= 0 and self.target.currentIndex() >= 0)

    def open_source(self):
        if not self.result.document.path.exists() or not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.document.path.resolve()))):
            self.error.setText("Không mở được hợp đồng gốc. File có thể đã được di chuyển.")
            self.error.show()

    def save_customer(self):
        try:
            customer = self.customer_value()
            validate_import_customer(customer)
            if self.target.currentIndex() < 0:
                raise UserError("Chọn bản ghi cần cập nhật trước khi lưu.")
            self.saved_customer = save_imported_customer(self.store, self.result, customer, self.target.currentData())
            self.accept()
        except UserError as exc:
            self.error.setText(str(exc))
            self.error.show()
        except OSError:
            self.error.setText("Không lưu được hợp đồng nguồn hoặc khách hàng. Kiểm tra quyền thư mục dữ liệu.")
            self.error.show()
        except Exception:
            self.error.setText("Chưa lưu được khách hàng. Các thay đổi chưa xác nhận vẫn ở cửa sổ này; kiểm tra thư mục dữ liệu rồi thử lại.")
            self.error.show()
