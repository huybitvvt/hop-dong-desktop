"""Review AI suggestions using source text and native, editable controls."""
from __future__ import annotations

from pathlib import Path
import html
import re
import tempfile
from pydantic import ValidationError

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from .models import FIELD_LABELS, UserError
from .template_builder import ALLOWED_FIELDS, Replacement, TemplateDraft, TemplatePlan, blank_slots_from_word, build_template_bytes, save_template
from .customer_fields import customer_field_key, field_label
from .blank_fields import DOTS, PARTY_FIELDS, field_hint, role_of

PARTY_LABELS = {"company_name": "Tên đơn vị", "tax_code": "Mã số thuế", "address": "Địa chỉ",
    "representative": "Người đại diện", "position": "Chức vụ", "contact_name": "Người liên hệ",
    "phone": "Điện thoại", "email": "Email", "bank_account": "Tài khoản ngân hàng", "bank_name": "Ngân hàng"}


def text_label(text, name=None):
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if name:
        label.setObjectName(name)
    return label


class TemplateChoiceDialog(QDialog):
    def __init__(self, matches, selected=None, parent=None):
        super().__init__(parent)
        self.matches = matches
        self.setWindowTitle("Chọn mẫu phù hợp")
        self.resize(690, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(text_label("Có nhiều mẫu có thể sử dụng", "SectionTitle"))
        layout.addWidget(text_label("Chọn mẫu cho yêu cầu này. Nội dung các mẫu được tra trên máy.", "Muted"))
        self.list = QListWidget()
        self.list.setAccessibleName("Các mẫu hợp đồng phù hợp")
        for item in matches:
            self.list.addItem(item.title + "\n" + item.description[:220])
        layout.addWidget(self.list, 1)
        index = next((i for i, item in enumerate(matches) if str(item.path) == str(selected)), 0)
        self.list.setCurrentRow(index)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Dùng mẫu này")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_path(self):
        return self.matches[self.list.currentRow()].path


class TemplateSourceDialog(QDialog):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Chuẩn bị mẫu từ hợp đồng có sẵn")
        self.resize(630, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(text_label(path.name, "SectionTitle"))
        layout.addWidget(text_label("Dùng được cả hợp đồng đã điền và mẫu trống chưa có biến. Chọn đúng bên đối tác sẽ thay đổi khi tạo hợp đồng mới.", "Muted"))
        form = QFormLayout()
        self.role = QComboBox()
        self.role.addItems(["Bên B", "Bên A"])
        self.role.setAccessibleName("Bên đối tác cần thay thông tin")
        form.addRow("Đối tác cần thay", self.role)
        layout.addLayout(form)
        detail = "Gemini nhận diện dữ liệu và chỗ trống cần điền. Anh sẽ kiểm tra trước khi lưu. Bên còn lại đã có thông tin thì giữ nguyên; chỗ trống lấy từ Cài đặt công ty hoặc hỏi bổ sung."
        if path.suffix.lower() == ".pdf":
            detail += " PDF được dựng thành Word chỉnh sửa được; cần đối chiếu lại bảng và bố cục."
        layout.addWidget(text_label(detail, "Muted"))
        self.vision = QCheckBox("Đọc lại bằng Gemini, bỏ kết quả đã xử lý trước đó")
        layout.addWidget(self.vision)
        layout.addWidget(text_label("Ảnh dấu và chữ ký sẽ được bỏ khỏi mẫu mới. File gốc được giữ nguyên.", "Warning"))
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Đọc và đề xuất mẫu")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class TemplateReview(QDialog):
    def __init__(self, store, draft: TemplateDraft, parent=None):
        super().__init__(parent)
        self.store, self.draft = store, draft
        self.slots = {slot.id: slot for slot in blank_slots_from_word(draft.word_data)}
        self.custom_fields = store.customer_field_labels() | {item.key: item.label for item in draft.plan.custom_fields}
        self.saved_path = None
        palette = self.palette()
        for role, value in ((QPalette.ColorRole.Window, "#F4F7FB"), (QPalette.ColorRole.Base, "#FFFFFF"),
                            (QPalette.ColorRole.Button, "#FFFFFF"), (QPalette.ColorRole.WindowText, "#17243B"),
                            (QPalette.ColorRole.Text, "#17243B"), (QPalette.ColorRole.ButtonText, "#17243B")):
            palette.setColor(role, QColor(value))
        self.setPalette(palette)
        self.preview_folder = tempfile.TemporaryDirectory(prefix="HopDong-Mau-", ignore_cleanup_errors=True)
        self.setWindowTitle("Kiểm tra mẫu hợp đồng")
        available = self.screen().availableGeometry()
        self.resize(min(1120, available.width() - 40), min(800, available.height() - 70))
        self.setMinimumSize(900, 640)
        layout = QVBoxLayout(self)
        layout.setSpacing(7)
        heading = QHBoxLayout()
        heading.addWidget(text_label("Kiểm tra các thông tin sẽ tự điền", "SectionTitle"), 1)
        self.warning_toggle = QPushButton(f"Lưu ý ({len(draft.plan.warnings)})")
        self.warning_toggle.setObjectName("CompactButton")
        self.warning_toggle.setCheckable(True)
        self.warning_toggle.setVisible(bool(draft.plan.warnings))
        heading.addWidget(self.warning_toggle)
        layout.addLayout(heading)
        form = QFormLayout()
        self.title_input = QLineEdit(draft.plan.title)
        self.title_input.setMaxLength(160)
        self.title_input.setAccessibleName("Tên mẫu hợp đồng")
        form.addRow("Tên mẫu", self.title_input)
        layout.addLayout(form)
        seller_role = "Bên A" if draft.customer_role == "Bên B" else "Bên B"
        self.role_hint = text_label(f"Khách hàng: {self.role_caption(draft.customer_role)}    |    Công ty của bạn: {self.role_caption(seller_role)}", "Badge")
        layout.addWidget(self.role_hint)
        self.warning = text_label("\n".join("• " + w for w in draft.plan.warnings), "Warning")
        self.warning.setMaximumHeight(120)
        self.warning.hide()
        self.warning_toggle.toggled.connect(self.warning.setVisible)
        if draft.reconstructed or any("KHÔNG ĐỌC RÕ" in note.upper() for note in draft.plan.warnings):
            self.warning_toggle.setChecked(True)
        layout.addWidget(self.warning)
        split = self.splitter = QSplitter(Qt.Orientation.Horizontal)
        source = QWidget()
        source.setObjectName("FormContent")
        left = QVBoxLayout(source)
        left.setContentsMargins(0, 0, 6, 0)
        left.addWidget(text_label("Nội dung nguồn", "SectionTitle"))
        self.anchors = QListWidget()
        self.anchors.setAccessibleName("Các đoạn trong tài liệu nguồn")
        for number, anchor in enumerate(draft.anchors, 1):
            self.anchors.addItem(f"{number}. {DOTS.sub('[trống]', anchor.text)[:100] if anchor.text.strip() else '[Ô / đoạn trống]'}")
            self.anchors.item(number - 1).setData(Qt.ItemDataRole.UserRole, anchor.id)
            self.anchors.item(number - 1).setToolTip(anchor.context)
        left.addWidget(self.anchors, 1)
        self.source_context = text_label("", "Muted")
        self.source_context.setMaximumHeight(70)
        left.addWidget(self.source_context)
        self.source_text = QPlainTextEdit()
        self.source_text.setReadOnly(True)
        self.source_text.setPlaceholderText("Ô hoặc đoạn này đang trống. Chọn chỗ trống bên dưới để gán trường tự điền.")
        self.source_text.setAccessibleName("Đoạn gốc; có thể bôi đen nội dung để chọn vùng tự điền")
        left.addWidget(self.source_text, 1)
        add = QPushButton("Thêm vùng đang bôi đen")
        add.clicked.connect(self.add_selected)
        left.addWidget(add)
        self.blank_selector = QComboBox()
        self.blank_selector.setAccessibleName("Các chỗ trống trong đoạn nguồn")
        left.addWidget(self.blank_selector)
        self.add_blank_button = QPushButton("Thêm chỗ trống")
        self.add_blank_button.clicked.connect(self.add_blank)
        left.addWidget(self.add_blank_button)
        self.anchors.currentRowChanged.connect(self.select_anchor)
        self.source_panel = QScrollArea()
        self.source_panel.setWidgetResizable(True)
        self.source_panel.setWidget(source)
        self.source_panel.setMinimumWidth(260)
        split.addWidget(self.source_panel)
        target = QWidget()
        right = QVBoxLayout(target)
        right.setContentsMargins(0, 0, 0, 0)
        self.preview = QTextBrowser()
        self.preview.setObjectName("TemplatePreview")
        self.preview.setAccessibleName("Vị trí tự điền trong hợp đồng gốc")
        self.preview.setOpenLinks(False)
        self.preview.setMinimumHeight(72)
        self.preview.setMaximumHeight(86)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Chỗ sẽ điền trong hợp đồng", "Nội dung gốc", "Thông tin lấy để điền", "Lần"])
        self.table.setAccessibleName("Đề xuất vùng tự điền cần kiểm tra")
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(56)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(1, 230)
        self.table.setColumnWidth(2, 400)
        self.table.setColumnWidth(3, 90)
        for replacement in draft.plan.replacements:
            self.add_row(replacement)
        self.table.currentCellChanged.connect(lambda row, col, *_: self.select_mapping(row, col))
        right.addWidget(self.table, 1)
        toolbar = QHBoxLayout()
        add_field = QPushButton("+ Thêm trường khách hàng")
        add_field.setObjectName("CompactButton")
        add_field.clicked.connect(self.add_customer_field)
        toolbar.addWidget(add_field)
        remove = QPushButton("Bỏ vùng đã chọn")
        remove.setObjectName("CompactButton")
        remove.clicked.connect(self.remove_selected)
        toolbar.addWidget(remove)
        toolbar.addStretch()
        self.advanced_toggle = QPushButton("Chỉnh chi tiết")
        self.advanced_toggle.setObjectName("CompactButton")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.toggled.connect(self.set_advanced)
        toolbar.addWidget(self.advanced_toggle)
        right.addLayout(toolbar)
        split.addWidget(target)
        layout.addWidget(split, 1)
        layout.addWidget(self.preview)
        self.keep_draft = QCheckBox("Mẫu nháp — hợp đồng tạo ra được đánh dấu bản thử")
        self.keep_draft.setChecked(True)
        layout.addWidget(self.keep_draft)
        self.error = text_label("", "Warning")
        self.error.hide()
        layout.addWidget(self.error)
        actions = QHBoxLayout()
        open_source = QPushButton("Mở bản gốc")
        open_source.clicked.connect(self.open_source)
        actions.addWidget(open_source)
        self.preview_button = QPushButton("Xem mẫu Word trước khi lưu")
        self.preview_button.clicked.connect(self.open_preview)
        actions.addWidget(self.preview_button)
        actions.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setText("Lưu mẫu tái sử dụng")
        self.save_button.setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        actions.addWidget(buttons)
        layout.addLayout(actions)
        self.set_advanced(False)
        if self.anchors.count():
            self.anchors.setCurrentRow(0)
        if self.table.rowCount():
            self.table.setCurrentCell(0, 0)
            self.select_mapping(0, 0)

    def role_caption(self, role):
        for anchor in self.draft.anchors:
            if role_of(anchor.text) == role:
                qualifier = re.search(r"\(([^)]+)\)", anchor.text)
                return role + (" (" + qualifier.group(1).lower() + ")" if qualifier else "")
        return role

    def set_advanced(self, checked):
        self.source_panel.setVisible(checked)
        self.table.setColumnHidden(1, not checked)
        self.table.setColumnHidden(3, not checked)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive if checked else QHeaderView.ResizeMode.Stretch)
        if checked:
            self.table.setColumnWidth(0, 250)
        self.table.setColumnWidth(2, 330 if checked else 400)
        self.splitter.setSizes([320, 760] if checked else [0, 1080])

    def field_caption(self, name):
        if name.startswith("seller_"):
            key = "company_name" if name == "seller_company" else name.removeprefix("seller_")
            return "Công ty của bạn · " + PARTY_LABELS.get(key, field_label(name, self.custom_fields))
        if name in PARTY_LABELS:
            return "Khách hàng · " + PARTY_LABELS[name]
        if name in self.custom_fields:
            return "Khách hàng · " + self.custom_fields[name]
        return field_label(name)

    def source_caption(self, anchor, slot, source_text=""):
        if slot:
            prefix = anchor.text[:slot.start]
            previous_blanks = list(DOTS.finditer(prefix))
            if previous_blanks:
                prefix = prefix[previous_blanks[-1].end():]
            caption = prefix.strip(" :：;—–-\t\n")
        else:
            caption = anchor.text.partition(source_text)[0].strip(" :：;—–-\t\n") if source_text else ""
            if not caption:
                caption = source_text
        if not caption and "Dòng bảng:" in anchor.context:
            cells = anchor.context.split("Dòng bảng:", 1)[1].rsplit(" | Ô", 1)[0].split(" | ")
            column = re.search(r"\| Ô (\d+)$", anchor.context)
            left = int(column.group(1)) - 2 if column else 0
            if 0 <= left < len(cells):
                caption = cells[left].strip(" :：")
        if not caption:
            index = self.draft.anchors.index(anchor)
            for previous in reversed(self.draft.anchors[max(0, index - 8):index]):
                candidate = DOTS.sub("", previous.text).strip()
                if candidate:
                    caption = candidate.rstrip(":：")
                    break
        caption = caption or source_text or "Ô trống chưa có nhãn"
        heading_role = role_of(caption)
        if heading_role:
            caption = "Tên đơn vị"
        hint = (slot.hint if slot else None) or field_hint(caption)
        if hint == "contract_number":
            caption = "Số hợp đồng"
        elif hint in ("day", "month", "year"):
            caption = "Ngày ký · " + {"day": "ngày", "month": "tháng", "year": "năm"}[hint]
        role = slot.role if slot else role_of(anchor.context)
        if role and (heading_role or hint in PARTY_FIELDS):
            caption = role + " · " + caption
        if "header" in anchor.id:
            caption = "Đầu trang · " + caption
        elif "footer" in anchor.id:
            caption = "Chân trang · " + caption
        return caption[:170]

    def select_anchor(self, row):
        anchor = self.draft.anchors[row] if row >= 0 else None
        self.source_text.setPlainText(anchor.text if anchor else "")
        self.source_context.setText(anchor.context if anchor else "")
        self.blank_selector.clear()
        for slot in self.slots.values():
            if anchor and slot.anchor == anchor.id:
                label = self.slot_label(slot)
                hint = slot.target_hint(self.draft.customer_role)
                if hint:
                    label += " — " + FIELD_LABELS.get(hint, {"day": "Ngày", "month": "Tháng", "year": "Năm"}.get(hint, hint))
                self.blank_selector.addItem(label, slot.id)
        self.blank_selector.setEnabled(self.blank_selector.count() > 0)
        self.add_blank_button.setEnabled(self.blank_selector.count() > 0)

    def slot_label(self, slot):
        if slot.kind in ("empty_cell", "empty_paragraph"):
            return "[Ô trống]" if slot.kind == "empty_cell" else "[Đoạn trống]"
        if slot.kind == "after_label":
            return "[Chèn sau nhãn]"
        source = next(anchor.text for anchor in self.draft.anchors if anchor.id == slot.anchor)
        return ("[Dòng chấm / gạch] " + source[slot.start:slot.end][:30].strip()) if slot.kind == "dotted" else "[Khoảng trống]"

    def add_row(self, replacement: Replacement):
        row = self.table.rowCount()
        self.table.insertRow(row)
        original = next((item for item in self.draft.anchors if item.id == replacement.anchor), None)
        slot = self.slots.get(replacement.slot_id)
        caption = self.source_caption(original, slot, replacement.source_text) if original else "Không tìm thấy đoạn nguồn"
        anchor = QTableWidgetItem(caption)
        anchor.setData(Qt.ItemDataRole.UserRole, replacement.anchor)
        anchor.setData(Qt.ItemDataRole.UserRole + 1, replacement.slot_id)
        anchor.setData(Qt.ItemDataRole.UserRole + 2, replacement.reason)
        anchor.setFlags(anchor.flags() & ~Qt.ItemFlag.ItemIsEditable)
        anchor.setToolTip("<pre>" + html.escape(original.text if original else replacement.reason) + "</pre>")
        self.table.setItem(row, 0, anchor)
        source = QTableWidgetItem(replacement.source_text)
        source.setToolTip(replacement.source_text)
        if replacement.slot_id:
            slot = self.slots.get(replacement.slot_id)
            source.setText(self.slot_label(slot) if slot else "[Chỗ trống không khớp]")
            source.setData(Qt.ItemDataRole.UserRole, replacement.source_text)
            source.setFlags(source.flags() & ~Qt.ItemFlag.ItemIsEditable)
            source.setToolTip(slot.context if slot else replacement.reason)
        self.table.setItem(row, 1, source)
        fields = QComboBox()
        fields.setAccessibleName(f"Trường tự điền dòng {row + 1}")
        fields.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        fields.setMinimumContentsLength(18)
        fields.view().setMinimumWidth(460)
        for name in sorted(ALLOWED_FIELDS | self.custom_fields.keys()):
            fields.addItem(self.field_caption(name), name)
        if fields.findData(replacement.field) < 0:
            fields.addItem("Chưa hỗ trợ: " + replacement.field, replacement.field)
        fields.setCurrentIndex(fields.findData(replacement.field))
        fields.setToolTip(fields.currentText())
        fields.currentTextChanged.connect(fields.setToolTip)
        fields.currentIndexChanged.connect(lambda *_: self.refresh_preview())
        self.table.setCellWidget(row, 2, fields)
        occurrence = QSpinBox()
        occurrence.setRange(1, 200)
        occurrence.setValue(replacement.occurrence)
        occurrence.setEnabled(not replacement.slot_id)
        occurrence.setAccessibleName(f"Lần xuất hiện dòng {row + 1}")
        self.table.setCellWidget(row, 3, occurrence)

    def select_mapping(self, row, _col):
        if row < 0 or not self.table.item(row, 0):
            self.refresh_preview()
            return
        anchor = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        for index, item in enumerate(self.draft.anchors):
            if item.id == anchor:
                self.anchors.setCurrentRow(index)
                slot = self.slots.get(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole + 1))
                if slot:
                    cursor = self.source_text.textCursor()
                    cursor.setPosition(slot.start)
                    cursor.setPosition(slot.end, QTextCursor.MoveMode.KeepAnchor)
                    self.source_text.setTextCursor(cursor)
                break
        self.refresh_preview()

    def refresh_preview(self):
        row = self.table.currentRow()
        if row < 0 or not self.table.item(row, 0) or not self.table.cellWidget(row, 3):
            self.preview.setPlainText("Chọn một dòng để xem vị trí sẽ điền trong hợp đồng.")
            return
        identity = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        anchor = next((item for item in self.draft.anchors if item.id == identity), None)
        if anchor is None:
            self.preview.setPlainText("Không tìm thấy đoạn nguồn. Chọn Chỉnh chi tiết để kiểm tra lại.")
            return
        slot = self.slots.get(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole + 1))
        if slot:
            start, end = slot.start, slot.end
        else:
            value = self.table.item(row, 1).text()
            matches = list(re.finditer(re.escape(value), anchor.text)) if value else []
            occurrence = self.table.cellWidget(row, 3).value()
            if len(matches) < occurrence:
                self.preview.setPlainText("Nội dung chọn chưa khớp với bản gốc. Chọn Chỉnh chi tiết để sửa vùng này.")
                return
            start, end = matches[occurrence - 1].span()
        def escaped(text):
            return html.escape(DOTS.sub("…", text)).replace("\n", "<br>")
        field = self.field_caption(self.table.cellWidget(row, 2).currentData())
        body = escaped(anchor.text[:start]) + '<span style="background:#DBEAFE;color:#1E40AF;font-weight:600">[' + html.escape(field) + "]</span>" + escaped(anchor.text[end:])
        self.preview.setHtml('<div style="color:#586A82">Vị trí trong bản gốc · ' + html.escape(self.table.item(row, 0).text()) + '</div><div style="margin-top:5px">' + body + "</div>")

    def add_selected(self):
        row = self.anchors.currentRow()
        cursor = self.source_text.textCursor()
        selected = cursor.selectedText().replace("\u2029", "\n")
        if row < 0 or not selected:
            self.show_error("Bôi đen dữ liệu cần thay trong một đoạn nguồn rồi bấm Thêm vùng.")
            return
        text = self.draft.anchors[row].text
        occurrence = text[:cursor.selectionStart()].count(selected) + 1
        self.add_row(Replacement(anchor=self.draft.anchors[row].id, source_text=selected, field="company_name", occurrence=occurrence))
        self.table.setCurrentCell(self.table.rowCount() - 1, 2)
        self.error.hide()

    def add_blank(self):
        slot = self.slots.get(self.blank_selector.currentData())
        if slot is None:
            self.show_error("Chọn một đoạn có chỗ trống trong danh sách nguồn.")
            return
        if any(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole + 1) == slot.id for row in range(self.table.rowCount())):
            self.show_error("Chỗ trống này đã có trong bảng. Sửa trường tự điền tại dòng hiện có.")
            return
        anchor = next(item for item in self.draft.anchors if item.id == slot.anchor)
        self.add_row(Replacement(anchor=slot.anchor, source_text=anchor.text[slot.start:slot.end],
            field=slot.target_hint(self.draft.customer_role) or "company_name", slot_id=slot.id,
            reason="Người dùng chọn chỗ trống trong bản nguồn"))
        self.table.setCurrentCell(self.table.rowCount() - 1, 2)
        self.error.hide()

    def remove_selected(self):
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(row)
        self.refresh_preview()

    def add_customer_field(self):
        name, accepted = QInputDialog.getText(self, "Thêm trường khách hàng", "Tên trường, ví dụ Số CCCD hoặc Email kế toán:")
        if accepted:
            try:
                key = customer_field_key(name)
                self.custom_fields.setdefault(key, name.strip())
                for row in range(self.table.rowCount()):
                    combo = self.table.cellWidget(row, 2)
                    if combo.findData(key) < 0:
                        combo.addItem(self.field_caption(key), key)
                if self.table.currentRow() >= 0:
                    combo = self.table.cellWidget(self.table.currentRow(), 2)
                    combo.setCurrentIndex(combo.findData(key))
                self.error.hide()
            except UserError as exc:
                self.show_error(str(exc))

    def plan(self):
        data = self.draft.plan.model_dump()
        data["title"] = self.title_input.text().strip()
        used = {self.table.cellWidget(row, 2).currentData() for row in range(self.table.rowCount())}
        data["custom_fields"] = [{"key": key, "label": name} for key, name in self.custom_fields.items() if key in used]
        data["replacements"] = [{
            "anchor": self.table.item(row, 0).data(Qt.ItemDataRole.UserRole),
            "slot_id": self.table.item(row, 0).data(Qt.ItemDataRole.UserRole + 1),
            "source_text": self.table.item(row, 1).data(Qt.ItemDataRole.UserRole) if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole + 1) else self.table.item(row, 1).text(),
            "field": self.table.cellWidget(row, 2).currentData(),
            "occurrence": self.table.cellWidget(row, 3).value(),
            "reason": self.table.item(row, 0).data(Qt.ItemDataRole.UserRole + 2) or "",
        } for row in range(self.table.rowCount())]
        if not data["title"]:
            raise UserError("Cần đặt tên mẫu trước khi lưu.")
        if any(not item["source_text"] and not item["slot_id"] for item in data["replacements"]):
            raise UserError("Vùng không có dữ liệu cần chọn bằng nút Thêm chỗ trống. Bỏ dòng không dùng.")
        try:
            return TemplatePlan.model_validate(data)
        except ValidationError as exc:
            raise UserError("Dữ liệu vùng tự điền vượt giới hạn hoặc chưa hợp lệ. Kiểm tra nội dung và số dòng.") from exc

    def show_error(self, text):
        self.error.setText(text)
        self.error.show()

    def open_source(self):
        # Use the same bytes that were reviewed, even if the original moved/changed.
        path = Path(self.preview_folder.name) / ("Nguon-doi-chieu" + self.draft.source.suffix.lower())
        path.write_bytes(self.draft.source_data)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.show_error("Không mở được bản gốc. Kiểm tra trình đọc PDF/Word trên máy.")

    def open_preview(self):
        try:
            path = Path(self.preview_folder.name) / "Mau-xem-truoc.docx"
            path.write_bytes(build_template_bytes(self.draft, self.plan(), self.keep_draft.isChecked()))
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                self.show_error("Không mở được Word. Kiểm tra ứng dụng đọc .docx trên máy.")
        except UserError as exc:
            self.show_error(str(exc))
        except OSError:
            self.show_error("Chưa ghi được bản xem trước; đóng file Word xem trước rồi thử lại.")

    def save(self):
        try:
            self.saved_path = save_template(self.store, self.draft, self.plan(), self.keep_draft.isChecked())
            self.accept()
        except UserError as exc:
            self.show_error(str(exc))
        except OSError:
            self.show_error("Chưa lưu được mẫu. Kiểm tra quyền truy cập thư mục dữ liệu.")
