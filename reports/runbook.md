# Runbook 1 trang — Region chính down

Runbook phải chạy được lúc 3h sáng bởi người KHÔNG viết nó. Mỗi bước: lệnh copy-paste
được + cách biết bước đó xong.

| # | Bước | Lệnh | Biết là xong khi | Ai làm |
|---|---|---|---|---|
| 1 | Xác nhận outage | `curl -s localhost:8001/readyz` | HTTP 503 hoặc timeout 3 lần liên tiếp; `localhost:8002/healthz` trả HTTP 200 | On-call SRE |
| 2 | Mở incident + bấm giờ RTO | `python dr/runbook.py --primary a --target b --backend fs` | Ghi nhận sự kiện vào `reports/runbook-run.jsonl`, thông báo kênh incident | Incident Commander |
| 3 | Restore state ở region phụ | `python state/snapshot.py get --region b --backend fs` | File `vectors.sqlite` và `weights/model.bin` xuất hiện tại `state/region-b/` | DR Automation / SRE |
| 4 | Scale pool warm→full | `printf full > state/region-b/pool_state` | `curl -s localhost:8002/readyz` trả về HTTP 200 (`ready: true`, warmup GPU xong) | DR Automation / SRE |
| 5 | DNS/LB cutover | `printf b > edge/active_region` | `curl -s localhost:8080/edge/state` trả về `"active_region": "b"` | DR Automation / SRE |
| 6 | Verify golden signals | `curl -s "http://localhost:8080/v1/infer?q=test"` | 100% trả về 200 từ `region: "b"`, error rate = 0%, p95 latency < 50ms | On-call SRE |
| 7 | Đo RTO + postmortem | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | Kết quả trả về `"rto_verdict": "PASS"`, bắt đầu viết postmortem | Incident Commander |

**Rollback (failover ngược):** điều kiện nào thì trả traffic về region A? Ai quyết định?
- **Điều kiện failback:**
  1. Region A đã được sửa xong lỗi hạ tầng, sống lại và `/readyz` trả 200 liên tục trong ít nhất 15 phút.
  2. Toàn bộ dữ liệu mới phát sinh tại Region B đã được replicate ngược về Region A (reverse replication) để đảm bảo không mất dữ liệu (`docs_lost = 0`).
  3. Quá trình failback chỉ thực hiện trong cửa sổ bảo trì (maintenance window), có giám sát lưu lượng.
- **Quyền quyết định:** Chỉ có **Incident Commander** hoặc **Head of Infrastructure** được quyền phê duyệt lệnh failback thủ công. Tuyệt đối **KHÔNG tự động failback (No Full-Auto Failback)** để tránh hiện tượng mạng chập chờn gây flapping 2 chiều liên tục.
