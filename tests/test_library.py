from io import BytesIO
from pathlib import Path
import zipfile

from docx import Document
from pypdf import PdfWriter
import pytest

from contract_app.drive_zip import RangeFile, drive_file_id
from contract_app.library import DocumentLibrary
from contract_app.models import UserError


def word(path, text):
    doc = Document()
    doc.add_paragraph(text)
    doc.save(path)
    return path


def test_folder_import_preserves_existing_customers_config_and_templates(store, tmp_path):
    source = tmp_path / "originals"
    source.mkdir()
    docx = word(source / "Hợp đồng An Phú Demo.docx", "Công ty An Phú Demo — mã số thuế 0000000111")
    word(source / "~$Hopdong.docx", "Office lock file")
    before = (store.customers(), store.config_file.read_bytes(), {p.name: p.read_bytes() for p in store.templates.glob("*")})
    library = DocumentLibrary(store)
    result = library.index_folder(source)
    assert result.added == 1
    assert not result.errors
    assert len(library.documents("an phu demo")) == 1
    assert len(library.documents("0000000111")) == 1
    assert library.materialize(library.documents()[0]["id"]) == docx
    assert library.index_folder(source).skipped == 1
    assert before == (store.customers(), store.config_file.read_bytes(), {p.name: p.read_bytes() for p in store.templates.glob("*")})


def test_zip_index_is_lazy_and_extracts_only_chosen_file_without_traversal(store, tmp_path):
    original = word(tmp_path / "source.docx", "Công ty An Phú Demo")
    archive = tmp_path / "contracts.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("Hồ sơ/Hợp đồng An Phú Demo.docx", original.read_bytes())
        handle.writestr("Hồ sơ/Khác.docx", original.read_bytes())
        handle.writestr("../escape.docx", original.read_bytes())
        handle.writestr("C:/escape.docx", original.read_bytes())
        handle.writestr("Hồ sơ/~$lock.docx", b"not a document")
    library = DocumentLibrary(store)
    summary = library.index_zip(archive)
    assert summary.added == 2
    assert len(summary.errors) == 2
    assert not (store.directory / "library_sources").exists()
    row = library.documents("an phu demo")[0]
    target = library.materialize(row["id"])
    assert target.read_bytes() == original.read_bytes()
    assert len(list((store.directory / "library_sources").glob("*"))) == 1
    assert library.get(row["id"])["status"] == "text"
    assert library.index_zip(archive).skipped == 2
    assert not (tmp_path / "escape.docx").exists()


def test_modified_source_and_modified_zip_are_never_silently_used(store, tmp_path):
    source = word(tmp_path / "old.docx", "Bản gốc")
    library = DocumentLibrary(store)
    library.index_paths([source])
    row = library.documents()[0]
    word(source, "Bản khác")
    with pytest.raises(UserError, match="thay đổi"):
        library.materialize(row["id"])
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.write(source, "old.docx")
    library.index_zip(archive)
    row = next(r for r in library.documents() if r["archive"])
    word(source, "Lại thay đổi")
    with zipfile.ZipFile(archive, "w") as handle:
        handle.write(source, "old.docx")
    with pytest.raises(UserError, match="thay đổi"):
        library.materialize(row["id"])


def test_scan_pdf_can_be_indexed_and_search_query_is_literal(store, tmp_path):
    path = tmp_path / "An Phú Demo.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with path.open("wb") as stream:
        writer.write(stream)
    library = DocumentLibrary(store)
    assert library.index_paths([path]).added == 1
    assert library.documents("An Phu Demo")[0]["status"] == "scan"
    assert not library.documents("%")
    assert not library.documents("' OR 1=1 --")
    assert library.index_paths([path], cancelled=lambda: True).added == 0


@pytest.mark.parametrize("link", [
    "https://drive.google.com/file/d/DEMO_Public_Zip_0123456789012345/view",
    "https://drive.google.com/open?id=DEMO_Public_Zip_0123456789012345",
    "DEMO_Public_Zip_0123456789012345",
])
def test_drive_links_only_accept_file_ids(link):
    assert drive_file_id(link) == "DEMO_Public_Zip_0123456789012345"


@pytest.mark.parametrize("link", ["https://evil.example/file/d/01234567890123456789", "http://127.0.0.1/", "https://drive.google.com/drive/folders/123"])
def test_arbitrary_urls_are_not_fetched(link):
    with pytest.raises(UserError):
        drive_file_id(link)


def test_range_reader_refuses_full_downloads_and_incorrect_ranges():
    class Response(BytesIO):
        def __init__(self, status, headers, data):
            super().__init__(data)
            self.status, self.headers = status, headers

    class Opener:
        def __init__(self, status, headers, data):
            self.result = status, headers, data
        def open(self, *_args, **_kwargs):
            return Response(*self.result)

    for opener in [Opener(200, {}, b"big archive"), Opener(206, {"Content-Range": "bytes 5-8/10"}, b"wrong")]:
        with pytest.raises(UserError):
            RangeFile(opener, "https://drive.usercontent.google.com/download?id=test", 10).read(3)
    reader = RangeFile(Opener(206, {"Content-Range": "bytes 0-2/10"}, b"abc"), "https://drive.usercontent.google.com/download?id=test", 10)
    assert reader.read(3) == b"abc"
    assert reader.tell() == 3
