# GDrive_Turbo_Copy

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/ekaznyra/GDrive_Turbo_Copy/blob/main/GDrive_Turbo_Copy.ipynb)

Sao chép thư mục Google Drive siêu tốc, hỗ trợ đa luồng và tiếp tục (resume) khi bị ngắt.

## Mục đích

Công cụ này giúp sao chép toàn bộ nội dung một thư mục Google Drive (bao gồm cả Shared Drives) sang một thư mục Google Drive khác, sử dụng Drive API server-side copy (không tốn băng thông tải xuống).

## Giới hạn quan trọng

- **Không copy permissions**: quyền chia sẻ của file/folder nguồn KHÔNG được sao chép.
- **Không copy comments**: bình luận trên file nguồn KHÔNG được sao chép.
- **Không copy revision history**: lịch sử chỉnh sửa KHÔNG được sao chép.
- **Giới hạn quota**: Google Drive giới hạn ~750 GB server-side copy mỗi ngày. Khi đạt giới hạn, công cụ sẽ dừng và lưu tiến độ để chạy lại sau.
- **Chỉ dùng hợp pháp**: chỉ sử dụng để sao chép dữ liệu bạn có quyền hợp pháp.

## Cách sử dụng

1. Mở notebook trong Google Colab bằng nút badge ở trên.
2. Chạy ô **Input**: điền link thư mục đích và thư mục nguồn.
3. Chạy ô **Run**: quá trình copy bắt đầu.

### Các tham số

| Tham số | Mô tả | Mặc định |
|---|---|---|
| Drive của bạn (đích) | Link thư mục Google Drive nhận file | Bắt buộc |
| Drive nguồn (shared) | Link thư mục Google Drive nguồn | Bắt buộc |
| Từ trang / Đến trang | Phân trang theo từng thư mục (mỗi trang ~1000 mục). 0 = không giới hạn | 0 |
| Dung lượng tối đa (GB) | Dừng khi đã copy đủ dung lượng này | 750 |
| Bỏ file/folder chứa chữ | Danh sách chuỗi cần bỏ qua, phân tách bằng dấu phẩy | Trống |
| Số luồng song song | Số file copy đồng thời (1 = tuần tự, tối đa 16) | 4 |
| Kiểm tra trùng | Cách kiểm tra file đã tồn tại ở đích | Tên + dung lượng |
| Dry-run | Chỉ xem trước, không thực sự copy | Tắt |

### Chế độ kiểm tra trùng

- **Tên + dung lượng** (khuyên dùng): bỏ qua file nếu tên và kích thước khớp.
- **Chỉ tên**: bỏ qua file nếu tên khớp và `appProperties` xác nhận (tránh bỏ qua nhầm file trùng tên).
- **Checksum**: so sánh MD5, fallback về dung lượng nếu không có MD5.

## Cơ chế Resume

Sau mỗi 50 file được copy, công cụ lưu một file log JSON vào thư mục đích:

```
.gdrive_copy_resume.<email>.json
```

File log lưu:
- Danh sách ID file đã copy (`copied_file_ids`)
- Mapping thư mục nguồn → thư mục đích (`folder_map`)
- Tổng dung lượng đã copy của tài khoản này (`lifetime_size_mb`)
- Danh sách file thất bại (`failed_items`)

Khi chạy lại, công cụ đọc tất cả log trong thư mục đích, bỏ qua file đã copy, và tiếp tục từ chỗ dừng.

Nếu không có file nào thất bại và copy hoàn tất 100%, file log sẽ được xóa tự động.

## appProperties (idempotency)

Mỗi file được copy sẽ có `appProperties`:
- `source_file_id`: ID file nguồn
- `source_md5`: MD5 checksum file nguồn (nếu có)
- `copied_by_tool`: `GDrive_Turbo_Copy`

Mỗi thư mục được tạo sẽ có `appProperties`:
- `source_folder_id`: ID thư mục nguồn
- `copied_by_tool`: `GDrive_Turbo_Copy`

`appProperties` được kiểm tra trước khi so sánh tên/dung lượng, giúp tránh bỏ qua nhầm file không liên quan có cùng tên.

## Xử lý lỗi

- **Rate limit / lỗi tạm thời**: tự động retry với exponential backoff (tối đa 6 lần, chờ tối đa 32s).
- **Quota fatal** (storageQuotaExceeded, dailyLimitExceeded, v.v.): dừng ngay, lưu log.
- **Permission error / 404**: bỏ qua file đó, không retry.
- **File thất bại**: ghi vào log và xuất báo cáo JSON (`gdrive_copy_failed_YYYYMMDD_HHMMSS.json`) vào thư mục đích.

## Tests

Chạy ô **Tests** để kiểm tra các chức năng core mà không cần kết nối Drive thực.
