"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n, name, **kw):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "step": n,
        "name": name,
        **kw,
    }
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"RUNBOOK [{n}] {name}:", json.dumps(rec))
    return rec


def confirm(auto: bool, msg: str) -> bool:
    if auto:
        return True
    ans = input(f"{msg} [y/N]: ").strip().lower()
    return ans in ("y", "yes")


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    t_start = time.time()

    # Tìm mốc t_outage gần nhất nếu có
    chaos_events = pathlib.Path("chaos/chaos-events.jsonl")
    t_outage = None
    if chaos_events.exists():
        for line in chaos_events.read_text().splitlines():
            if line.strip():
                try:
                    ev = json.loads(line)
                    if ev.get("action") == "kill":
                        t_outage = ev.get("ts")
                except Exception:
                    pass

    # Bước 1: Xác nhận outage — chờ health check phát hiện hoặc probe xác nhận
    health_log = pathlib.Path("reports/health-events.jsonl")
    for _ in range(30):
        detected = False
        if health_log.exists():
            for line in health_log.read_text().splitlines():
                if line.strip():
                    try:
                        ev = json.loads(line)
                        if (ev.get("region") == primary and ev.get("to") == "UNHEALTHY"
                                and (not t_outage or ev.get("ts", 0) >= t_outage)):
                            detected = True
                            break
                    except Exception:
                        pass
        if detected:
            break
        try:
            with httpx.Client(timeout=1.0) as c:
                if c.get(f"{URL[primary]}/readyz").status_code == 200:
                    time.sleep(1.0)
                    continue
        except Exception:
            pass
        time.sleep(1.0)

    prim_dead = False
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{URL[primary]}/readyz")
            prim_dead = (r.status_code != 200)
    except Exception:
        prim_dead = True

    target_alive = False
    try:
        with httpx.Client(timeout=2.0) as c:
            r = c.get(f"{URL[target]}/healthz")
            target_alive = (r.status_code == 200)
    except Exception:
        target_alive = False

    step(1, "xac_nhan_outage", primary=primary, primary_down=prim_dead,
         target=target, target_alive=target_alive)

    # Chặn failover nếu primary vẫn sống hoặc target không phản hồi
    if not prim_dead:
        return {"ok": False, "aborted": True,
                "error": f"Region chinh ({primary}) van dang hoat dong binh thuong, huy failover"}

    if not target_alive:
        return {"ok": False, "aborted": True,
                "error": f"Region phu ({target}) khong alive, huy failover de tranh double outage"}

    # Bước 2: Thông báo incident & xác nhận
    t_operator = time.time()
    operator_latency = round(t_operator - t_outage, 2) if t_outage else 0.0

    if not confirm(auto, f"XAC NHAN: Failover tu region-{primary} sang region-{target}?"):
        step(2, "thong_bao_incident", confirmed=False, aborted=True)
        return {"ok": False, "aborted": True}

    step(2, "thong_bao_incident", confirmed=True, t_outage=t_outage,
         t_operator=t_operator, operator_latency_s=operator_latency)

    # Bước 3: Scale GPU pool & Failover
    fo_res = fo.failover(target=target, backend=backend, wait=60.0)
    step(3, "scale_gpu_pool", ok=fo_res.get("ok"), target=target)
    if not fo_res.get("ok"):
        return {"ok": False, "error": "Failover execution failed", "detail": fo_res}

    # Bước 4: Verify state replica
    step(4, "verify_state_replica",
         rpo_seconds=fo_res.get("rpo_seconds"),
         docs_lost=fo_res.get("docs_lost"))

    # Bước 5: DNS cutover
    step(5, "dns_cutover", active_region=target, ok=fo_res.get("ok"))

    # Bước 6: Verify golden signals (10 request thật)
    latencies = []
    errors = 0
    with httpx.Client(timeout=3.0) as c:
        for i in range(10):
            t0 = time.time()
            try:
                resp = c.get(f"{URL[target]}/v1/infer", params={"q": f"test query {i}"})
                lat = round((time.time() - t0) * 1000, 1)
                latencies.append(lat)
                if resp.status_code != 200:
                    errors += 1
            except Exception:
                errors += 1
                latencies.append(3000.0)

    latencies.sort()
    # P95 trong 10 phần tử là index 9
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    err_rate = round(errors / 10.0, 2)
    step(6, "verify_golden_signals", total_requests=10, error_rate=err_rate, p95_ms=p95)

    if err_rate > 0.0:
        return {
            "ok": False,
            "error": f"Golden signals verification failed: error_rate={err_rate*100:.1f}%, p95={p95}ms",
            "primary": primary,
            "target": target,
            "elapsed_s": round(time.time() - t_start, 2),
            "p95_latency_ms": p95,
            "error_rate": err_rate,
        }

    # Bước 7: Post incident
    elapsed = round(time.time() - t_start, 2)
    step(7, "post_incident", elapsed_s=elapsed,
         measure_cmd="python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300")

    return {
        "ok": True,
        "primary": primary,
        "target": target,
        "elapsed_s": elapsed,
        "rpo_seconds": fo_res.get("rpo_seconds"),
        "docs_lost": fo_res.get("docs_lost"),
        "p95_latency_ms": p95,
        "error_rate": err_rate,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
