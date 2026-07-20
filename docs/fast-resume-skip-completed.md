# Fast resume — bỏ qua các thư mục đã copy xong (`--skip-completed-folders`)

> **TL;DR** — Khi một lần copy bị dừng giữa chừng (hết quota ngày, mất mạng…), lần chạy sau vẫn phải **liệt kê lại (list) toàn bộ cây thư mục** để biết mình đã tới đâu — dù các file đã copy thì không bị copy lại. Với cây sâu/rộng, việc list lại này tốn rất nhiều lời gọi API và thời gian. Thay đổi này thêm tuỳ chọn **`--skip-completed-folders`**: resume log ghi lại những **nhánh thư mục đã copy trọn vẹn**, và lần sau bỏ qua hẳn (không list lại) các nhánh đó. Đánh đổi: nhánh bị bỏ qua sẽ *không* nhận file mới thêm vào nguồn — nên đây là tuỳ chọn **bật khi cần**, mặc định tắt.

## Bối cảnh

Công cụ sao chép thư mục Drive→Drive theo kiểu duyệt cây theo chiều sâu: với mỗi thư mục, nó **list** danh sách con (nguồn) và cả thư mục đích để phát hiện trùng, rồi `files.copy` từng file phía server. Cơ chế **resume** hiện tại rất chắc:

- Mỗi file đã copy được đánh dấu bằng `appProperties` (`source_file_id`, …) và ghi vào một **resume log** (JSON có hash toàn vẹn) đặt trong thư mục đích.
- Lần chạy lại, mỗi file được kiểm tra qua `copied_ids`/`appProperties` — **đã copy thì bỏ qua**, không copy lại.

Nhưng có một điểm chưa tối ưu: **để biết file nào đã copy, tool vẫn phải list lại từng thư mục.** Nếu anh có một cây 10.000 thư mục và bị dừng ở thư mục thứ 9.000, lần resume vẫn list lại cả 9.000 thư mục đầu (mỗi cái ≥ 1 lời gọi API) chỉ để rồi bỏ qua từng file. Việc này *không* tốn quota copy ngày (750 GB) nhưng tốn **quota số lời gọi/100 giây** và **thời gian** — resume chậm một cách không cần thiết. Chính README của repo đã ghi nhận đây là "future work".

> **Khái niệm chính:** quota *copy theo ngày* (byte) và quota *số truy vấn API* là hai thứ khác nhau. Thay đổi này giảm loại thứ hai và giảm thời gian resume; nó **không** (và không thể) nâng trần 750 GB/ngày của Google.

## Ý tưởng cốt lõi

Nếu ta biết chắc **cả một nhánh con đã được copy trọn vẹn** ở lần trước, thì lần sau khỏi cần list lại nhánh đó — bỏ qua thẳng.

Điều tinh tế nằm ở chữ "biết chắc". Vì các file được copy **bất đồng bộ** (qua thread pool), ta không thể kết luận một thư mục "xong" ngay tại lúc duyệt. Nên cách làm là:

1. **Trong lúc duyệt**, ghi lại cấu trúc từng thư mục: danh sách file con (id) + thư mục con (id) + việc list có lỗi không. (Việc ghi này chạy ở luồng chính, không cần khoá.)
2. **Cuối lần chạy** (sau khi thread pool đã xả hết — nên `copied_ids`/`failed_items` đã chốt), tính đệ quy theo hậu-thứ-tự: một thư mục là **"đã xong"** ⇔ list sạch (không lỗi) **và** đủ điều kiện **và** mọi file con đều nằm trong `copied_ids` mà không nằm trong tập lỗi **và** mọi thư mục con cũng "đã xong".
3. Ghi tập `completed_folder_ids` vào resume log (schema **v3 → v4**).
4. **Lần sau**, trước khi list một thư mục, nếu id của nó nằm trong `completed_folder_ids` (đã nạp) → bỏ qua, không list, tính là "skipped".

Nguyên tắc vàng: **bảo toàn theo hướng an toàn.** Bất cứ điều gì không chắc chắn (list lỗi, có shortcut, thư mục con chưa từng duyệt tới…) đều bị coi là *chưa xong* → **không bao giờ** bỏ qua một nhánh chưa thực sự copy đủ. Một lỗi (nếu có) sẽ nghiêng về "list lại thừa" chứ không nghiêng về "mất dữ liệu".

