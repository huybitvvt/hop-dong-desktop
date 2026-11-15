# Hợp Đồng — Bản Windows

1. Giải nén toàn bộ `HopDongAI-Windows.zip` và mở `HopDongAI/HopDongAI.exe`. Giữ thư mục `_internal` cạnh `.exe`.
2. **Cài đặt:** nhập API key của máy nhận, giữ model `gemini-3.5-flash-lite`, lưu và kiểm tra kết nối. API key không nằm trong ZIP.
3. **Khách hàng:** nhập Excel hoặc PDF/Word, chọn đúng bên và kiểm tra trước khi lưu.
4. **Mẫu hợp đồng:** chọn **Tạo mẫu từ Word/PDF** để dùng mẫu trống chưa có biến hoặc hợp đồng đã điền. Xác nhận bên đối tác, kiểm tra vùng tự điền và xem Word trước khi lưu. Chỗ còn sót dùng **Thêm chỗ trống**. Mẫu mới mặc định là nháp; PDF dựng lại cần đối chiếu nội dung/bố cục.
5. **Tạo hợp đồng:** nhập đối tác và nội dung yêu cầu, chọn mẫu/khách nếu app hỏi, bổ sung trường còn thiếu rồi mở Word. File lưu trên Desktop hoặc nơi đã chọn trong Cài đặt.

Khách hàng hỗ trợ các trường thông tin riêng: thêm cột Excel, lấy từ hợp đồng hoặc nhấp đúp khách → **+ Thêm trường**. Cửa sổ bổ sung hợp đồng có **+ Thêm thông tin**; trường đã có trong mẫu được điền đúng ô, trường mới ghi ở mục Thông tin bổ sung cuối Word.

**Thư viện hồ sơ** hỗ trợ thư mục, ZIP và ZIP Drive công khai; chỉ hồ sơ được chọn mới được tải/xử lý. Lập danh mục không gửi cả bộ hồ sơ đến API.

Dữ liệu cũ ở `%LOCALAPPDATA%\HopDongAI` được giữ khi thay bộ chương trình. Profile thử trong workspace là `private/client-preview-data`, tách riêng. Không xóa hoặc thay các thư mục dữ liệu khi cập nhật ứng dụng.

Máy nhận không cần Python/GPU/model local. Muốn xem file cần trình đọc DOCX. Tài liệu chi tiết: `HUONG-DAN.md`; source và cách build trong `source/`; license thư viện trong `licenses/`.

Bản này dùng Gemini API, không có model OCR/LLM chạy trên máy hoặc màn hình đếm token. Kết quả đọc giống hệt được lưu trên máy để tránh gọi lại khi không cần thiết. App không ký số hoặc gửi hợp đồng ra ngoài.
