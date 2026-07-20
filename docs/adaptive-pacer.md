# Adaptive rate pacing (AIMD) + global `Retry-After` cooldown

> **TL;DR** — Bộ điều tốc (pacer) phía client trước đây là một *token bucket cố định*: nó giữ tốc độ ở một trần không đổi và không bao giờ học được tốc độ thực sự mà tài khoản chịu được. Thay đổi này biến nó thành **thích ứng (AIMD)** — bắt đầu ở trần `--max-tps`, tự *giảm nhân* khi bị Drive bóp (429/rate-limit), rồi *tăng cộng* trở lại khi mọi thứ trơn tru — và thêm một **cooldown toàn cục** khi Drive trả về `Retry-After` để *tất cả* worker cùng nghỉ.

## Bối cảnh

Google Drive áp một trần ghi bền vững khá thấp — khoảng **~10 thao tác/giây/project** — bên cạnh hạn mức upload+copy ~750 GB/ngày. Công cụ này sao chép thư mục Drive→Drive bằng `files.copy` phía server, chạy đa luồng (1–16 worker). Khi nhiều worker cùng gọi API, rất dễ chạm trần tốc độ và nhận về `429` hoặc `403 rateLimitExceeded`.

Hệ thống hiện có **hai** cơ chế ghìm tốc độ độc lập:

- **`concurrency.py` — bộ điều khiển đồng thời thích ứng.** Mỗi loại thao tác (COPY, LIST, …) có một limiter riêng; khi bị bóp thì *chia đôi* số luồng cho phép, khi thành công liên tục thì bò lên lại từng bước. Đây là cơ chế *phản ứng*.
- **`pacer.py` — token bucket chủ động.** Một cái sàn giữ tổng số request/giây của cả project dưới ngưỡng, để phần lớn lỗi 429 *không xảy ra ngay từ đầu*.

Vấn đề nằm ở chỗ pacer là **tĩnh**. Nó luôn phát token ở đúng tốc độ cấu hình (mặc định 10 req/s). Khi tài khoản thực tế chỉ chịu được, ví dụ, 4 req/s tại thời điểm đó, bộ điều khiển đồng thời sẽ giảm số luồng — nhưng pacer vẫn sẵn sàng bắn ở 10 req/s. Tệ hơn, `Retry-After` do Drive gửi kèm lỗi chỉ được *một* lời gọi đang lỗi tôn trọng (nó ngủ đúng chừng ấy giây); các worker anh em vẫn tiếp tục nã request trong đúng khoảng thời gian máy chủ bảo phải nghỉ.

## Ý tưởng cốt lõi

Ý tưởng là dạy cho pacer **tự dò tìm tốc độ bền vững** thay vì giữ một hằng số, dùng đúng luật điều khiển mà TCP dùng để chống nghẽn: **AIMD — Additive Increase, Multiplicative Decrease** (tăng cộng, giảm nhân).

- **Khởi đầu ở trần.** Pacer bắt đầu đúng bằng `--max-tps`. Nếu không có gì bị bóp, hành vi *giống hệt* pacer cũ — không hề chậm đi ở trường hợp thường gặp.
- **Bị bóp → giảm nhân.** Mỗi tín hiệu throttle (429 hoặc 403 rate-limit) làm `rate *= 0.5`, chặn dưới ở `min_rate` (mặc định 1 req/s). Đồng thời *dung lượng bình* (burst) co lại theo tốc độ mới, nên một tốc độ đã giảm thực sự được thực thi chứ không bị đánh bại bởi một đống token tích lũy.
- **Trơn tru → tăng cộng.** Sau một chuỗi lời gọi sạch (mặc định 25 lần), `rate += 1`, tối đa bằng trần.
- **`Retry-After` → cooldown toàn cục.** Khi Drive gửi kèm `Retry-After: N`, pacer mở một cửa sổ nghỉ chung: lần `acquire()` kế tiếp của *mọi* worker sẽ chặn cho đến khi hết N giây.

**Ví dụ cụ thể.** Trần 10 req/s. Drive trả về `429` kèm `Retry-After: 20`:

| Sự kiện | rate | burst | cooldown |
|---|---|---|---|
| khởi đầu | 10 | 10 | — |
| throttle (Retry-After 20s) | 5 | 5 | 20s |
| worker bất kỳ gọi `acquire()` | 5 | 5 | ngủ hết 20s rồi mới lấy token |
| +3 lần thành công (mỗi 25 lần) | 6→7→8 | 6→7→8 | — |

Tức là cả đội cùng lùi một bước, tìm ra tốc độ an toàn, rồi từ từ đẩy lại lên mức tối đa mà tài khoản chịu được — thay vì cắm đầu vào tường suốt 24h.

