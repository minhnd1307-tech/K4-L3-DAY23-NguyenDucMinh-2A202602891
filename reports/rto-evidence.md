# RTO/RPO Evidence - Lab 23

Quy tac duy nhat: moi con so o day phai tro duoc ve mot dong log that
(duong/dan.jsonl:so_dong). pytest tests/test_rto_evidence.py se mo tung file ra kiem tra.
Con so khong co evidence = truot, bat ke cac phan khac.

## 1. Drill 1 - khong co DR (baseline)

| Chi so | Gia tri | Cach do | Evidence |
|---|---|---|---|
| t_outage | `2026-10-09T04:33:26` | chaos kill | `chaos/chaos-events.jsonl:1` |
| Request fail dau tien | `+0.2s` | dong ok:false dau tien sau t_outage | `reports/drill-1-nodr.jsonl:18` |
| Request thanh cong sau do | khong co | khong co dong ok:true nao sau t_outage | `reports/measure-drill-1.json` |
| RTO | `NO_RECOVERY` | tools/measure_rto.py | `reports/measure-drill-1.json` |

## 2. Drill 2 - co DR

| Moc | +giay tu t_outage | Cach do | Evidence |
|---|---|---|---|
| t_outage (moc 0) | 0 | action:kill | `chaos/chaos-events.jsonl:3` |
| User thay loi dau tien | +0.4s | dong ok:false dau | `reports/drill-2-withdr.jsonl:27` |
| Health check phat hien | +14.5s | to:UNHEALTHY, region:a | `reports/health-events.jsonl:2` |
| Snapshot restore xong | +16.6s | step:2_restore_snapshot | `reports/failover-events.jsonl:2` |
| Region phu ready | +22.8s | step:4_wait_ready | `reports/failover-events.jsonl:4` |
| DNS cutover | +22.8s | step:5_dns_cutover | `reports/failover-events.jsonl:5` |
| **RTO do duoc** | +26.7s | dong ok:true dau sau loi | `reports/drill-2-withdr.jsonl:40` |

| Chi so | Do duoc | Muc tieu (slide 1) | Verdict |
|---|---|---|---|
| RTO - Inference API | `26.7s` | 300s (5 phut) | PASS |
| RPO - Vector DB | `4.0s` / `2` doc | 300s (5 phut) | PASS |

## 3. RTO cua toi gom nhung gi (bat buoc - day la phan cham diem hieu bai)

| Thanh phan | Giay | No den tu dau | Giam duoc bang cach nao |
|---|---|---|---|
| Health-check detect floor | 15.0s | interval_s * threshold trong `reports/health-events.jsonl:2` | Giam interval xuong 2s hoac threshold xuong 2 (doi lai tang nguy co flapping) |
| Snapshot restore | 2.1s | 2_restore_snapshot trong `reports/failover-events.jsonl:2` (t_restore 16.6s - t_detect 14.5s) | Dung CDC streaming replication hoac luu snapshot tren NVMe/S3 da vung |
| GPU pool warm-up | 6.2s | waited_s o 4_wait_ready trong `reports/failover-events.jsonl:4` | Dung hot standby (scale full san) hoac pre-warm model weights |
| DNS/LB TTL cache | 3.9s | t_recovered - t_cutover (`reports/drill-2-withdr.jsonl:40` - `reports/failover-events.jsonl:5`) | Giam DNS TTL xuong 1s hoac dung Anycast IP routing / Layer 4 Load Balancer |
