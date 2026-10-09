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
| 1 | Xác nhận outage | `for i in 1 2 3; do curl -sf -m 2 localhost:8001/readyz >/dev/null \|\| echo "FAIL"; sleep 5; done` | 3 lần liên tiếp đều trả về FAIL (nhờ cờ `-f` bắt đúng cả HTTP 503 và timeout); đồng thời `curl -sf localhost:8002/healthz` trả HTTP 200 (target còn sống) | On-call SRE |
| 2 | Mở incident + bấm giờ RTO | Thông báo kênh incident `#incident-ai` và lưu mốc: `date -u +"%Y-%m-%dT%H:%M:%SZ"` | Kênh incident được kích hoạt, Incident Commander tiếp nhận chỉ huy | Incident Commander |
| 3 | Restore state ở region phụ | `python state/snapshot.py get --region b --backend fs` | File `state/region-b/vectors.sqlite` và `weights/model.bin` tồn tại;<br>Kiểm chứng RPO thật giữa DB A và B:<br>`python -c "import pathlib, sys; sys.path.insert(0, '.'); from state import snapshot; print(snapshot.rpo(pathlib.Path('state/region-a/vectors.sqlite'), pathlib.Path('state/region-b/vectors.sqlite')))"`<br>trả về cả `rpo_seconds` và `docs_lost` | DR Engineer / SRE |
| 4 | Scale pool warm→full | `printf full > state/region-b/pool_state` | Poll `curl -sf localhost:8002/readyz` cho tới khi trả HTTP 200 (`ready: true`, GPU warmup xong sau ~6s) | SRE |
| 5 | DNS/LB cutover | `printf b > edge/active_region` | `curl -s localhost:8080/edge/state` trả về `"active_region": "b"` | SRE |
| 6 | Verify golden signals | Bắn 10 request kiểm tra và trích xuất region phục vụ:<br>`for i in $(seq 1 10); do curl -s "http://localhost:8080/v1/infer?q=check$i" \| grep -o '"region":"[^"]*"'; done` | 10/10 dòng in ra đều là `"region":"b"`, HTTP status 200 (Error rate = 0%), P95 latency < 50ms | On-call SRE |
| 7 | Đo RTO + postmortem | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | Kết quả trả về `"rto_verdict": "PASS"`, lưu bằng chứng và mở phiên họp postmortem | Incident Commander |

---

## Quy định Rollback (Failback về Region A)

**Điều kiện cần và đủ để trả traffic về Region A:**
1. **Region A hoàn toàn ổn định:** Hạ tầng Region A đã được khắc phục, `curl localhost:8001/readyz` trả HTTP 200 liên tục trong tối thiểu 15 phút.
2. **Reverse Replication hoàn tất:** Dữ liệu mới phát sinh tại Region B trong thời gian sự cố đã được đồng bộ ngược về Region A (`docs_lost = 0`).
3. **Cửa sổ bảo trì:** Quá trình failback chỉ thực hiện trong Maintenance Window có kiểm soát tải.

**Thẩm quyền quyết định:** Chỉ có **Incident Commander** hoặc **Head of Infrastructure** được quyền ra lệnh failback thủ công. Tuyệt đối **KHÔNG cấu hình auto-failback** để tránh hiện tượng mạng dao động gây flapping 2 chiều liên tục.
