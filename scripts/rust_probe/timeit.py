"""Run a command N times with a file on stdin; print median / p95 / min wall time in ms."""
import statistics, subprocess, sys, time
n, stdin_path, *cmd = sys.argv[1:]
data = open(stdin_path, "rb").read() if stdin_path != "-" else b""
ms = []
for _ in range(int(n)):
    t = time.perf_counter()
    r = subprocess.run(cmd, input=data, capture_output=True)
    ms.append((time.perf_counter() - t) * 1000)
ms.sort()
print(f"median {statistics.median(ms):7.1f}  p95 {ms[min(len(ms)-1, int(round(0.95*len(ms)))-1)]:7.1f}  min {ms[0]:7.1f} ms  exit {r.returncode}  out {len(r.stdout)} bytes   {' '.join(cmd)[-70:]}")
