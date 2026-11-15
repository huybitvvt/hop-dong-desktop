"""Read a public Google Drive ZIP using HTTP ranges, without downloading it all."""
from __future__ import annotations

from html.parser import HTMLParser
import http.cookiejar
import io
import re
import urllib.parse
import urllib.request
import zipfile

from .models import UserError


def drive_file_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{16,100}", value):
        return value
    url = urllib.parse.urlsplit(value)
    if url.scheme != "https" or url.hostname != "drive.google.com":
        raise UserError("Nhập link chia sẻ file ZIP công khai trên drive.google.com.")
    match = re.search(r"/file/d/([A-Za-z0-9_-]{16,100})(?:/|$)", url.path)
    identity = match.group(1) if match else urllib.parse.parse_qs(url.query).get("id", [""])[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", identity):
        raise UserError("Link Drive chưa có mã file hợp lệ. Hãy dùng link của file ZIP, không dùng link thư mục.")
    return identity


def _allowed_url(url):
    parsed = urllib.parse.urlsplit(url)
    hostname = parsed.hostname or ""
    return parsed.scheme == "https" and parsed.port in (None, 443) and not parsed.username and (
        hostname in ("drive.google.com", "drive.usercontent.google.com", "docs.google.com")
        or hostname.endswith(".googleusercontent.com")
    )


class GoogleRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _allowed_url(newurl):
            raise UserError("Drive chuyển đến địa chỉ không hỗ trợ. Hãy tải ZIP về máy rồi nhập file.")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class DownloadForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action, self.values = "", {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "form" and "download" in values.get("action", ""):
            self.action = values["action"]
        if tag == "input" and values.get("name") and self.action:
            self.values[values["name"]] = values.get("value", "")


class RangeFile(io.RawIOBase):
    def __init__(self, opener, url, length):
        self.opener, self.url, self.length, self.position = opener, url, length, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        target = offset + (0 if whence == 0 else self.position if whence == 1 else self.length)
        if target < 0:
            raise ValueError("Negative seek")
        self.position = target
        return target

    def read(self, size=-1):
        size = min(self.length - self.position, self.length if size < 0 else size)
        if size <= 0:
            return b""
        if size > 50_000_000:
            raise UserError("Một phần ZIP quá lớn để đọc trên máy này. Hãy tải và tách bộ hồ sơ.")
        end = self.position + size - 1
        # Defeat caches that ignore the Range request header.
        url = self.url + ("&" if "?" in self.url else "?") + f"range_read={self.position}-{end}"
        request = urllib.request.Request(url, headers={"Range": f"bytes={self.position}-{end}"})
        with self.opener.open(request, timeout=60) as response:
            if response.status != 206 or response.headers.get("Content-Range") != f"bytes {self.position}-{end}/{self.length}":
                raise UserError("Drive không cho tải từng phần. Hãy tải ZIP về máy rồi dùng Nhập ZIP.")
            payload = response.read(size + 1)
        if len(payload) != size:
            raise UserError("Tải thiếu dữ liệu từ Drive. Chưa nhập file; hãy thử lại.")
        self.position += size
        return payload


def open_drive_zip(identity: str):
    identity = drive_file_id(identity)
    opener = urllib.request.build_opener(GoogleRedirects(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    url = "https://drive.usercontent.google.com/download?" + urllib.parse.urlencode({
        "id": identity, "export": "download", "confirm": "t",
    })
    try:
        for _ in range(3):
            request = urllib.request.Request(url, headers={"Range": "bytes=0-0"})
            with opener.open(request, timeout=45) as response:
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes 0-0/(\d+)", content_range)
                if response.status == 206 and match:
                    length = int(match.group(1))
                    if not 22 <= length <= 5_000_000_000:
                        raise UserError("File Drive không phải ZIP hợp lệ hoặc vượt 5 GB.")
                    return zipfile.ZipFile(RangeFile(opener, response.geturl(), length))
                if "text/html" not in response.headers.get("Content-Type", ""):
                    raise UserError("Drive không hỗ trợ đọc ZIP từng phần. Hãy tải ZIP về máy rồi nhập.")
                html = response.read(200_000).decode("utf-8", errors="replace")
            form = DownloadForm()
            form.feed(html)
            if not form.action or not _allowed_url(form.action):
                raise UserError("Chưa đọc được file Drive. Kiểm tra quyền 'Bất kỳ ai có đường liên kết', hoặc tải ZIP về máy.")
            parts = urllib.parse.urlsplit(form.action)
            query = urllib.parse.parse_qsl(parts.query) + list(form.values.items())
            url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), ""))
        raise UserError("Drive yêu cầu xác nhận tải file. Hãy tải ZIP về máy rồi dùng Nhập ZIP.")
    except UserError:
        raise
    except Exception as exc:
        # Never include signed download URLs/cookies in messages or logs.
        raise UserError("Chưa mở được ZIP trên Drive. Kiểm tra mạng/quyền chia sẻ, hoặc tải ZIP về máy để nhập.") from exc