**Ví dụ cụ thể.** Cây: `root/{a.txt, subOK/{c.txt}, subBAD/{d.txt}}`, trong đó `d.txt` bị lỗi copy ở lần 1.

| Lần chạy | subOK | subBAD | Kết quả |
|---|---|---|---|
| **Lần 1** (`d.txt` lỗi) | copy xong `c.txt` → **đánh dấu xong** | `d.txt` lỗi → **chưa xong** | log còn lại (vì có lỗi), lưu `completed=[subOK]` |
| **Lần 2** (sửa lỗi, resume) | nằm trong `completed` → **bỏ qua, không list** | không trong `completed` → **list lại**, copy `d.txt` | xong, sạch lỗi |

`root` chỉ được đánh dấu xong khi *cả* `subOK` lẫn `subBAD` xong — nên ở lần 1 `root` chưa xong, đúng như mong đợi.

## Mã

Thay đổi gom vào các tệp sau:

**1. `resume_store.py` — schema v4.** Thêm trường `completed_folders: set[str]` vào `ResumeState`; đưa vào payload chuẩn (`completed_folder_ids`), thêm bước `migrate` cho log cũ (`< 4` → mặc định rỗng), và **hợp nhất (union)** khi nạp nhiều log.

**2. `copier.py` — theo dõi & tính toán.**

```python
@dataclass
class _FolderNode:
    listing_ok: bool = True
    eligible: bool = True                       # tắt cho thư mục chứa shortcut (bảo toàn)
    file_eff_ids: set[str] = field(default_factory=set)
    subfolder_ids: set[str] = field(default_factory=set)

def _record_tree_node(self, folder_id, children):   # gọi sau mỗi lần list (chỉ khi bật cờ)
    if not self.config.skip_completed_folders: return
    node = _FolderNode(listing_ok=folder_id not in self._listing_error_folders)
    for src in children:
        if src.is_shortcut:  node.eligible = False
        elif src.is_folder:  node.subfolder_ids.add(src.id)
        else:                node.file_eff_ids.add(src.id)
    self._tree[folder_id] = node

def _compute_completed_folders(self):                # cuối run, sau khi xả thread pool
    ... # đệ quy hậu-thứ-tự, bảo toàn: chỉ trả về thư mục chứng minh được đã copy đủ
```

Điểm chèn: bỏ qua thư mục ngay đầu `_copy_folder` (chỉ với thư mục thật, không phải đích của shortcut, và chỉ khi bật cờ); ghi node sau khi list ở `run()` (gốc) và `_copy_folder` (các thư mục con); trong `run()`'s `finally`, `self._state.completed_folders |= self._compute_completed_folders()` **trước** khi lưu log.

**3. `models.py`** — `CopyConfig.skip_completed_folders: bool = False` và `CopyResult.skipped_complete_folders: int`.

**4. `cli.py`** — cờ `--skip-completed-folders` + dòng tổng kết "Skipped folders".

**5. Notebook Colab** — thêm ô chọn "⏩ Bỏ qua thư mục đã copy xong".

## Xác minh

- **`tests/test_skip_completed.py` (mới):**
  - Nhánh copy xong **không bị list lại** ở lần resume; nhánh có lỗi **bị list lại** và copy tiếp phần còn thiếu.
  - Với cờ **tắt** (mặc định), mọi thứ vẫn được list lại như cũ (control).
  - File **mới** thêm vào nhánh đã-xong **không** được copy khi bật cờ (đúng như đánh đổi đã ghi).
  - Resume log thực sự chứa `completed_folders` đúng (subOK có, subBAD không).
- **`tests/test_resume_store.py`:** round-trip có `completed_folders`; migrate v3→v4 thêm tập rỗng.
- **Kết quả:** `108 passed`, `ruff check src tests` sạch. Không đổi hành vi mặc định (cờ tắt ⇒ 0 chi phí, `_tree` không được dựng).

**QA thủ công:**

1. Copy một cây lớn tới khi bị dừng (hoặc dùng `--max-size-gb` nhỏ để mô phỏng dừng sớm) — **có bật** `--skip-completed-folders`.
2. Chạy lại cùng lệnh. Quan sát log: các nhánh đã xong hiện `folder_skip_complete`, phần tổng kết có dòng **"Skipped folders: N"**; resume nhanh hơn hẳn.
3. Kiểm tra không mất dữ liệu: sau khi hoàn tất, đối chiếu số file/thư mục nguồn ↔ đích.
4. Thử **tắt** cờ để xác nhận hành vi cũ (list lại đầy đủ, có nhận file mới).

