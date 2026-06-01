<div align="center">

# ☁️ Copy Folder Google Drive → Google Drive

### 1TouchPro · Sao chép toàn bộ thư mục Drive sang Drive, kể cả khác tài khoản

<a href="https://colab.research.google.com/github/nqthaivl/Copy-Folder-Google-Drive-to-Google-Drive/blob/main/Copy_Folder_Google_Drive_to_Google_Drive.ipynb">
  <img src="https://colab.research.google.com/assets/colab-badge.svg" alt="Open In Colab">
</a>

![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Google%20Colab-F9AB00?logo=googlecolab&logoColor=white)
![Drive API](https://img.shields.io/badge/Google%20Drive%20API-v3-1FA463?logo=googledrive&logoColor=white)
![No Install](https://img.shields.io/badge/Cài%20đặt-Không%20cần-success)

</div>

---

## 📑 Mục lục

- [Giới thiệu](#-giới-thiệu)
- [Tính năng chính](#-tính-năng-chính)
- [Bắt đầu nhanh](#-bắt-đầu-nhanh-3-bước)
- [Bảng thông số đầu vào](#-bảng-thông-số-đầu-vào)
- [Cơ chế resume & copy nhiều tài khoản](#-cơ-chế-resume--copy-nhiều-tài-khoản)
- [Đổi tài khoản để copy tiếp](#-đổi-tài-khoản-để-copy-tiếp)
- [Lưu ý & giới hạn](#-lưu-ý--giới-hạn)
- [Câu hỏi thường gặp](#-câu-hỏi-thường-gặp-faq)

---

## 🎯 Giới thiệu

**Copy Folder Google Drive to Google Drive** là một notebook Google Colab giúp bạn sao chép **toàn bộ nội dung** của một thư mục Google Drive sang thư mục khác — trên **cùng tài khoản** hoặc **giữa nhiều tài khoản** khác nhau.

Công cụ chạy hoàn toàn trên Colab, **không cần cài đặt gì thêm**, và được thiết kế để vượt qua giới hạn tải lên 750 GB/ngày của Google bằng cách chia việc cho nhiều tài khoản và tự động tiếp tục phần dở dang.

---

## ✨ Tính năng chính

| Tính năng | Mô tả |
|---|---|
| 🔁 **Copy đệ quy** | Sao chép toàn bộ file và thư mục con từ nguồn sang đích. |
| 👥 **Đa tài khoản & Shared Drive** | Hỗ trợ `supportsAllDrives` — copy được giữa các tài khoản và shared drive. |
| 🔗 **Tự xử lý shortcut** | Shortcut được phân giải về file gốc để copy đúng nội dung; shortcut hỏng sẽ bỏ qua. |
| 📂 **Gộp thư mục trùng tên** | Nếu thư mục con đã có ở đích thì gộp vào đó thay vì tạo thư mục trùng. |
| 🚫 **Bỏ qua file đã tồn tại** | Chạy lại không bị nhân đôi, vẫn giữ đúng các file trùng tên (khác ID). |
| 🔎 **Lọc loại trừ** | Bỏ qua file/thư mục có chứa chuỗi bạn nhập. |
| 📄 **Chọn khoảng trang** | Copy một phần thư mục lớn theo `Từ trang`/`Đến trang`. |
| 💾 **Giới hạn dung lượng** | Đặt hạn mức mỗi lần chạy (mặc định **750 GB**), dừng sạch khi đạt. |
| ⚡ **Copy song song** | Nhiều luồng cùng lúc (mặc định **4**) để tăng tốc rõ rệt. |
| 🔄 **Resume thông minh** | Ghi log tiến độ và tiếp tục dở dang — kể cả khi đổi tài khoản. |
| ♻️ **Tự thử lại** | Lỗi tạm thời (rate limit, 5xx) được retry với backoff lũy thừa + jitter. |
| 📋 **Tổng kết lỗi** | Liệt kê file copy thất bại cuối phiên để biết và tự thử lại lần sau. |

---

## 🚀 Bắt đầu nhanh (3 bước)

> **1️⃣ Mở notebook** — bấm nút **Open In Colab** ở đầu trang.

> **2️⃣ Điền thông tin** — chạy cell **Input**, dán link thư mục **đích** và **nguồn** vào giao diện.

> **3️⃣ Chạy** — chạy cell **Run**, xác thực tài khoản Google khi được hỏi. Xong!

✅ Không cần `pip install`, không cần cấu hình — mọi thư viện đã có sẵn trong Colab.

---

## 🎛️ Bảng thông số đầu vào

Điền các giá trị này trong cell **Input**:

| Ô nhập | Ý nghĩa | Mặc định |
|---|---|:---:|
| 📁 **Drive của bạn (đích)** | Link thư mục **nhận** file | — |
| 📂 **Drive nguồn (shared)** | Link thư mục **lấy** file | — |
| 📄 **Từ trang** | Trang bắt đầu copy (`0` = từ đầu) | `0` |
| 📄 **Đến trang** | Trang kết thúc (`0` = đến hết) | `0` |
| 💾 **Dung lượng tối đa (GB)** | Hạn mức **mỗi lần chạy** (không cộng dồn qua ngày) | `750` |
| 🚫 **Bỏ file/folder chứa chữ** | Chuỗi loại trừ, phân tách bằng dấu phẩy. VD: `tmp, .log` | — |
| ⚡ **Số luồng song song** | Số file copy đồng thời. `1` = tuần tự, tăng để nhanh hơn | `4` |

> 💡 **Mẹo:** hạn mức `750 GB` đúng bằng giới hạn tải lên/ngày của một tài khoản Google. Đặt `Từ trang`/`Đến trang` = `0` để không giới hạn phân trang.

---

## 🔄 Cơ chế resume & copy nhiều tài khoản

Google giới hạn khoảng **750 GB tải lên mỗi ngày cho mỗi tài khoản** (bản sao server-side cũng bị tính). Khi chạm giới hạn, công cụ **dừng sạch** và ghi tiến độ vào file log đặt ngay trong **thư mục đích**.

Nhờ vậy bạn có thể nối nhiều tài khoản để copy khối lượng lớn:

```
Tài khoản A  ──copy 750 GB──►  [đạt giới hạn]  ──ghi log──┐
                                                          │
Tài khoản B  ──đọc log, bỏ phần A đã copy, copy tiếp──────┤
                                                          │
Tài khoản C  ──tiếp tục phần còn lại──────────────────────┘
                                                          │
                              ►  "Copy hoàn tất ✅"
```

**Cách log hoạt động:**

- Mỗi tài khoản ghi **một file log riêng** trong thư mục đích: `.gdrive_copy_resume.<tài-khoản>.json` (tránh lỗi quyền khi ghi đè log của tài khoản khác).
- Khi khởi động, công cụ **đọc và gộp tất cả log** để biết chính xác file nào đã được copy bởi bất kỳ tài khoản nào.
- Log dùng **ID gốc của file** (không dùng tên) → tiếp tục giữa các tài khoản luôn chính xác, không trùng, không sót.
- Log được lưu định kỳ trong lúc chạy và lưu lần cuối khi kết thúc → ít mất tiến độ nếu Colab ngắt giữa chừng.
- Log chỉ chứa **danh sách ID** (không có nội dung file) và được tự cấp quyền "ai có link cũng đọc" để mọi tài khoản truy cập được.

> ⚠️ **Bắt buộc khi dùng nhiều tài khoản:**
> - Tất cả tài khoản phải copy vào **cùng một thư mục đích** (cùng link "Drive của bạn").
> - Thư mục đích phải được **chia sẻ quyền Editor** cho mọi tài khoản sẽ dùng, hoặc đặt trong **Shared Drive** mà các tài khoản đều là thành viên. Nếu không, các tài khoản không đọc được log của nhau.

---

## 🔁 Đổi tài khoản để copy tiếp

Khi đạt 750 GB hoặc đụng quota của Google, cell sẽ in thông báo dừng. Để copy tiếp bằng tài khoản khác:

1. Vào **Runtime → Disconnect and delete runtime** (ngắt kết nối Colab).
2. Kết nối lại và chạy lại cell **Run**.
3. Khi được hỏi xác thực, đăng nhập bằng **tài khoản tiếp theo** (B, C, D…).
4. Công cụ tự đọc log, bỏ qua phần đã copy và làm tiếp phần còn lại.

> 📌 Làm **tuần tự** từng tài khoản (A xong mới tới B). Không chạy nhiều tài khoản đồng thời trên cùng thư mục đích vì có thể gây copy trùng.

---

## ⚠️ Lưu ý & giới hạn

- 📄 File Google tài liệu gốc (Docs/Sheets/Slides) báo `size = 0`, nên **không tính vào hạn mức GB**. Việc dừng theo quota thật của Google vẫn hoạt động bình thường.
- 🧵 Khi chạy **song song**, các dòng log in ra sẽ **xen kẽ** giữa các file (không theo thứ tự tuần tự) — đây là bình thường. Việc duyệt thư mục con vẫn tuần tự, chỉ phần copy file chạy song song.
- 🐢 Tăng số luồng quá cao dễ khiến Google trả lỗi rate-limit hơn. Công cụ tự thử lại với backoff, nhưng nếu thấy nhiều cảnh báo "Lỗi tạm thời" thì nên **giảm số luồng**.
- 🌳 Mỗi lần resume, công cụ vẫn duyệt lại toàn bộ cây thư mục nguồn (chỉ bỏ phần đã copy), nên với thư mục rất lớn bước này có thể mất thời gian.
- 🧹 Khi copy xong hoàn toàn, bạn có thể xóa các file log `.gdrive_copy_resume.*.json` trong thư mục đích.
- 🔧 Không có bước build/test tự động — notebook được chạy lần lượt từng cell một cách tương tác.

---

## ❓ Câu hỏi thường gặp (FAQ)

<details>
<summary><b>Có cần cài thư viện gì không?</b></summary>

Không. Tất cả thư viện (`googleapiclient`, `ipywidgets`, `google.colab.auth`) đã có sẵn trong Google Colab.
</details>

<details>
<summary><b>Copy giữa hai tài khoản Google khác nhau được không?</b></summary>

Được. Đăng nhập tài khoản nào thì copy bằng tài khoản đó. Để nối nhiều tài khoản, hãy dùng chung một thư mục đích và chia sẻ quyền Editor như mục [Cơ chế resume](#-cơ-chế-resume--copy-nhiều-tài-khoản).
</details>

<details>
<summary><b>Chạy lại có bị copy trùng file không?</b></summary>

Không. Công cụ kiểm tra log tiến độ và các file đã tồn tại ở đích trước khi copy, nên chạy lại sẽ bỏ qua phần đã xong.
</details>

<details>
<summary><b>Bị dừng giữa chừng thì sao?</b></summary>

Tiến độ đã được ghi vào log trong thư mục đích. Chỉ cần chạy lại cell **Run** — công cụ sẽ tiếp tục phần còn lại.
</details>

<details>
<summary><b>Nên đặt bao nhiêu luồng song song?</b></summary>

Mặc định `4` là cân bằng tốt (giống rclone). Tăng lên `8` để nhanh hơn nếu thư mục nhiều file nhỏ; đặt `1` nếu muốn chạy tuần tự ổn định.
</details>

---

<div align="center">

**Made with ☁️ by 1TouchPro**

Nếu thấy hữu ích, hãy ⭐ repo để ủng hộ nhé!

</div>
