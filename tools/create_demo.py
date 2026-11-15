"""Build transparent, fictional sample files. Never use client data here."""
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment


def create_assets(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2)
    style = document.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(12)
    style.paragraph_format.space_after = Pt(7)
    header = section.header.paragraphs[0]
    header.text = "HỢP ĐỒNG AI  /  MẪU MINH HỌA"
    header.runs[0].font.size = Pt(9)
    header.runs[0].font.color.rgb = RGBColor.from_string("64748B")
    p = document.add_paragraph("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.runs[0].bold = True
    p = document.add_paragraph("Độc lập – Tự do – Hạnh phúc")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = document.add_paragraph("HỢP ĐỒNG THI CÔNG")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.runs[0].bold = True
    p.runs[0].font.size = Pt(18)
    p = document.add_paragraph("Số: {{ contract_number }}")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph("Ngày {{ day }} tháng {{ month }} năm {{ year }}, các bên gồm:")
    document.add_heading("BÊN A — {{ seller_company }}", level=2)
    for text in ["Mã số thuế: {{ seller_tax_code }}", "Địa chỉ: {{ seller_address }}", "Đại diện: {{ seller_representative }} — Chức vụ: {{ seller_position }}"]:
        document.add_paragraph(text)
    document.add_heading("BÊN B — {{ company_name }}", level=2)
    for text in ["Mã số thuế: {{ tax_code }}", "Địa chỉ: {{ address }}", "Đại diện: {{ representative }} — Chức vụ: {{ position }}", "Người liên hệ: {{ contact_name }}"]:
        document.add_paragraph(text)
    document.add_heading("ĐIỀU 1. NỘI DUNG CÔNG VIỆC", level=2)
    document.add_paragraph("{{ work_description }}")
    document.add_heading("ĐIỀU 2. GIÁ TRỊ HỢP ĐỒNG", level=2)
    table = document.add_table(rows=2, cols=2)
    table.style = "Table Grid"
    table.cell(0, 0).text = "Giá trị (VND)"
    table.cell(0, 1).text = "{{ amount }} đồng"
    table.cell(1, 0).text = "Bằng chữ"
    table.cell(1, 1).text = "{{ amount_words }}"
    document.add_paragraph("Mẫu này chỉ minh họa việc điền dữ liệu. Điều khoản thuế, thanh toán, thời hạn và trách nhiệm cần được xác định trong mẫu sử dụng thực tế.")
    signatures = document.add_table(rows=2, cols=2)
    signatures.cell(0, 0).text = "ĐẠI DIỆN BÊN A"
    signatures.cell(0, 1).text = "ĐẠI DIỆN BÊN B"
    signatures.cell(1, 0).text = "{{ seller_representative }}"
    signatures.cell(1, 1).text = "{{ representative }}"
    footer = section.footer.paragraphs[0]
    footer.text = "{% if is_demo %}DỮ LIỆU MINH HỌA — KHÔNG PHẢI HỢP ĐỒNG THỰC TẾ{% else %}Tạo từ mẫu minh họa; cần thay bằng mẫu hợp đồng đã duyệt.{% endif %}"
    footer.runs[0].font.size = Pt(9)
    document.save(root / "Mau-thi-cong-minh-hoa.docx")
    book = Workbook()
    sheet = book.active
    sheet.title = "Khách hàng"
    sheet.append(["Tên liên hệ", "Tên công ty", "Mã số thuế", "Địa chỉ", "Người đại diện", "Chức vụ", "Điện thoại", "Email", "Bí danh"])
    sheet.append(["Nguyễn Văn Thông", "CÔNG TY TNHH X (MINH HỌA)", "DEMO-X", "Địa chỉ minh họa tại Hà Nội", "Nguyễn Văn Bình (minh họa)", "Giám đốc", "", "", "Công ty X;X"])
    sheet.append(["Trần Văn Thông", "CÔNG TY TNHH Y (MINH HỌA)", "DEMO-Y", "Địa chỉ minh họa tại TP. Hồ Chí Minh", "Trần Văn An (minh họa)", "Giám đốc", "", "", "Công ty Y;Y"])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = PatternFill("solid", fgColor="1D4ED8")
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = min(52, max(20, max(len(str(c.value or "")) for c in column) + 3))
    book.save(root / "Khach-hang-minh-hoa.xlsx")


if __name__ == "__main__":
    create_assets(Path(__file__).resolve().parents[1] / "assets")