## Các phương án thay thế

**Phương án A — Lưu `pageToken` để resume giữa trang (mid-page).**

| Ưu | Nhược |
|---|---|
| Resume mịn ngay trong *một* thư mục khổng lồ | `pageToken` của Drive **dễ hết hạn** giữa các phiên (nhất là sau 24h chờ quota) → rủi ro sai/trùng |
| Tiết kiệm tối đa lời gọi list | Phức tạp, khó bảo đảm đúng khi nội dung nguồn thay đổi |

**Phương án B — Bật mặc định (không cần cờ).**

| Ưu | Nhược |
|---|---|
| "Tốt nhất cho tôi" không cần bật tay | Đổi ngữ nghĩa resume: không còn nhận file mới khi chạy lại → phá vỡ kỳ vọng của người coi re-run như một dạng đồng bộ |

PR chọn **subtree-level skip, opt-in** — an toàn (không rủi ro `pageToken`, không đổi mặc định), theo đúng khuôn mẫu opt-in sẵn có của `--fast-list`.

## Đề xuất người để trao đổi

Toàn bộ `copier.py` và `resume_store.py` chỉ có một tác giả thực chất: **Nguyễn Ngọc Anh Tú** (`ekaznyra`) — người đã dựng gói production, resume log và cơ chế chống trùng. Đây là người nắm rõ nhất ngữ nghĩa resume và phù hợp nhất để review đánh đổi "bỏ qua nhánh đã xong".

## Trắc nghiệm

<details>
<summary>1. Vì sao resume vẫn tốn kém dù file đã copy thì không bị copy lại?</summary>

- A. Vì tool copy lại tất cả.
- **B. Vì để biết đã tới đâu, tool phải list lại từng thư mục — tốn quota số truy vấn API và thời gian, dù không tốn quota copy byte.**
- C. Vì resume log bị xoá.

Giải thích: File được bỏ qua qua `copied_ids`/`appProperties`, nhưng muốn gặp lại chúng thì phải list. Chính chi phí list này là thứ `--skip-completed-folders` cắt giảm.
</details>

<details>
<summary>2. Điều kiện để một thư mục được đánh dấu "đã xong"?</summary>

- A. Chỉ cần đã tạo thư mục đích.
- **B. List sạch (không lỗi) + đủ điều kiện + mọi file con ∈ copied_ids và không lỗi + mọi thư mục con cũng "đã xong".**
- C. Chỉ cần một nửa số file con đã copy.

Giải thích: Định nghĩa mang tính đệ quy và bảo toàn — bất kỳ điều không chắc nào cũng khiến thư mục bị coi là chưa xong.
</details>

<details>
<summary>3. Vì sao việc tính "đã xong" được để tới cuối lần chạy mới làm?</summary>

- **A. Vì file được copy bất đồng bộ; chỉ sau khi thread pool xả hết thì `copied_ids`/`failed_items` mới chốt, nên mới kết luận đúng được.**
- B. Để tiết kiệm bộ nhớ.
- C. Vì Drive yêu cầu thế.

Giải thích: Nếu tính giữa chừng, một file đang copy dở có thể bị hiểu nhầm là xong. Đợi xả hết pool đảm bảo dữ liệu đã chốt.
</details>

<details>
<summary>4. Đánh đổi lớn nhất của việc bỏ qua nhánh đã xong là gì?</summary>

- A. Có thể copy trùng file.
- **B. Nhánh bị bỏ qua sẽ không nhận file mới thêm vào nguồn kể từ lần chạy trước.**
- C. Làm hỏng resume log.

Giải thích: Bỏ qua = không list = không thấy file mới. Vì vậy nó là opt-in; ai coi re-run như đồng bộ thì nên tắt.
</details>

<details>
<summary>5. Vì sao thư mục chứa shortcut bị đánh dấu "không đủ điều kiện" (eligible=False)?</summary>

- A. Vì shortcut không được copy.
- **B. Để bảo toàn: shortcut và đích của nó được đánh khoá (key) khác nhau, nên ta cố tình không bao giờ bỏ qua nhánh có shortcut, tránh sai sót.**
- C. Vì shortcut luôn lỗi.

Giải thích: Đây là lựa chọn thiên về an toàn — thà list lại thừa một nhánh có shortcut còn hơn liều bỏ qua nhầm.
</details>
