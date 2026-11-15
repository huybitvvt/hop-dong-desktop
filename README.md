# Hợp Đồng

Tải bản Windows tại **[GitHub Releases](https://github.com/huybitvvt/hop-dong-desktop/releases/latest)**:

- **HopDongAI-Windows.zip:** bản chính để dùng với dữ liệu của khách hàng.
- **HopDong-DEMO-Linh-Hoat-20261115.zip:** bản demo riêng, có 3 khách và 1 mẫu giả lập.

Giải nén toàn bộ trước khi chạy. Máy nhận không cần Python; nhập Gemini API key riêng trong **Cài đặt**. Bản chính giữ dữ liệu đã có tại `%LOCALAPPDATA%\HopDongAI` khi cập nhật.

Ứng dụng desktop Windows: đọc hồ sơ, chuẩn bị mẫu tái sử dụng, tìm khách hàng từ câu chat và xuất hợp đồng Word. Dùng Gemini API, model mặc định **`gemini-3.5-flash-lite`**. Khách hàng, mẫu, tra cứu và điền Word lưu/xử lý trên máy. Bản này không chạy model AI local.

## Mở ứng dụng

- Giải nén toàn bộ `HopDongAI-Windows.zip`, mở `HopDongAI/HopDongAI.exe`. Giữ `_internal` cạnh `.exe`; máy nhận không cần Python.
- Trong workspace: `Run-App.cmd` ưu tiên bản `.exe`. Chạy source: `.venv\Scripts\python.exe main.py`.
- `Chay-thu-ho-so-khach.cmd` dùng profile thử riêng `private/client-preview-data`.

## Thiết lập

1. Trong **Cài đặt**, nhập Gemini API key, giữ model ID `gemini-3.5-flash-lite`.
2. Chọn **Lưu kết nối**, rồi **Kiểm tra kết nối**. Kiểm tra có gọi API thật và có thể tính phí.
3. Nhập thông tin công ty, chọn nơi xuất hoặc để trống để dùng Desktop thực tế của Windows. Bấm **Lưu cài đặt tài liệu**.

Key được ghi nhớ bằng Windows Credential Manager; bỏ Ghi nhớ để chỉ dùng trong phiên. Không lưu key vào JSON/source/ZIP. Máy nhận cần tự nhập key; key trên máy phát triển không đi theo bản phát hành. Hỗ trợ biến môi trường `GEMINI_API_KEY` / `GOOGLE_API_KEY`. Không tự đổi model khi hết quota hoặc thiếu quyền.

## Tạo mẫu từ Word/PDF có sẵn

1. Mở **Mẫu hợp đồng → Tạo mẫu từ Word/PDF**, chọn mẫu trống chưa có biến hoặc hợp đồng đã điền (`.docx`/PDF, kể cả scan).
2. Chọn **Bên A/Bên B là đối tác cần thay thông tin**. Bên còn lại đã có dữ liệu thì giữ nguyên; chỗ trống lấy từ **Cài đặt → Thông tin công ty của bạn** hoặc hỏi bổ sung.
3. Gemini đọc tài liệu và đề xuất vùng tự điền. Word giữ định dạng chữ, bảng, đầu/chân trang khi thay dữ liệu. PDF được dựng lại thành Word chỉnh sửa được, bố cục có thể khác nguồn.
4. Kiểm tra bảng hai cột **Chỗ sẽ điền trong hợp đồng → Thông tin lấy để điền**. Tên như **Bên A · Địa chỉ → Khách hàng · Địa chỉ** cho biết rõ vùng nào lấy dữ liệu từ đâu; phía trên ghi vai trò khách hàng/công ty của bạn. Chọn dòng để xem chỗ điền tô xanh trong đoạn gốc. Muốn chọn thêm vùng hoặc sửa nội dung nguyên văn, mở **Chỉnh chi tiết** rồi **Thêm chỗ trống** hoặc bôi đen → **Thêm vùng đang bôi đen**. Các vùng không được chồng nhau.
5. **Mở bản gốc** và **Xem mẫu Word trước khi lưu** để đối chiếu. File xem trước chỉ dùng để xem; sửa Word xem trước không tự cập nhật bảng đề xuất.
6. **Lưu mẫu tái sử dụng**. Mặc định là **nháp**, đầu ra có tên file/giao diện ghi bản thử. Chỉ bỏ trạng thái nháp sau khi đối chiếu đầy đủ.

Ảnh, dấu/chữ ký không mang sang mẫu mới. Bản nguồn được giữ riêng. Bước gắn biến không tự viết lại điều khoản; PDF dựng lại vẫn cần kiểm tra chữ và ngắt trang. Chỗ `[KHÔNG ĐỌC RÕ]` chưa xử lý không được lưu thành mẫu chính thức. Word chỉ chứa ảnh cần lưu thành PDF để dựng mẫu.

Mẫu trống và hợp đồng đã điền đều dùng được qua bước này, không cần tự chèn biến bằng tay. **Nhập mẫu có biến** dành cho Word đã chuẩn bị sẵn; chọn Word chưa có biến sẽ chuyển sang đề xuất mẫu. Nếu một ô trống thiếu nhãn/ngữ cảnh, chọn trường thủ công khi duyệt; app không tự bịa nội dung còn thiếu.

Giới hạn: 10 MB/file, 40 trang PDF. Chuẩn bị mẫu cần Internet/API key và chỉ làm một lần; sau đó dùng mẫu đã lưu để tạo hợp đồng mới.

## Thư viện hồ sơ

- **Nhập thư mục**: lập danh mục PDF, Word, Excel trên máy; file có chữ có thể tìm theo nội dung.
- **Nhập ZIP**: đọc danh mục, chỉ lấy riêng hồ sơ được chọn, không giải nén toàn bộ.
- **Nhập ZIP từ Drive**: link ZIP công khai trên Google Drive, tải từng phần. Nếu Drive không hỗ trợ, tải ZIP về rồi nhập.
- Tìm theo tên file, thư mục đối tác hoặc chữ đã đọc. PDF scan ban đầu tìm theo tên; sau khi chuẩn bị mẫu có thể tìm nội dung đã đọc.
- Chọn **Mở hồ sơ**, **Lấy thông tin khách hàng** hoặc **Tạo mẫu từ hồ sơ**.

Lập danh mục không gọi Gemini hoặc tự tạo khách hàng. Tối đa 5.000 hồ sơ mỗi lần nhập. File trên 40 MB vẫn hiển thị nhưng cần tách trước khi xử lý; giới hạn gửi Gemini vẫn là 10 MB/40 trang. Không hỗ trợ ZIP có mật khẩu. Danh mục không đồng nghĩa đã OCR/huấn luyện toàn bộ hồ sơ.

## Khách hàng

**Từ hợp đồng:** Khách hàng → Nhập hợp đồng (hoặc chọn từ Thư viện) → Gemini tách các bên → chọn đúng đối tác → kiểm tra/sửa → **Lưu khách hàng**. Hủy không lưu khách/bản sao nguồn. Trùng MST sẽ cập nhật bản ghi có sẵn; ô trống giữ thông tin cũ. Người liên hệ không tự lấy từ người đại diện. Khác biệt người đại diện/người ký được ghi để đối chiếu. **Đọc lại PDF gốc bằng Gemini** bỏ kết quả đọc đã lưu và yêu cầu đọc mới.

**Từ Excel:** tải Excel mẫu hoặc dùng bảng riêng rồi Nhập Excel. Chỉ cần ít nhất một cột nhận diện: **Tên công ty**, **Tên liên hệ/Tên khách hàng** hoặc **Mã số thuế**. Những thông tin khác có thể thiếu hoặc thêm cột tùy hồ sơ, như Số CCCD, Ngày/Nơi cấp, Email kế toán, Chi nhánh, Giấy ủy quyền. App giữ các cột bổ sung, số 0 đầu và ngày tháng. Không nhập công thức hoặc bảng theo dõi hợp đồng thay cho danh bạ khách hàng.

**Thêm/sửa trực tiếp:** bấm **Thêm khách hàng** hoặc nhấp đúp khách trong bảng → **+ Thêm trường** → nhập tên trường và giá trị → **Lưu khách hàng**. Có thể sửa hoặc bỏ trường bổ sung. Các cột bổ sung xuất hiện trong danh sách; kéo thanh cuộn ngang để xem. Hủy không lưu thay đổi. Khi nhập lại Excel/hợp đồng ít thông tin hơn, giá trị trống không xóa thông tin đã có của khách nhận diện trùng; thông tin đã xác nhận/nhập tay được giữ ưu tiên khi cập nhật Excel.

**Từ hợp đồng có trường khác:** AI giữ các thông tin riêng của từng bên trong phần bổ sung. Bảng đối chiếu có cả giá trị cũ và mới, cùng nút **+ Thêm trường thông tin**. Kiểm tra đúng bên trước khi lưu. Trường bổ sung dùng được trong mẫu Word; thiếu giá trị chỉ hỏi khi mẫu thực sự cần.

Nhập lại Excel chỉ thay phần khách từ Excel, giữ khách đã xác nhận từ hợp đồng; không sửa file gốc. Excel nguồn thay đổi được đọc lại trước khi tạo hợp đồng. Nếu nguồn mất/lỗi, chỉ khách đã xác nhận từ hợp đồng còn được dùng.

## Tạo hợp đồng

1. Mở **Tạo hợp đồng**. Bật **Tự chọn mẫu** để tìm mẫu theo câu chat; nhiều mẫu phù hợp sẽ hỏi lại. Bỏ chọn để chọn mẫu bằng tay.
2. Nhập đối tác, công việc/hàng hóa, số/ngày hợp đồng nếu cần, tiền nếu mẫu có tổng giá trị.
3. **Tạo hợp đồng** hoặc **Ctrl + Enter**. Xác nhận khách khi tên gần giống, bổ sung trường còn thiếu.
4. Mở Word hoặc thư mục xuất; tìm lại trong **Lịch sử**. Mỗi lần xuất có tên riêng, không ghi đè.

Ví dụ với dữ liệu đã nhập của bạn:

> Tạo hợp đồng nguyên tắc mua bán số TEST-001 với công ty ABC, mã số thuế 0123456789. Nội dung hàng hóa: Container các loại phục vụ thi công dự án Y.

Mẫu nguyên tắc theo đơn hàng có thể không có tổng tiền. Có tiền trong yêu cầu nhưng mẫu không có trường tiền sẽ dừng để tránh bỏ sót. Hỗ trợ VND: `1 tỷ`, `1,2 tỷ`, `1 tỷ 200 triệu`, `một tỷ hai trăm triệu`, `1.000.000.000 đồng`. Câu như `1 tỷ 2` cần viết rõ. Không tự tính VAT/đơn giá hoặc thêm điều khoản.

**Chạy ví dụ** dùng dữ liệu minh họa, không gọi API; không thay dữ liệu khách hàng thật.

## Mẫu Word có biến

Hai trường chính: `{{ company_name }}`, `{{ work_description }}`. Mẫu có tổng tiền cần `{{ amount }}`.

| Nhóm | Biến |
|---|---|
| Đối tác | `company_name`, `contact_name`, `tax_code`, `address`, `representative`, `position`, `phone`, `email`, `bank_account`, `bank_name` |
| Hợp đồng | `contract_number`, `contract_date`, `day`, `month`, `year`, `work_description`, `payment_terms`, `duration` |
| Tiền | `amount`, `amount_words`, `amount_number`, `currency` |
| Công ty của bạn | `seller_company`, `seller_tax_code`, `seller_address`, `seller_representative`, `seller_position`, `seller_contact_name`, `seller_phone`, `seller_email`, `seller_bank_account`, `seller_bank_name` |
| Dự án | `project_name`, `project_address` |

Viết mỗi biến trong `{{ ... }}`; sửa bản sao, giữ bản gốc. Biến lạ/thiếu dữ liệu sẽ ngăn xuất Word.

Trường bổ sung có biến riêng, ví dụ `{{ customer_so_cccd }}`. Bước tạo mẫu tự đề xuất biến theo nhãn; trong cửa sổ duyệt có **+ Thêm trường khách hàng** để gán thêm. Khi tạo hợp đồng, cửa sổ bổ sung có **+ Thêm thông tin**: chọn trường hoặc nhập tên mới. Nếu mẫu có ô tương ứng, app điền ô đó; nếu chưa có, thông tin được ghi vào mục **Thông tin bổ sung** cuối file Word. Các giá trị nhập ở bước tạo chỉ áp dụng cho hợp đồng đó; muốn lưu cho những lần sau thì sửa hồ sơ khách hàng.

## Dữ liệu và API

- Profile: `%LOCALAPPDATA%\HopDongAI`; đổi bằng `HOPDONG_DATA_DIR`. Gồm cấu hình không có key, SQLite khách/lịch sử/thư viện, `templates/`, nguồn đã xác nhận và `processing_cache/`.
- Tạo hợp đồng: chỉ gửi câu chat và chỉ dẫn/schema; không gửi danh bạ hoặc mẫu đang điền.
- Nhập khách/chuẩn bị mẫu: gửi nội dung hồ sơ đã chọn đến Gemini; không gửi cả thư mục/ZIP.
- Kết quả đọc hồ sơ, đề xuất mẫu và yêu cầu giống hệt được tái sử dụng trên máy. Đổi file/model/vai trò/yêu cầu có kết quả riêng. Có lựa chọn đọc lại khi cần. Bộ nhớ kết quả không chứa key; không có màn hình đếm token.
- Desktop dùng Windows Known Folder API. Nếu thuộc OneDrive, file có thể được đồng bộ; chọn nơi xuất khác trong Cài đặt nếu cần.
- Giữ bản nháp và đối chiếu trước khi sử dụng thực tế. App không ký số, gửi email hoặc phát hành ra ngoài.

## Phát triển và kiểm thử

Python 3.12, PySide6, google-genai, Pydantic, SQLite, docxtpl/python-docx, openpyxl, RapidFuzz, pypdf, keyring; Noto Sans đóng kèm. Không cần GPU/model local.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools/create_demo.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe main.py
powershell -ExecutionPolicy Bypass -File .\Build.ps1
```

`requirements.lock.txt` ghi các phiên bản đã kiểm tra. Source và hướng dẫn build đi kèm. License ở `THIRD_PARTY_NOTICES.md`, `licenses/`. Hồ sơ khách, profile phát triển, API key và thử nghiệm OCR không được đóng gói.

Giới hạn còn lại: chưa kế thừa ngữ cảnh cho câu sửa rời như “đổi thành 2 tỷ”; chưa đọc mọi scan bằng AI hàng loạt; PDF dựng lại có thể khác bố cục; không tự kiểm chứng thông tin pháp nhân/nội dung pháp lý.
