<div align="center">

# ⚡ GDrive_Turbo_Copy

### Copy nguyên thư mục Google Drive sang Google Drive bằng Google Colab

<a href="https://colab.research.google.com/github/nqthaivl/Copy-Folder-Google-Drive-to-Google-Drive/blob/main/GDrive_Turbo_Copy.ipynb" target="_blank">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab">
</a>

![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Google%20Colab-F9AB00?logo=googlecolab&logoColor=white)
![Google Drive API](https://img.shields.io/badge/Google%20Drive%20API-v3-1FA463?logo=googledrive&logoColor=white)
![Install](https://img.shields.io/badge/C%C3%A0i%20%C4%91%E1%BA%B7t-Kh%C3%B4ng%20c%E1%BA%A7n-success)

**GDrive_Turbo_Copy** giúp sao chép toàn bộ cây thư mục Drive, hỗ trợ Shared Drive, copy nhiều tài khoản nối tiếp, resume tiến độ và copy song song.

</div>

---

## 📑 Mục lục

- [Tổng quan](#-tổng-quan)
- [Tính năng](#-tính-năng)
- [Cách dùng nhanh](#-cách-dùng-nhanh)
- [Tham số đầu vào](#-tham-số-đầu-vào)
- [Chế độ kiểm tra trùng](#-chế-độ-kiểm-tra-trùng)
- [Dry-run](#-dry-run)
- [Resume và đổi nhiều tài khoản](#-resume-và-đổi-nhiều-tài-khoản)
- [Gợi ý cấu hình](#-gợi-ý-cấu-hình)
- [Lưu ý quan trọng](#-lưu-ý-quan-trọng)
- [FAQ](#-faq)

---

## 🎯 Tổng quan

Notebook này dùng **Google Drive API v3** để copy server-side từ một thư mục Google Drive nguồn sang một thư mục Google Drive đích. Công cụ phù hợp khi bạn cần:

- Copy một folder lớn từ tài khoản này sang tài khoản khác.
- Copy dữ liệu từ folder được share vào Drive của bạn.
- Copy Shared Drive hoặc thư mục có nhiều thư mục con.
- Resume khi Colab bị ngắt, khi chạm quota Google Drive, hoặc khi cần đổi tài khoản copy tiếp.

Không cần cài đặt thủ công: các thư viện cần thiết như `googleapiclient`, `google.colab.auth`, `ipywidgets` thường đã có sẵn trong Google Colab.

---

## ✨ Tính năng

| Tính năng | Mô tả |
|---|---|
| 🔁 Copy đệ quy | Copy toàn bộ file và thư mục con từ nguồn sang đích. |
| 📂 Merge thư mục | Nếu thư mục con cùng tên đã có ở đích, công cụ dùng lại thư mục đó thay vì tạo bản trùng. |
| 👥 Hỗ trợ nhiều tài khoản | Mỗi tài khoản có log riêng, khi chạy lại sẽ đọc và gộp log để tiếp tục phần còn thiếu. |
| 🏢 Shared Drive | Dùng `supportsAllDrives=True` và `includeItemsFromAllDrives=True` cho thao tác list/copy. |
| ⚡ Copy song song | Copy nhiều file cùng lúc bằng thread pool; mặc định 4 luồng, giới hạn tối đa 16 luồng. |
| 🔎 Kiểm tra trùng linh hoạt | Hỗ trợ `Tên + dung lượng`, `Chỉ tên`, hoặc `Checksum nếu có`. |
| 🧪 Dry-run | Xem trước file/dung lượng sẽ copy mà không tạo file, folder hay log. |
| 🚫 Loại trừ theo chuỗi | Bỏ qua file/folder có tên chứa chuỗi bạn nhập. |
| 🔗 Xử lý shortcut | Shortcut được phân giải về file gốc để copy nội dung thật; shortcut hỏng sẽ bị bỏ qua. |
| ♻️ Retry lỗi tạm thời | Tự retry lỗi rate limit/server error bằng exponential backoff + jitter. |
| 💾 Resume log | Ghi tiến độ vào `.gdrive_copy_resume.*.json` trong thư mục đích. |
| 🛡️ Log an toàn hơn | Không public log mặc định; chỉ public khi bạn bật tùy chọn. |
| 📊 Tiến độ | In tiến độ định kỳ và tổng kết file lỗi cuối phiên. |

---

## 🚀 Cách dùng nhanh

1. Mở file notebook `GDrive_Turbo_Copy.ipynb` trên Google Colab.
2. Chạy cell **Input**.
3. Dán link folder **đích** vào ô `Drive của bạn (đích)`.
4. Dán link folder **nguồn** vào ô `Drive nguồn (shared)`.
5. Nếu chưa chắc, bật **Dry-run** để kiểm tra trước.
6. Chạy cell **Run**.
7. Xác thực tài khoản Google khi Colab yêu cầu.
8. Theo dõi log trong output cho đến khi hoàn tất hoặc dừng vì quota/hạn mức.

> Mẹo: nên test với một folder nhỏ hoặc bật **Dry-run** trước khi copy folder lớn.

---

## 🎛️ Tham số đầu vào

| Ô nhập | Ý nghĩa | Mặc định / gợi ý |
|---|---|---|
| `Drive của bạn (đích)` | Link thư mục nhận dữ liệu. Công cụ sẽ tạo hoặc dùng thư mục con theo tên folder nguồn bên trong thư mục này. | Bắt buộc |
| `Drive nguồn (shared)` | Link thư mục nguồn cần copy. | Bắt buộc |
| `Từ trang` | Bắt đầu từ trang list thứ mấy. Drive API list tối đa 1000 item/trang. `0` nghĩa là từ đầu. | `0` |
| `Đến trang` | Kết thúc ở trang list thứ mấy. `0` nghĩa là đến hết. | `0` |
| `Dung lượng tối đa (GB)` | Hạn mức copy cho phiên hiện tại. Khi vượt mức, công cụ dừng sạch và lưu log. | `750` |
| `Bỏ file/folder chứa chữ` | Danh sách chuỗi loại trừ, phân tách bằng dấu phẩy. Ví dụ: `tmp, .log, cache`. | Trống |
| `Số luồng song song` | Số file copy đồng thời. Tool tự giới hạn trong khoảng `1..16`. | `4` |
| `Kiểm tra trùng` | Cách xác định file đã tồn tại ở đích. | `Tên + dung lượng` |
| `Dry-run` | Chỉ xem trước, không copy, không tạo folder, không ghi log. | Tắt |
| `Public log` | Cấp quyền “anyone with the link can read” cho file log để tài khoản khác đọc được trong trường hợp chia sẻ folder không đủ. | Tắt |

---

## 🔎 Chế độ kiểm tra trùng

Khi chạy lại hoặc khi đích đã có dữ liệu, công cụ sẽ index thư mục đích và quyết định file nào cần bỏ qua.

| Chế độ | Khi nào dùng | Ưu điểm | Nhược điểm |
|---|---|---|---|
| `Tên + dung lượng` | Khuyên dùng mặc định. | Nhanh, giảm nguy cơ bỏ nhầm so với chỉ tên. | File Google Docs/Sheets/Slides có thể không có size rõ ràng. |
| `Chỉ tên` | Khi chắc chắn đích chưa có file khác nội dung nhưng cùng tên. | Nhanh nhất. | Có thể bỏ nhầm nếu có file cùng tên nhưng khác nội dung. |
| `Checksum nếu có` | Khi cần chắc hơn với binary file có `md5Checksum`. | Xác thực tốt hơn cho file có checksum. | Google Docs/Sheets/Slides và một số item không có checksum nên phải fallback. |

Nếu mục tiêu là an toàn, giữ mặc định `Tên + dung lượng` hoặc dùng `Checksum nếu có`.

---

## 🧪 Dry-run

Bật `Dry-run` khi bạn muốn kiểm tra trước:

- Folder gốc ở đích sẽ được tạo hay dùng lại.
- File nào sẽ được copy.
- Dung lượng dự kiến sẽ copy trong phiên.
- Logic skip/resume có hoạt động đúng theo dữ liệu hiện có không.

Trong chế độ này, công cụ **không tạo file**, **không tạo folder**, và **không ghi resume log**.

---

## 🔄 Resume và đổi nhiều tài khoản

Google Drive thường có hạn mức tạo/copy/upload khoảng **750 GB/ngày cho mỗi tài khoản**. Khi chạm giới hạn hoặc khi bạn đặt `Dung lượng tối đa (GB)`, công cụ sẽ dừng và lưu tiến độ.

### Cơ chế log

- Mỗi tài khoản ghi một log riêng trong thư mục copy đích:

```text
.gdrive_copy_resume.<account>.json
```

- Khi chạy lại, công cụ đọc tất cả log trong thư mục đích rồi gộp danh sách source file ID đã copy.
- File đã được copy thành công hoặc đã tồn tại ở đích sẽ được ghi nhận để lần sau skip nhanh hơn.
- Log chỉ chứa metadata tiến độ như source file ID, dung lượng đã xử lý, thời gian cập nhật; không chứa nội dung file.

### Đổi tài khoản để copy tiếp

1. Chờ phiên hiện tại dừng sạch và in thông báo đã lưu tiến độ.
2. Trong Colab, chọn **Runtime → Disconnect and delete runtime**.
3. Kết nối lại runtime.
4. Chạy lại cell **Input** nếu cần, giữ nguyên folder đích và nguồn.
5. Chạy cell **Run** và xác thực bằng tài khoản tiếp theo.
6. Công cụ sẽ đọc log, bỏ qua phần đã copy và tiếp tục phần còn lại.

> Không nên chạy nhiều tài khoản cùng lúc vào cùng một thư mục đích. Hãy chạy tuần tự: tài khoản A xong/dừng rồi mới chuyển sang tài khoản B.

---

## ⚙️ Gợi ý cấu hình

| Nhu cầu | Cấu hình gợi ý |
|---|---|
| Test trước khi copy thật | Bật `Dry-run`, giữ `Kiểm tra trùng = Tên + dung lượng`. |
| Copy ổn định, ít lỗi | `Số luồng song song = 2..4`. |
| Folder nhiều file nhỏ | Có thể thử `Số luồng song song = 4..8`. |
| Gặp nhiều rate limit | Giảm luồng xuống `1..2`. |
| Muốn tránh bỏ nhầm file cùng tên | Dùng `Tên + dung lượng` hoặc `Checksum nếu có`. |
| Copy tiếp bằng tài khoản khác | Dùng chung folder đích, cấp quyền Editor cho tài khoản mới. |

---

## ⚠️ Lưu ý quan trọng

- Tài khoản đang xác thực phải có quyền đọc folder nguồn và quyền ghi folder đích.
- Với nhiều tài khoản, folder đích nên được share quyền **Editor** cho mọi tài khoản sẽ dùng, hoặc đặt trong Shared Drive mà các tài khoản đều là thành viên.
- `Public log` mặc định tắt để tránh public danh sách source file ID. Chỉ bật nếu các tài khoản khác không đọc được log dù đã share folder.
- File Google-native như Docs/Sheets/Slides thường không có `size`/`md5Checksum` giống file binary; đây là giới hạn từ metadata Drive API.
- `Từ trang`/`Đến trang` chỉ áp dụng cho danh sách item ở folder nguồn cấp đang list; mỗi trang tối đa 1000 item theo Drive API.
- Mỗi lần resume vẫn cần duyệt lại cây nguồn để biết file nào còn thiếu, nên folder cực lớn vẫn mất thời gian scan.
- Nếu Colab bị ngắt đột ngột, tiến độ gần nhất phụ thuộc vào lần flush log gần nhất và lần lưu cuối nếu có chạy tới `finally`.
- Sau khi copy hoàn tất, bạn có thể xóa các file `.gdrive_copy_resume.*.json` trong thư mục đích.

---

## ❓ FAQ

<details>
<summary><b>Có cần cài thư viện không?</b></summary>

Không cần cài thủ công trong Colab thông thường. Notebook dùng các thư viện phổ biến có sẵn như `googleapiclient`, `google.colab.auth` và `ipywidgets`.
</details>

<details>
<summary><b>Chạy lại có bị copy trùng không?</b></summary>

Thông thường không. Công cụ đọc resume log và index dữ liệu ở đích để skip file đã copy/đã tồn tại. Tuy nhiên nếu bạn chọn `Chỉ tên`, file khác nội dung nhưng cùng tên vẫn có thể bị coi là đã tồn tại.
</details>

<details>
<summary><b>Nên chọn chế độ kiểm tra trùng nào?</b></summary>

Mặc định `Tên + dung lượng` là cân bằng nhất. Nếu muốn nhanh và chắc chắn không có file cùng tên khác nội dung, chọn `Chỉ tên`. Nếu muốn chắc hơn với file binary, chọn `Checksum nếu có`.
</details>

<details>
<summary><b>Nên đặt bao nhiêu luồng?</b></summary>

`4` là mức cân bằng. Nếu gặp rate limit, giảm xuống `2` hoặc `1`. Nếu folder có nhiều file nhỏ và API ổn định, có thể thử `8`. Tool giới hạn tối đa `16`.
</details>

<details>
<summary><b>Copy shortcut thì sao?</b></summary>

Shortcut sẽ được phân giải sang target gốc và copy nội dung target. Shortcut hỏng hoặc không có target sẽ bị bỏ qua.
</details>

<details>
<summary><b>Log có an toàn không?</b></summary>

Log không chứa nội dung file, nhưng có chứa source file ID. Vì vậy mặc định tool không public log. Chỉ bật `Public log` khi bạn hiểu rủi ro và thật sự cần cho resume đa tài khoản.
</details>

---

<div align="center">

Nếu thấy hữu ích, hãy ⭐ repo để ủng hộ nhé!

</div>
