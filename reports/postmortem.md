# Postmortem - DR Drill Lab 23

Blameless Postmortem: cau hoi la he thong/process nao cho phep chuyen nay xay ra, khong phai ai lam sai.

## 1. Timeline (moi dong co evidence path:line)

| ISO time | Su kien | Evidence |
|---|---|---|
| 2026-10-09T05:10:59 | outage bat dau | `chaos/chaos-events.jsonl:3` |
| 2026-10-09T05:10:59 | user dau tien bi anh huong | `reports/drill-2-withdr.jsonl:27` |
| 2026-10-09T05:11:13 | health check alert | `reports/health-events.jsonl:2` |
| 2026-10-09T05:11:15 | operator confirm cutover | `reports/runbook-run.jsonl:2` |
| 2026-10-09T05:11:25 | resolved (request dau tien OK tu region phu) | `reports/drill-2-withdr.jsonl:40` |

## 2. RTO/RPO do duoc vs muc tieu - gap o buoc nao?

- RTO muc tieu: 300s - do duoc: 26.7s - gap: +273.3s (dat muc tieu, vuot tien do 273.3s)
- RPO muc tieu: 300s - do duoc: 4.0s (2 doc bi mat) - gap: +296.0s (dat muc tieu, that thoat cuc thap)
- **Buoc ton nhieu giay nhat:** Health-check detect floor (14.5s) - vi co che anti-flapping bat buoc 3 lan probe lien tiep that bai voi chu ky 5 giay, chiem 54.3% tong thoi gian RTO.

## 3. Root cause (5 whys)

1. **Tai sao user nhan loi 503?** Do Region A khong phan hoi request suy luan cua nguoi dung.
2. **Tai sao Region A khong phan hoi?** Do bi netblock lam nghen ket noi TCP toi tien trinh serving.
3. **Tai sao he thong khong phuc vu ngay tu Region B?** Do Region B la warm standby, chua co model weights va vector DB rong (count: 0).
4. **Tai sao mat 26.7s moi phuc hoi sang Region B?** Do mat 14.5s de health checker phat hien su co chac chan (anti-flapping), 2.1s de keo snapshot va 6.2s de GPU pool warm up.
5. **Neu day la su co that, buoc nao trong runbook co nguy co that bai?** Buoc 2 (2_restore_snapshot) co nguy co hong cao nhat neu qua trinh replication giua cac cloud region bi tre hoac artifact snapshot bi loi phien ban model embedding.

## 4. Action items (co owner + deadline)

| # | Action | Owner | Deadline | Giam RTO/RPO bao nhieu giay |
|---|---|---|---|---|
| 1 | Cau hinh Pre-warm Model Weights tai Region B (hot standby) | ML Platform Team | 2026-11-01 | Giam 6.0s RTO (bo thoi gian GPU warmup) |
| 2 | Chuyen co che replicate tu batch snapshot 30s sang CDC streaming replication | Data Infra Team | 2026-11-15 | Giam RPO ve < 1.0s va 0 document bi mat |

## 5. Ba cau hoi bat buoc tra loi

1. `interval * threshold` cua ban la bao nhieu giay? No chiem bao nhieu % RTO?
   - `interval * threshold` la **15.0s** (5.0s * 3). No chiem **56.2%** tong thoi gian RTO (15.0s / 26.7s).
2. Neu ha interval xuong 1s, RTO giam may giay - va ban tra gia gi (flapping)?
   - RTO se giam khoang **12.0s** (thoi gian phat hien giam tu 15s xuong 3s). Tuy nhien cai gia phai tra la nguy co cao gap **flapping**: chi can mang chap chon hoac latency tang dot bien trong 3 giay la he thong se kich hoat failover nham, lam dao chieu luong luu luong lien tuc, gay gian doan dich vu va nguy co phan manh du lieu (split-brain).
3. Neu outage keo dai 6 gio va region chinh mat du lieu vinh vien, `docs_lost` cua ban co nghia gi voi khach hang?
   - `docs_lost = 2` co nghia la co **2 ban ghi/ticket cua khach hang** gui vao he thong trong khoang 4.0s truoc su co da bi mat vinh vien. Nhung khach hang nay se bi mat du lieu phien lam viec do va he thong can co che thong bao cho client thuc hien retry hoac thuc hien doi soat log giao dich de bu du lieu.
