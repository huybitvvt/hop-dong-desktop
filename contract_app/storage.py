from __future__ import annotations

from dataclasses import asdict, fields
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys
import re

from .models import Customer, UserError
from .money import normalize

DEFAULT_MODEL = "gemini-3.5-flash-lite"


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])) / "assets" / name


def app_directory() -> Path:
    if override := os.environ.get("HOPDONG_DATA_DIR"):
        return Path(override).resolve()
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share"))) / "HopDongAI"


def desktop_directory() -> Path:
    if os.name == "nt":
        import ctypes
        import uuid
        guid = (ctypes.c_ubyte * 16).from_buffer_copy(uuid.UUID("B4BFCC3A-DB2C-424C-B029-7FE99A87C641").bytes_le)
        result = ctypes.c_wchar_p()
        shell = ctypes.windll.shell32
        shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        shell.SHGetKnownFolderPath.restype = ctypes.c_long
        status = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(result))
        if status == 0:
            try:
                return Path(result.value)
            finally:
                ctypes.windll.ole32.CoTaskMemFree(ctypes.cast(result, ctypes.c_void_p))
        raise UserError("Không tìm được thư mục Desktop. Hãy chọn thư mục xuất trong Cài đặt.")
    return Path.home() / "Desktop"


class Store:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or app_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.templates = self.directory / "templates"
        self.templates.mkdir(exist_ok=True)
        self.database = self.directory / "local.sqlite3"
        self.config_file = self.directory / "settings.json"
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(customers)")}
            if "origin" not in columns:
                conn.execute("ALTER TABLE customers ADD COLUMN origin TEXT NOT NULL DEFAULT 'excel'")
            if "source_path" not in columns:
                conn.execute("ALTER TABLE customers ADD COLUMN source_path TEXT NOT NULL DEFAULT ''")
            conn.execute("CREATE TABLE IF NOT EXISTS customer_imports (id INTEGER PRIMARY KEY, created TEXT NOT NULL, customer_id INTEGER NOT NULL, source_path TEXT NOT NULL, sha256 TEXT NOT NULL, previous_data TEXT, approved_data TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, created TEXT NOT NULL, company TEXT NOT NULL, amount INTEGER NOT NULL, path TEXT NOT NULL, template TEXT NOT NULL, demo INTEGER NOT NULL DEFAULT 0)")

    def connect(self):
        return sqlite3.connect(self.database)

    def config(self) -> dict:
        base = {"model": DEFAULT_MODEL, "output_directory": "", "customer_source": "", "source_signature": None, "demo_data": False, "seller": {}}
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError
                base.update({k: v for k, v in data.items() if k in base})
            except (ValueError, OSError):
                raise UserError("Không đọc được settings.json. Hãy kiểm tra file cấu hình trong thư mục dữ liệu.")
        return base

    def save_config(self, data: dict):
        allowed = {k: v for k, v in data.items() if k in self.config()}
        temporary = self.config_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(allowed, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.config_file)

    def customers(self) -> list[Customer]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id,data FROM customers ORDER BY id").fetchall()
        return [Customer(id=row[0], **json.loads(row[1])) for row in rows]

    def replace_customers(self, customers: list[Customer]):
        if not customers:
            raise UserError("Danh sách khách hàng trống; dữ liệu hiện có được giữ lại.")
        with self.connect() as conn:
            conn.execute("DELETE FROM customers")
            for customer in customers:
                values = asdict(customer)
                values.pop("id")
                conn.execute("INSERT INTO customers(data) VALUES (?)", (json.dumps(values, ensure_ascii=False),))

    @staticmethod
    def same_company(a: Customer, b: Customer) -> bool:
        if a.tax_code and b.tax_code:
            return re.sub(r"[\s-]", "", a.tax_code).lower() == re.sub(r"[\s-]", "", b.tax_code).lower()
        return bool(a.company_name and b.company_name) and normalize(a.company_name) == normalize(b.company_name)

    @staticmethod
    def customer_values(customer, previous=None):
        from .customer_fields import clean_extra_fields, merge_extra_fields
        incoming = asdict(customer)
        incoming.pop("id")
        incoming["extra_fields"] = clean_extra_fields(incoming.get("extra_fields", {}))
        if previous:
            old = asdict(previous)
            incoming = {key: (merge_extra_fields(previous.extra_fields, value) if key == "extra_fields" else value if value.strip() else old[key]) for key, value in incoming.items()}
        return incoming

    def customer_field_labels(self):
        from .customer_fields import extra_field_labels
        return extra_field_labels(self.customers())

    def save_customer_edit(self, customer: Customer, target_id=None):
        from .contract_import import validate_import_customer
        validate_import_customer(customer)
        if any(other.id != target_id for other in self.matching_customers(customer)):
            raise UserError("Đã có khách hàng cùng mã số thuế hoặc tên công ty. Mở bản ghi đó để cập nhật.")
        values = self.customer_values(customer)
        with self.connect() as conn:
            if target_id is None:
                target_id = conn.execute("INSERT INTO customers(data,origin) VALUES (?,'manual')", (json.dumps(values, ensure_ascii=False),)).lastrowid
            else:
                changed = conn.execute("UPDATE customers SET data=?,origin=CASE WHEN origin='contract' THEN origin ELSE 'manual' END WHERE id=?", (json.dumps(values, ensure_ascii=False), target_id))
                if changed.rowcount != 1:
                    raise UserError("Khách hàng đã thay đổi. Đóng cửa sổ và chọn lại.")
        return Customer(id=target_id, **values)

    def matching_customers(self, incoming: Customer) -> list[Customer]:
        return [customer for customer in self.customers() if self.same_company(customer, incoming)]

    def contract_customers(self) -> list[Customer]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id,data FROM customers WHERE origin IN ('contract','manual') ORDER BY id").fetchall()
        return [Customer(id=row[0], **json.loads(row[1])) for row in rows]

    def replace_excel_customers(self, customers: list[Customer], source_path: str = ""):
        if not customers:
            raise UserError("Danh sách Excel trống; dữ liệu hiện có được giữ lại.")
        with self.connect() as conn:
            protected = [Customer(id=row[0], **json.loads(row[1])) for row in conn.execute("SELECT id,data FROM customers WHERE origin IN ('contract','manual')")]
            previous_excel = [Customer(id=row[0], **json.loads(row[1])) for row in conn.execute("SELECT id,data FROM customers WHERE origin='excel'")]
            conn.execute("DELETE FROM customers WHERE origin='excel'")
            for customer in customers:
                matches = [existing for existing in protected if self.same_company(customer, existing)]
                if matches:
                    if len(matches) == 1:
                        # Confirmed/manual values win; new Excel fields are retained.
                        values = self.customer_values(matches[0], customer)
                        conn.execute("UPDATE customers SET data=? WHERE id=?", (json.dumps(values, ensure_ascii=False), matches[0].id))
                    continue
                matches = [existing for existing in previous_excel if self.same_company(customer, existing)]
                if not matches and not customer.company_name and not customer.tax_code and customer.contact_name:
                    matches = [existing for existing in previous_excel if not existing.company_name and not existing.tax_code and normalize(existing.contact_name) == normalize(customer.contact_name)]
                    if len(matches) > 1:
                        raise UserError("Có nhiều khách hàng cùng tên trong dữ liệu cũ. Bổ sung công ty hoặc mã số thuế trước khi nhập lại để tránh gộp nhầm.")
                values = self.customer_values(customer, matches[0] if len(matches) == 1 else None)
                conn.execute("INSERT INTO customers(data,origin,source_path) VALUES (?,'excel',?)", (json.dumps(values, ensure_ascii=False), source_path))

    def save_contract_customer(self, customer: Customer, source_path: str, sha256: str, target_id: int | None = None) -> Customer:
        matches = self.matching_customers(customer)
        if target_id is not None and target_id not in {c.id for c in matches}:
            raise UserError("Bản ghi cần cập nhật đã thay đổi; hãy kiểm tra lại khách hàng trước khi lưu.")
        if target_id is None and len(matches) > 1:
            raise UserError("Có nhiều bản ghi cùng công ty. Chọn bản ghi cần cập nhật trước khi lưu.")
        if target_id is None and len(matches) == 1:
            target_id = matches[0].id
        previous = next((c for c in matches if c.id == target_id), None)
        incoming = self.customer_values(customer, previous)
        if previous:
            aliases = [name.strip() for name in (previous.aliases + ";" + customer.aliases).split(";") if name.strip()]
            incoming["aliases"] = ";".join(dict.fromkeys(aliases))
        cfg = self.config()
        with self.connect() as conn:
            if cfg.get("demo_data") and cfg.get("customer_source") == "Danh sách minh họa đi kèm ứng dụng":
                conn.execute("DELETE FROM customers WHERE origin='excel'")
                if previous and not conn.execute("SELECT 1 FROM customers WHERE id=?", (target_id,)).fetchone():
                    target_id = None
            payload = json.dumps(incoming, ensure_ascii=False)
            if target_id is None:
                cursor = conn.execute("INSERT INTO customers(data,origin,source_path) VALUES (?,'contract',?)", (payload, source_path))
                target_id = cursor.lastrowid
            else:
                conn.execute("UPDATE customers SET data=?,origin='contract',source_path=? WHERE id=?", (payload, source_path, target_id))
            conn.execute("INSERT INTO customer_imports(created,customer_id,source_path,sha256,previous_data,approved_data) VALUES (?,?,?,?,?,?)", (datetime.now().isoformat(timespec="seconds"), target_id, source_path, sha256, json.dumps(asdict(previous), ensure_ascii=False) if previous else None, payload))
        return Customer(id=target_id, **incoming)

    def add_history(self, result):
        with self.connect() as conn:
            conn.execute("INSERT INTO history(created,company,amount,path,template,demo) VALUES (?,?,?,?,?,?)", (datetime.now().isoformat(timespec="seconds"), result.customer.company_name, result.amount, str(result.path), result.template_name, int(result.demo)))

    def history(self) -> list[dict]:
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT 100")]


