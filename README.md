# Copy Folder Google Drive to Google Drive - 1TouchPro
<a href="https://colab.research.google.com/github/nqthaivl/Copy-Folder-Google-Drive-to-Google-Drive/blob/main/Copy_Folder_Google_Drive_to_Google_Drive.ipynb"><img data-canonical-src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab" src="https://camo.githubusercontent.com/f5e0d0538a9c2972b5d413e0ace04cecd8efd828d133133933dfffec282a4e1b/68747470733a2f2f636f6c61622e72657365617263682e676f6f676c652e636f6d2f6173736574732f636f6c61622d62616467652e737667"></a>

## Giới thiệu

Chào mừng bạn đến với dự án "Copy Folder Google Drive to Google Drive - 1TouchPro". Dự án này giúp bạn sao chép toàn bộ nội dung của một thư mục trên Google Drive sang một thư mục khác, trên cùng tài khoản hoặc giữa các tài khoản Google Drive khác nhau.

## Tính năng chính

- Sao chép đệ quy toàn bộ file và thư mục con từ nguồn sang đích.
- Hỗ trợ sao chép giữa các tài khoản và shared drive (`supportsAllDrives`).
- **Tự xử lý shortcut:** shortcut được phân giải về file gốc để copy đúng nội dung thật; shortcut hỏng sẽ được bỏ qua.
- **Gộp vào thư mục đích có sẵn:** nếu thư mục con đã tồn tại ở đích thì copy gộp vào đó thay vì tạo thư mục trùng tên.
- **Bỏ qua file/thư mục đã tồn tại** ở đích (chạy lại không bị nhân đôi), giữ đúng cả file trùng tên.
- Lọc bỏ file/thư mục theo chuỗi loại trừ do bạn nhập.
- Chọn khoảng trang (`Từ trang`/`Đến trang`) để sao chép một phần thư mục lớn.
- Giới hạn tổng dung lượng mỗi lần chạy (mặc định **750 GB** — đúng bằng hạn mức tải lên/ngày của Google).
- Tự thử lại khi gặp lỗi tạm thời (rate limit, lỗi 5xx) với backoff lũy thừa kèm jitter.
- **Ghi log tiến độ và tiếp tục dở dang (resume)** — kể cả khi đổi sang tài khoản khác.
- **Copy song song nhiều luồng** (mặc định 4 luồng, chỉnh được) để tăng tốc rõ rệt với thư mục nhiều file.
- **Tổng kết file lỗi cuối phiên** — liệt kê các file copy không thành công (không phải do quota) để bạn biết và lần chạy sau tự thử lại.

## Cơ chế log & tiếp tục copy (resume) — quan trọng

Google giới hạn khoảng **750 GB tải lên mỗi ngày cho mỗi tài khoản** (bản sao server-side cũng bị tính). Khi chạm giới hạn, công cụ sẽ **dừng sạch** và ghi lại tiến độ vào một file log đặt ngay trong **thư mục đích**.

Nhờ vậy bạn có thể:

1. Dùng **tài khoản A** copy đến khi đạt giới hạn 750 GB (hoặc đụng quota thật của Google).
2. Đổi sang **tài khoản B** (hoặc C, D...) và chạy lại — công cụ đọc log, bỏ qua những file A đã copy và **copy tiếp phần còn lại**.
3. Lặp lại cho đến khi hiện thông báo `All files processed. Copy complete ✅`.

Cách hoạt động của log:

- Mỗi tài khoản ghi **một file log riêng** trong thư mục đích, đặt tên dạng `.gdrive_copy_resume.<tài-khoản>.json`. (Mỗi tài khoản ghi log của chính mình để tránh lỗi quyền khi ghi đè file của tài khoản khác.)
- Khi khởi động, công cụ **đọc và gộp tất cả các file log** để biết chính xác file nào đã được copy bởi bất kỳ tài khoản nào.
- Log dùng **ID gốc của file** (không dùng tên), nên việc tiếp tục giữa các tài khoản luôn chính xác, không trùng, không sót.
- Log được lưu định kỳ trong lúc chạy và lưu lần cuối khi kết thúc, nên ít bị mất tiến độ nếu Colab ngắt giữa chừng.
- File log chỉ chứa danh sách ID file (không chứa nội dung), và được tự cấp quyền "ai có link cũng đọc được" để mọi tài khoản đều truy cập được.

> **Bắt buộc để chạy nhiều tài khoản:**
> - Tất cả tài khoản phải copy vào **cùng một thư mục đích** (cùng link "Your drive").
> - Thư mục đích phải được **chia sẻ với quyền Editor (toàn quyền)** cho tất cả các tài khoản sẽ dùng, hoặc đặt trong một **Shared Drive** mà các tài khoản đều là thành viên. Nếu không, các tài khoản sẽ không đọc được log của nhau.

