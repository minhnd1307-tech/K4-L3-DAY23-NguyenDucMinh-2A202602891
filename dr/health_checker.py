"""BƯỚC 3a — SINH VIÊN VIẾT. Health checker cho 2 region.

Yêu cầu (đọc §4 "Kiến Trúc Health-Check-Based Failover" + §2 "DNS Failover"):
  1. Poll /readyz của CẢ HAI region mỗi `interval` giây (mặc định 5s).
     Dùng /readyz, KHÔNG dùng /healthz. /healthz chỉ nói "process còn sống" —
     region có process sống nhưng vector DB rỗng thì vẫn không serve được.
  2. Chỉ đổi trạng thái sau `threshold` lần fail LIÊN TIẾP (mặc định 3).
     Một lần fail không phải outage. Đây là chống flapping (§4 Anti-Patterns).
  3. Ghi 1 dòng JSONL MỖI LẦN ĐỔI TRẠNG THÁI (không ghi mỗi lần poll — log sẽ ngập).
     Dòng bắt buộc có: ts, region, to (HEALTHY|UNHEALTHY), reason,
     interval_s, threshold. Thiếu interval_s/threshold thì tools/measure_rto.py
     không tính được detect floor -> mất điểm.

Chạy:  python dr/health_checker.py --interval 5 --threshold 3 --duration 300 \
              --out reports/health-events.jsonl

CÂU HỎI PHẢI TRẢ LỜI TRƯỚC KHI VIẾT (ghi câu trả lời vào reports/postmortem.md):
  interval=5s, threshold=3 -> sớm nhất bạn có thể phát hiện outage là bao nhiêu giây?
  Con số đó nằm TRONG RTO của bạn. Muốn RTO 5 phút thì được phép chọn interval bao nhiêu?
"""
import argparse
import json
import pathlib
import time

import httpx

URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def probe(region: str, timeout: float) -> tuple[bool, str]:
    url = f"{URL[region]}/readyz"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                return True, "ready"
            return False, f"status_{resp.status_code}"
    except httpx.TimeoutException:
        return False, "timeout"
    except httpx.ConnectError:
        return False, "connect_error"
    except Exception as e:
        return False, type(e).__name__



def run(interval: float, timeout: float, threshold: int, duration: float, out: pathlib.Path):
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    state = {"a": "HEALTHY", "b": "HEALTHY"}
    consecutive_fails = {"a": 0, "b": 0}

    end_time = time.time() + duration
    while time.time() < end_time:
        loop_start = time.time()
        for r in ["a", "b"]:
            ok, reason = probe(r, timeout)
            if ok:
                consecutive_fails[r] = 0
                if state[r] != "HEALTHY":
                    state[r] = "HEALTHY"
                    ev = {
                        "event": "state_change",
                        "ts": time.time(),
                        "region": r,
                        "from": "UNHEALTHY",
                        "to": "HEALTHY",
                        "reason": reason,
                        "consecutive_fails": 0,
                        "interval_s": interval,
                        "threshold": threshold,
                    }
                    with out.open("a") as f:
                        f.write(json.dumps(ev) + "\n")
            else:
                consecutive_fails[r] += 1
                if consecutive_fails[r] >= threshold and state[r] != "UNHEALTHY":
                    state[r] = "UNHEALTHY"
                    ev = {
                        "event": "state_change",
                        "ts": time.time(),
                        "region": r,
                        "from": "HEALTHY",
                        "to": "UNHEALTHY",
                        "reason": reason,
                        "consecutive_fails": consecutive_fails[r],
                        "interval_s": interval,
                        "threshold": threshold,
                    }
                    with out.open("a") as f:
                        f.write(json.dumps(ev) + "\n")

        elapsed = time.time() - loop_start
        sleep_time = max(0.0, interval - elapsed)
        time.sleep(sleep_time)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=float, default=5.0)
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--threshold", type=int, default=3)
    p.add_argument("--duration", type=float, default=300)
    p.add_argument("--out", default="reports/health-events.jsonl")
    a = p.parse_args()
    run(a.interval, a.timeout, a.threshold, a.duration, pathlib.Path(a.out))