class Credentials:
    service = "HopDongAI.Gemini"
    account = "api-key"

    def __init__(self):
        self.session_key = ""

    def get(self) -> str:
        if self.session_key:
            return self.session_key
        if key := os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            return key.strip()
        try:
            import keyring
            return keyring.get_password(self.service, self.account) or ""
        except Exception:
            return ""

    def set(self, key: str, remember: bool):
        key = key.strip()
        if remember:
            try:
                import keyring
                # Never accept third-party plaintext backends.
                backend = keyring.get_keyring()
                if os.name == "nt" and not type(backend).__module__.startswith("keyring.backends.Windows"):
                    raise RuntimeError("Unsupported credential backend")
                keyring.set_password(self.service, self.account, key)
            except Exception as exc:
                raise UserError("Không lưu được vào kho khóa hệ điều hành. Bỏ chọn Ghi nhớ để chỉ dùng trong phiên này.") from exc
        else:
            self.forget()
        self.session_key = key

    def forget(self):
        self.session_key = ""
        try:
            import keyring
            keyring.delete_password(self.service, self.account)
        except keyring.errors.PasswordDeleteError:
            # A missing credential is already the requested state.
            return
        except Exception as exc:
            raise UserError("Không xóa được key trong kho thông tin xác thực Windows. Kiểm tra Credential Manager.") from exc
