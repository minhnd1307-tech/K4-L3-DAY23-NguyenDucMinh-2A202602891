# Runbook 1 trang — Region chính down

Runbook phục vụ phản ứng sự cố lúc 3h sáng cho kỹ sư On-call SRE. Có thể chạy qua Automation (khuyên dùng) hoặc thao tác Thủ công từng bước.

---

## Cách 1: Chạy Tự Động Hóa (Recommended Automation)

Chạy lệnh bán tự động duy nhất (yêu cầu xác nhận y/N của operator trước khi cutover):
```bash
python dr/runbook.py --primary a --target b --backend fs
```
Script tự động thực thi tuần tự 7 bước: xác nhận outage -> cảnh báo & xin xác nhận -> khôi phục snapshot & scale pool -> DNS cutover -> bắn 10 request kiểm chứng golden signals -> ghi nhận timeline sự cố vào `reports/runbook-run.jsonl`.

---

## Cách 2: Quy trình Thủ Công Từng Bước (Manual Execution)

Dùng khi hệ thống tự động hóa gặp sự cố hoặc cần can thiệp từng bước có kiểm soát:

| # | Bước | Lệnh thực thi (Execution) | Lệnh kiểm chứng & Tiêu chuẩn hoàn thành (Verification) | Ai làm |
|---|---|---|---|---|
| 1 | Xác nhận outage | `for i in 1 2 3; do curl -s -m 2 localhost:8001/readyz \|\| echo "FAIL"; sleep 5; done` | 3 lần liên tiếp đều FAIL (503/timeout); đồng thời `curl -s localhost:8002/healthz` trả 200 (target còn sống) | On-call SRE |
| 2 | Mở incident + bấm giờ RTO | Thông báo kênh incident `#incident-ai` và lưu mốc: `date -u +"%Y-%m-%dT%H:%M:%SZ"` | Kênh incident được kích hoạt, Incident Commander tiếp nhận chỉ huy | Incident Commander |
| 3 | Restore state ở region phụ | `python state/snapshot.py get --region b --backend fs` | `state/region-b/vectors.sqlite` và `weights/model.bin` tồn tại; `python state/snapshot.py lag --backend fs` xác nhận RPO | DR Engineer / SRE |
| 4 | Scale pool warm→full | `printf full > state/region-b/pool_state` | Poll `curl -s localhost:8002/readyz` cho tới khi trả HTTP 200 (`ready: true`, GPU warmup xong sau ~6s) | SRE |
| 5 | DNS/LB cutover | `printf b > edge/active_region` | `curl -s localhost:8080/edge/state` trả về `"active_region": "b"` | SRE |
| 6 | Verify golden signals | Bắn 10 request thật:<br>`for i in $(seq 1 10); do curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" "http://localhost:8080/v1/infer?q=check$i"; done` | 10/10 request trả HTTP 200 (Error rate = 0%), P95 latency < 50ms, response xác nhận `served_by: "b"` | On-call SRE |
| 7 | Đo RTO + postmortem | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | Kết quả trả về `"rto_verdict": "PASS"`, lưu bằng chứng và mở phiên họp postmortem | Incident Commander |

---

## Quy định Rollback (Failback về Region A)

**Điều kiện cần và đủ để trả traffic về Region A:**
1. **Region A hoàn toàn ổn định:** Hạ tầng Region A đã được khắc phục, `curl localhost:8001/readyz` trả HTTP 200 liên tục trong tối thiểu 15 phút.
2. **Reverse Replication hoàn tất:** Dữ liệu mới phát sinh tại Region B trong thời gian sự cố đã được đồng bộ ngược về Region A (`docs_lost = 0`).
3. **Cửa sổ bảo trì:** Quá trình failback chỉ thực hiện trong Maintenance Window có kiểm soát tải.

**Thẩm quyền quyết định:** Chỉ có **Incident Commander** hoặc **Head of Infrastructure** được quyền ra lệnh failback thủ công. Tuyệt đối **KHÔNG cấu hình auto-failback** để tránh hiện tượng mạng dao động gây flapping 2 chiều liên tục.