## Mã

Thay đổi gom vào 5 tệp, theo thứ tự dễ hiểu:

**1. `pacer.py` — lớp `AdaptivePacer(TokenBucket)`.** Kế thừa cơ chế token bucket sẵn có, thêm trạng thái AIMD và cooldown.

```python
class AdaptivePacer(TokenBucket):
    def acquire(self, tokens=1.0):
        # chờ hết cooldown toàn cục trước, rồi mới xin token như thường
        while True:
            with self._lock:
                wait = self._cooldown_until - self._monotonic()
            if wait <= 0:
                break
            self._sleep(wait); slept += wait
        return slept + super().acquire(tokens)

    def record_throttle(self, *, retry_after=None):
        with self._lock:
            self._successes = 0
            self.rate = max(self.min_rate, self.rate * self._backoff)
            self.capacity = max(1.0, self.rate)          # co burst theo rate
            if self._tokens > self.capacity: self._tokens = self.capacity
            if retry_after and retry_after > 0:
                self._cooldown_until = max(self._cooldown_until,
                                           self._monotonic() + retry_after)

    def record_success(self):
        with self._lock:
            if self.rate >= self.max_rate: self._successes = 0; return
            self._successes += 1
            if self._successes >= self._recover_after:
                self.rate = min(self.max_rate, self.rate + self._recover_step)
                self.capacity = max(1.0, self.rate); self._successes = 0
```

`NullPacer` (khi tắt điều tốc) nhận thêm hai phương thức no-op `record_throttle`/`record_success` để client gọi vô điều kiện. `make_pacer()` giờ trả về `AdaptivePacer` — vì nó là lớp con của `TokenBucket` nên mọi kiểm tra kiểu `isinstance(..., TokenBucket)` vẫn đúng.

**2. `retry.py` — thêm trường `retry_after` vào `RetryEvent`.** Giá trị `Retry-After` đã được parse sẵn (`parse_retry_after`) nay được đính kèm vào sự kiện để lớp trên tiêu thụ.

**3. `drive_client.py` — nối tín hiệu vào pacer.** Trong `_exec`, callback `on_event` khi gặp throttle sẽ gọi cả `controller.record_throttle(op)` *và* `pacer.record_throttle(retry_after=event.retry_after)`; sau mỗi lời gọi thành công thì gọi `pacer.record_success()`. Đây là điểm mấu chốt: pacer giờ *nghe* được nhịp thở của Drive, giống hệt bộ điều khiển đồng thời.

**4. `models.py`** — cập nhật chú thích `DEFAULT_MAX_TPS` nêu rõ đây là *trần*, không phải hằng số.

**5. Tài liệu & phiên bản** — README (bảng tính năng, mô tả module, cờ `--max-tps`), nhãn ô nhập trong notebook Colab, và bump `2.0.0 → 2.1.0`.

## Xác minh

- **Kiểm thử đơn vị mới trong `tests/test_pacer.py`:** khởi đầu ở trần; throttle chia đôi rate và chặn dưới ở `min_rate`; hồi phục cộng dồn đúng nhịp `recover_after`; không vượt trần; `Retry-After` mở cooldown toàn cục (một `acquire` ngủ đủ 20s); burst co theo rate và token bị kẹp lại.
- **Kiểm thử tích hợp mới `tests/test_drive_client_pacing.py`:** dùng một `service` giả (không chạm googleapiclient/mạng) để chạy đúng đường retry, khẳng định `DriveClient` chuyển tiếp throttle (kèm `Retry-After`) và success vào pacer, và `acquire()` được gọi trước *mỗi* lần thử HTTP.
- **Kết quả:** `103 passed` (94 cũ + 9 mới), `ruff check src tests` sạch.

**QA thủ công:**

1. `pip install -e ".[dev]"` rồi `pytest -q` và `ruff check src tests`.
2. Chạy thử `--dry-run` để chắc chắn không có gì bị copy: `gdrive-turbo-copy --source <link> --dest <link> --dry-run`.
3. Chạy thật với `--max-tps 10` trên một cây có nhiều file nhỏ; theo dõi log `drive_retry` — khi thấy 429, tốc độ sẽ tự giảm; khi lặng, log `progress` tiếp tục đều.
4. Đặt `--max-tps 0` để xác nhận đường tắt điều tốc (`NullPacer`) vẫn chạy bình thường.

## Các phương án thay thế

**Phương án A — Chỉ nâng cấp bộ điều khiển đồng thời, bỏ pacer thích ứng.**

