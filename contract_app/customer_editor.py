"""Edit a customer's standard and arbitrary fields with explicit save/cancel."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .customer_fields import CUSTOMER_BASE_FIELDS, clean_extra_fields, field_label
from .models import Customer, UserError


def text_label(text):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class CustomerEditor(QDialog):
    def __init__(self, store, customer=None, parent=None):
        super().__init__(parent)
        self.store, self.customer, self.saved_customer = store, customer, None
        self.setWindowTitle("Thông tin khách hàng" if customer else "Thêm khách hàng")
        available = self.screen().availableGeometry()
        self.resize(min(850, available.width() - 40), min(800, available.height() - 60))
        layout = QVBoxLayout(self)
        layout.addWidget(text_label("Chỉ cần thông tin nhận diện khách hàng. Các trường khác có thể để trống hoặc thêm theo hồ sơ."))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setObjectName("FormContent")
        form = QFormLayout(content)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.inputs = {}
        for name in CUSTOMER_BASE_FIELDS:
            field = QLineEdit(getattr(customer, name) if customer else "")
            field.setMaxLength(4000)
            title = "Tên khách hàng / người liên hệ" if name == "contact_name" else "Tên gọi ngắn / bí danh" if name == "aliases" else field_label(name)
            field.setAccessibleName(title)
            form.addRow(text_label(title), field)
            self.inputs[name] = field
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        layout.addWidget(text_label("Thông tin bổ sung — đặt tên trường theo hồ sơ của anh"))
        self.extras = QTableWidget(0, 2)
        self.extras.setAccessibleName("Các trường khách hàng bổ sung")
        self.extras.setHorizontalHeaderLabels(["Tên trường", "Giá trị"])
        self.extras.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.extras.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.extras.verticalHeader().setDefaultSectionSize(42)
        layout.addWidget(self.extras, 1)
        if customer:
            for name, value in customer.extra_fields.items():
                self.add_extra(name, value)
        actions = QHBoxLayout()
        add = QPushButton("+ Thêm trường")
        add.clicked.connect(lambda: self.add_extra())
        actions.addWidget(add)
        remove = QPushButton("Bỏ trường đã chọn")
        remove.clicked.connect(self.remove_extra)
        actions.addWidget(remove)
        actions.addStretch()
        layout.addLayout(actions)
        self.error = text_label("")
        self.error.setObjectName("Warning")
        self.error.hide()
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Lưu khách hàng")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add_extra(self, name="", value=""):
        row = self.extras.rowCount()
        self.extras.insertRow(row)
        self.extras.setItem(row, 0, QTableWidgetItem(name))
        self.extras.setItem(row, 1, QTableWidgetItem(value))
        self.extras.setCurrentCell(row, 0)

    def remove_extra(self):
        for row in sorted({index.row() for index in self.extras.selectedIndexes()}, reverse=True):
            self.extras.removeRow(row)

    def customer_value(self):
        values, labels = {}, set()
        for row in range(self.extras.rowCount()):
            name, value = (self.extras.item(row, col).text().strip() for col in (0, 1))
            if not name and not value:
                continue
            if name in labels:
                raise UserError("Trùng tên trường khách hàng: " + name)
            values[name] = value
            labels.add(name)
        return Customer(id=self.customer.id if self.customer else 0,
                        **{name: field.text().strip() for name, field in self.inputs.items()},
                        extra_fields=clean_extra_fields(values))

    def save(self):
        try:
            self.saved_customer = self.store.save_customer_edit(self.customer_value(), self.customer.id if self.customer else None)
            self.accept()
        except UserError as exc:
            self.error.setText(str(exc))
            self.error.show()
        except Exception:
            self.error.setText("Chưa lưu được khách hàng. Kiểm tra quyền thư mục dữ liệu rồi thử lại.")
            self.error.show()
