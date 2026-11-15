"""Local searchable document catalog. Importing a folder never calls an AI API."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
from pathlib import Path, PurePosixPath
import sqlite3
import zipfile

from openpyxl import load_workbook
from pypdf import PdfReader

from .documents import check_docx
from .drive_zip import drive_file_id, open_drive_zip
from .models import UserError
from .money import normalize
from .template_builder import anchors_from_word

SUPPORTED = {".pdf", ".docx", ".xlsx"}
MAX_DOCUMENT_BYTES = 40_000_000
MAX_ENTRIES = 5000


@dataclass
class ImportSummary:
    added: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    cancelled: bool = False


class DocumentLibrary:
    def __init__(self, store):
        self.store = store
        with store.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS library_documents (
                id INTEGER PRIMARY KEY, identity TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                path TEXT NOT NULL DEFAULT '', archive TEXT NOT NULL DEFAULT '', member TEXT NOT NULL DEFAULT '',
                drive_id TEXT NOT NULL DEFAULT '', size INTEGER NOT NULL, crc INTEGER,
                sha256 TEXT NOT NULL DEFAULT '', pages INTEGER, text TEXT NOT NULL DEFAULT '',
                search_text TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL,
                template_path TEXT NOT NULL DEFAULT '')""")

    def documents(self, query="") -> list[dict]:
        clauses, args = [], []
        for token in normalize(query)[:500].split()[:12]:
            clauses.append("search_text LIKE ? ESCAPE '\\'")
            args.append("%" + token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.store.connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM library_documents" + where + " ORDER BY id DESC LIMIT 5000", args)]

    def get(self, identity: int) -> dict:
        with self.store.connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM library_documents WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise UserError("Hồ sơ không còn trong thư viện. Hãy làm mới danh sách.")
        return dict(row)

    def _insert(self, **values) -> bool:
        values["created"] = datetime.now().isoformat(timespec="seconds")
        with self.store.connect() as conn:
            cursor = conn.execute(f"INSERT OR IGNORE INTO library_documents ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", list(values.values()))
            return bool(cursor.rowcount)

    def index_paths(self, paths, progress=None, cancelled=None) -> ImportSummary:
        summary = ImportSummary()
        count = 0
        for path in paths:
            if cancelled and cancelled():
                summary.cancelled = True
                break
            path = Path(path).resolve()
            if path.suffix.lower() not in SUPPORTED or path.name.startswith("~$"):
                continue
            count += 1
            if count > MAX_ENTRIES:
                summary.errors.append("Đã đạt giới hạn 5.000 file mỗi lần nhập; hãy chia nhỏ thư mục.")
                break
            if progress:
                progress(f"Đang lập danh mục hồ sơ {count}: {path.name}")
            try:
                size = path.stat().st_size
                if size > MAX_DOCUMENT_BYTES:
                    identity = hashlib.sha256(f"{path}\n{size}\n{path.stat().st_mtime_ns}".encode()).hexdigest()
                    added = self._insert(identity="large:" + identity, name=path.name, path=str(path), size=size,
                                         status="large", search_text=normalize(str(path)))
                    summary.added += int(added)
                    summary.skipped += int(not added)
                    continue
                data = path.read_bytes()
                if len(data) > MAX_DOCUMENT_BYTES:
                    raise UserError("File vừa thay đổi và vượt 40 MB.")
                digest = hashlib.sha256(data).hexdigest()
                text, pages, status = index_text(path)
                added = self._insert(identity="sha256:" + digest, name=path.name, path=str(path), size=size,
                                     sha256=digest, text=text, pages=pages, status=status,
                                     search_text=normalize(str(path) + " " + text))
                summary.added += int(added)
                summary.skipped += int(not added)
            except (OSError, UserError, ValueError):
                summary.errors.append(path.name + ": chưa đọc được hoặc vượt giới hạn; file gốc được giữ nguyên.")
        return summary

    def index_folder(self, folder: Path, **kwargs):
        return self.index_paths((p for p in folder.rglob("*") if p.is_file() and not p.is_symlink()), **kwargs)

    def index_zip(self, path: Path | None = None, drive_link: str = "", progress=None, cancelled=None):
        summary = ImportSummary()
        drive_id = drive_file_id(drive_link) if drive_link else ""
        try:
            archive = open_drive_zip(drive_id) if drive_id else zipfile.ZipFile(path)
            with archive:
                infos = archive.infolist()
                if len(infos) > 15000:
                    raise UserError("ZIP có quá nhiều mục. Hãy chia bộ hồ sơ thành các ZIP nhỏ hơn.")
                for index, info in enumerate(infos):
                    if cancelled and cancelled():
                        summary.cancelled = True
                        break
                    parts = PurePosixPath(info.filename.replace("\\", "/"))
                    if info.is_dir() or parts.suffix.lower() not in SUPPORTED or parts.name.startswith("~$"):
                        continue
                    if parts.is_absolute() or ".." in parts.parts or any(":" in p for p in parts.parts) or info.flag_bits & 1:
                        summary.errors.append(parts.name + ": đường dẫn ZIP hoặc mã hóa không được hỗ trợ.")
                        continue
                    if summary.added + summary.skipped >= MAX_ENTRIES:
                        summary.errors.append("Đã đạt giới hạn 5.000 hồ sơ mỗi lần nhập.")
                        break
                    origin = "drive:" + drive_id if drive_id else "zip:" + str(path.resolve())
                    identity = hashlib.sha256(f"{origin}\n{info.filename}\n{info.CRC}\n{info.file_size}".encode()).hexdigest()
                    added = self._insert(identity=identity, name=parts.name, archive=str(path.resolve()) if path else "",
                                         member=info.filename, drive_id=drive_id, size=info.file_size, crc=info.CRC,
                                         status="large" if info.file_size > MAX_DOCUMENT_BYTES else "archive",
                                         search_text=normalize(info.filename))
                    summary.added += int(added)
                    summary.skipped += int(not added)
                    if progress and index % 10 == 0:
                        progress(f"Đã lập danh mục {summary.added + summary.skipped} hồ sơ trong ZIP…")
            return summary
        except UserError:
            raise
        except (OSError, zipfile.BadZipFile, ValueError) as exc:
            raise UserError("Chưa đọc được ZIP hồ sơ. Kiểm tra file hoặc chọn một thư mục đã giải nén.") from exc

    def materialize(self, identity: int, progress=None) -> Path:
        item = self.get(identity)
        if item["size"] > MAX_DOCUMENT_BYTES:
            raise UserError("Hồ sơ vượt 40 MB. Hãy tải bản gốc và tách thành các phần nhỏ trước khi xử lý.")
        if item["path"]:
            path = Path(item["path"])
            if path.is_file() and path.stat().st_size <= MAX_DOCUMENT_BYTES:
                if item["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest():
                    return path
                raise UserError("File hồ sơ đã thay đổi từ lúc nhập. Nhập lại file để dùng đúng phiên bản mới.")
            if not item["member"]:
                raise UserError("Không còn tìm thấy hồ sơ gốc. Hãy nhập lại đúng file hoặc thư mục.")
        if progress:
            progress("Đang lấy riêng hồ sơ được chọn; không tải cả bộ ZIP…")
        try:
            archive = open_drive_zip(item["drive_id"]) if item["drive_id"] else zipfile.ZipFile(item["archive"])
            with archive:
                info = archive.getinfo(item["member"])
                if info.file_size != item["size"] or info.CRC != item["crc"] or info.file_size > MAX_DOCUMENT_BYTES:
                    raise UserError("Nội dung ZIP đã thay đổi. Hãy nhập lại danh mục để chọn đúng hồ sơ.")
                with archive.open(info) as handle:
                    data = handle.read(MAX_DOCUMENT_BYTES + 1)
                if len(data) != info.file_size:
                    raise UserError("Hồ sơ trong ZIP chưa đầy đủ hoặc vượt giới hạn.")
            digest = hashlib.sha256(data).hexdigest()
            folder = self.store.directory / "library_sources"
            folder.mkdir(exist_ok=True)
            target = folder / (digest[:24] + Path(item["name"]).suffix.lower())
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise UserError("Bản sao hồ sơ đã bị thay đổi. Chưa ghi đè; cần kiểm tra thư mục dữ liệu.")
            else:
                with target.open("xb") as handle:
                    handle.write(data)
            try:
                text, pages, status = index_text(target)
            except (UserError, OSError, ValueError):
                text, pages, status = "", None, "unreadable"
            with self.store.connect() as conn:
                conn.execute("UPDATE library_documents SET path=?,sha256=?,text=?,pages=?,status=?,search_text=? WHERE id=?",
                             (str(target), digest, text, pages, status, normalize(item["member"] + " " + item["name"] + " " + text), identity))
            return target
        except UserError:
            raise
        except Exception as exc:
            raise UserError("Chưa lấy được hồ sơ đã chọn. Kiểm tra mạng hoặc vị trí ZIP rồi thử lại.") from exc

    def attach_template(self, identity: int, draft, template: Path):
        text = "\n".join(anchor.text for anchor in draft.anchors)
        item = self.get(identity)
        if item["sha256"] and item["sha256"] != draft.sha256:
            raise UserError("Hồ sơ nguồn và mẫu vừa tạo không cùng phiên bản.")
        with self.store.connect() as conn:
            conn.execute("UPDATE library_documents SET template_path=?,text=?,search_text=?,status='template' WHERE id=?",
                         (str(template), text, normalize(item["member"] + " " + item["name"] + " " + text), identity))


def index_text(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".docx":
        check_docx(path)
        try:
            anchors = anchors_from_word(path.read_bytes())
        except UserError:
            return "", None, "scan"
        return "\n".join(a.text for a in anchors), None, "text"
    if suffix == ".xlsx":
        with zipfile.ZipFile(path) as archive:
            if sum(i.file_size for i in archive.infolist()) > 80_000_000:
                raise UserError("Excel vượt giới hạn nội dung giải nén.")
        book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        values = []
        total = 0
        try:
            for sheet in book.worksheets[:10]:
                for row in sheet.iter_rows(max_row=1000, max_col=30, values_only=True):
                    line = " | ".join(str(cell)[:1000] for cell in row if cell is not None)
                    total += len(line)
                    if total > 150_000:
                        return "\n".join(values), None, "text"
                    values.append(line)
        finally:
            book.close()
        return "\n".join(values), None, "text"
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            return "", None, "encrypted"
        if len(reader.pages) > 40:
            return "", len(reader.pages), "long"
        parts = []
        total = 0
        for page in reader.pages:
            contents = page.get_contents()
            if contents and len(contents.get_data()) > 8_000_000:
                return "", len(reader.pages), "complex"
            text = page.extract_text() or ""
            total += len(text)
            parts.append(text[:max(0, 150_000 - sum(map(len, parts)))])
            if total >= 150_000:
                break
        text = "\n".join(parts)
        return text, len(reader.pages), "text" if len(text.strip()) >= 50 else "scan"
    except Exception as exc:
        raise UserError("Chưa đọc được PDF để lập chỉ mục.") from exc