| Ưu | Nhược |
|---|---|
| Ít bề mặt thay đổi hơn | Giảm số luồng *không* trực tiếp giảm req/s; vẫn có thể bùng nổ khi các luồng còn lại đồng loạt bắn |
| Tận dụng cơ chế đã có | Không có cooldown toàn cục cho `Retry-After` |

**Phương án B — Cấu hình thêm cờ CLI cho `min_tps`/`backoff`/`recover_after`.**

| Ưu | Nhược |
|---|---|
| Người dùng nâng cao chỉnh được | Tăng gánh nặng cấu hình; mặc định AIMD đã hợp lý cho gần như mọi trường hợp |
| Linh hoạt thử nghiệm | Thêm bề mặt cần kiểm thử & tài liệu |

PR chọn cách hiện tại: thích ứng *trong suốt*, không thêm cờ mới, giữ `--max-tps` làm trần duy nhất.

## Đề xuất người để trao đổi

Toàn bộ lịch sử của `pacer.py`, `drive_client.py`, `retry.py` chỉ có **một** tác giả thực chất: **Nguyễn Ngọc Anh Tú** (`ekaznyra`) — chính là người đã viết commit *"rate pacing, metadata fidelity, quota circuit breaker"* và *"opt-in fast-list"*. Đây là người nắm rõ nhất bối cảnh điều tốc/hạn mức và là người phù hợp nhất để review thay đổi này.

## Trắc nghiệm

<details>
<summary>1. Vì sao giảm số luồng đồng thời chưa đủ để tôn trọng trần tốc độ của Drive?</summary>

- A. Vì số luồng không liên quan gì đến số request.
- **B. Đúng — Ít luồng hơn nhưng mỗi luồng vẫn có thể bắn ở tốc độ cao; trần Drive là req/s tổng, nên cần một cơ chế ghìm req/s riêng (pacer).**
- C. Vì Drive không giới hạn theo luồng.

Giải thích: Bộ điều khiển đồng thời giới hạn *độ song song*, còn pacer giới hạn *nhịp phát request*. Hai trục khác nhau; chạm trần ~10 req/s có thể xảy ra ngay cả với ít luồng nếu mỗi thao tác rất nhanh.
</details>

<details>
<summary>2. Sau một tín hiệu throttle, tốc độ thay đổi thế nào?</summary>

- A. Giảm đi 1 (trừ cộng).
- **B. Nhân với hệ số backoff (mặc định ×0.5), chặn dưới ở min_rate.**
- C. Về thẳng min_rate.

Giải thích: "Multiplicative Decrease" — giảm nhân để lùi nhanh khỏi vùng nguy hiểm; hồi phục mới là "Additive Increase" (cộng từng bước).
</details>

<details>
<summary>3. Vì sao khi throttle, `capacity` (burst) cũng bị co lại?</summary>

- **A. Để một tốc độ đã giảm thực sự được thực thi — nếu giữ burst lớn, một đống token tích lũy có thể bắn dồn và lại chạm trần.**
- B. Để tiết kiệm bộ nhớ.
- C. Vì token bucket bắt buộc burst = rate.

Giải thích: Nếu rate xuống 5 nhưng burst vẫn 10, ngay sau đó có thể có 10 request bắn tức thì — phá vỡ mục đích giảm tốc. Token hiện có cũng bị kẹp về capacity mới.
</details>

<details>
<summary>4. "Cooldown toàn cục" khác gì với việc tôn trọng Retry-After như trước?</summary>

- A. Không khác, chỉ đổi tên.
- **B. Trước đây chỉ lời gọi đang lỗi ngủ đúng số giây; nay mọi worker đều chặn ở `acquire()` cho tới khi hết cửa sổ, nên cả đội cùng nghỉ.**
- C. Cooldown làm chương trình thoát hẳn.

Giải thích: Retry-After là lệnh của máy chủ cho *toàn bộ* project. Nghỉ chung tránh hiện tượng "đàn worker" tiếp tục nã trong lúc lẽ ra phải im.
</details>

<details>
<summary>5. Vì sao PR khẳng định không gây thoái lui hiệu năng ở trường hợp thường?</summary>

- A. Vì nó tắt pacer.
- **B. Vì AdaptivePacer *khởi đầu* đúng ở trần `--max-tps`; chỉ khi có throttle nó mới hạ tốc. Không throttle ⇒ hành vi giống pacer cố định cũ.**
- C. Vì nó tăng số luồng.

Giải thích: AIMD chỉ can thiệp khi có tín hiệu bị bóp. Cây không gặp giới hạn sẽ chạy y như trước, thậm chí ổn định hơn dưới tải.
</details>