## Hướng dẫn sử dụng

### 1. Yêu cầu

- Tài khoản Google.
- Google Colab (hoặc môi trường hỗ trợ IPython Notebook).
- Không cần cài thêm thư viện — tất cả đã có sẵn trong Colab.

### 2. Chuẩn bị thư mục đích (cho trường hợp nhiều tài khoản)

1. Tạo (hoặc chọn) một thư mục đích trên Google Drive.
2. Chia sẻ thư mục đó với **tất cả** các tài khoản bạn định dùng, đặt quyền **Người chỉnh sửa (Editor)**.
3. Dùng cùng một link thư mục đích này cho mọi tài khoản.

### 3. Nhập thông tin đầu vào (cell **Input**)

- **Your drive:** Link thư mục đích (nơi nhận file).
- **Shared drive:** Link thư mục nguồn (nơi lấy file).
- **Từ trang / Đến trang:** Khoảng trang cần copy. Đặt `0` để không giới hạn phân trang.
- **Tổng dung lượng tối đa (GB):** Hạn mức mỗi lần chạy. Mặc định `750`. Đây là ngân sách **của riêng lần chạy hiện tại** (đặt lại về 0 mỗi lần chạy), không cộng dồn qua các ngày — khớp với hạn mức 750 GB/ngày của Google.
- **Bỏ file, folder có chứa nội dung:** Các chuỗi loại trừ, phân tách bằng dấu phẩy.
- **Số luồng song song:** Số file copy đồng thời. Mặc định `4` (giống rclone). Đặt `1` để chạy tuần tự như trước; tăng lên (vd 8) để nhanh hơn, nhưng dễ chạm rate-limit hơn (cơ chế tự thử lại sẽ gánh).

### 4. Chạy (cell **Run**)

Chạy cell **Run**, xác thực khi được hỏi, quá trình copy sẽ bắt đầu. Cell sẽ tự đọc giá trị từ các ô nhập:

```python
destDriveLink = dest_text.value
sourceDriveLink = source_text.value
fromPage = _parse_int(from_page_text.value, 0)
toPage = _parse_int(to_page_text.value, 0)

downloader = DownloadFromDrive()
downloader._limit_size = _parse_float(max_download_size_text.value, 0)
downloader._workers = max(1, _parse_int(workers_text.value, DEFAULT_WORKERS))
downloader.excluded_strings = [ext.strip() for ext in exclude_str_text.value.split(",") if ext.strip()]
downloader.copy_drive_to_drive(destDriveLink, sourceDriveLink, fromPage, toPage)
```

### 5. Khi đạt giới hạn — đổi tài khoản để copy tiếp

Khi đạt 750 GB hoặc đụng quota của Google, cell sẽ in thông báo dừng và nhắc bạn tiếp tục. Để copy tiếp bằng tài khoản khác:

1. Vào **Runtime > Disconnect and delete runtime** (ngắt kết nối Colab).
2. Kết nối lại và chạy lại cell **Run**.
3. Khi được hỏi xác thực, đăng nhập bằng **tài khoản tiếp theo** (B, C, D...).
4. Công cụ tự đọc log, bỏ qua phần đã copy và làm tiếp phần còn lại.

> Lưu ý: làm **tuần tự** từng tài khoản (A xong mới đến B). Không nên chạy nhiều tài khoản đồng thời trên cùng thư mục đích vì có thể gây copy trùng.

## Lưu ý & giới hạn

- File Google tài liệu gốc (Google Docs/Sheets/Slides) không có dung lượng báo cáo (`size = 0`), nên không được tính vào hạn mức GB. Việc dừng theo quota thật của Google vẫn hoạt động bình thường.
- Khi chạy **song song nhiều luồng**, các dòng log in ra sẽ xen kẽ giữa các file (không còn theo thứ tự tuần tự) — đây là bình thường. Việc duyệt thư mục con vẫn theo thứ tự, chỉ phần copy file là chạy song song.
- Tăng số luồng quá cao có thể khiến Google trả về lỗi rate-limit thường xuyên hơn; công cụ tự thử lại với backoff, nhưng nếu thấy nhiều cảnh báo "Lỗi tạm thời" thì nên giảm số luồng.
- Mỗi lần resume, công cụ vẫn duyệt lại toàn bộ cây thư mục nguồn (chỉ bỏ qua phần đã copy), nên với thư mục rất lớn bước này có thể mất thời gian.
- Khi copy xong hoàn toàn, bạn có thể xóa các file log `.gdrive_copy_resume.*.json` trong thư mục đích.
- Không có bước build hay test tự động — notebook được chạy lần lượt từng cell một cách tương tác.
