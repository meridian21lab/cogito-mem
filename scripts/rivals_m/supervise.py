#!/usr/bin/env python3
"""Run rival jobs one at a time, only while no other eval or test is running on this Mac.

    python supervise.py --base <rivals-m> --check <check_quiet.sh> --wait <wait_quiet.sh> setting:data:sample ...

Before each job and every 5 minutes during it, it runs the check. If something else has started, the job is stopped (rows
are flushed per question, so at most the question in progress is lost) and the supervisor waits until the check is empty
twice, 10 minutes apart, then resumes the job. Each job's running time and pauses go to rows/<job>.wall.json, so the
result file can say which jobs overlapped and for how long. Gives up after 24 hours of waiting in total.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from pathlib import Path

POLL_S = 300


def stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def say(text: str) -> None:
    print(f"{stamp()} {text}", flush=True)


class Supervisor:
    def __init__(self, base: Path, check: str, wait: str) -> None:
        self.base, self.check, self.wait = base, check, wait
        self.waited = 0.0

    def busy(self) -> str:
        proc = subprocess.run(["bash", self.check], capture_output=True, text=True)
        return proc.stdout.strip() if proc.returncode else ""

    def wait_quiet(self) -> None:
        t0 = time.time()
        proc = subprocess.run(["bash", self.wait], capture_output=True, text=True,
                              env={"PATH": "/usr/bin:/bin", "WAIT_START": os.environ.get("JOB_START", str(int(t0 - self.waited)))})  # fmt: skip
        self.waited += time.time() - t0
        say(f"wait ended: {proc.stdout.strip()}")
        if proc.returncode:
            raise SystemExit(f"still busy after 24 hours of waiting: {proc.stdout.strip()}")

    def run(self, job: str) -> None:
        setting, data, sample = job.split(":")
        record = self.base / "rows" / f"{setting}-{data}-{sample}.wall.json"
        wall = {"job": job, "running_s": 0.0, "started_utc": None, "finished_utc": None, "stops": []}
        if record.exists():
            wall = json.loads(record.read_text())
        if wall["finished_utc"]:
            say(f"{job}: already finished")
            return
        log = open(self.base / "rows" / f"{setting}-{data}-{sample}.log", "a")
        runner = "budget_one.sh" if setting.startswith("budget-") else "run_one.sh"
        cmd = ["bash", str(self.base / "adapters" / runner), setting, data, sample]
        while True:
            found = self.busy()
            if found:
                say(f"{job}: waiting, busy: {found[:300]}")
                self.wait_quiet()
                continue
            wall["started_utc"] = wall["started_utc"] or stamp()
            say(f"{job}: start")
            t0 = time.time()
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                    env={"PATH": "/usr/bin:/bin", "RIVALS_BASE": str(self.base), "HOME": os.environ.get("HOME", "")})  # fmt: skip
            stopped = None
            while proc.poll() is None:
                try:
                    proc.wait(POLL_S)
                except subprocess.TimeoutExpired:
                    stopped = self.busy()
                    if stopped:
                        say(f"{job}: stopping, overlap with: {stopped[:300]}")
                        subprocess.run(["/bin/kill", "-TERM", f"-{proc.pid}"])
                        try:
                            proc.wait(120)
                        except subprocess.TimeoutExpired:
                            subprocess.run(["/bin/kill", "-KILL", f"-{proc.pid}"])
                            proc.wait()
                        break
            wall["running_s"] += time.time() - t0
            if stopped:
                wall["stops"].append({"at": stamp(), "overlap": stopped[:600]})
                record.write_text(json.dumps(wall, indent=2))
                self.wait_quiet()
                continue
            record.write_text(json.dumps(wall, indent=2))
            if proc.returncode:
                say(f"{job}: FAILED, exit {proc.returncode}; see its log")
                return
            wall["finished_utc"] = stamp()
            record.write_text(json.dumps(wall, indent=2))
            say(f"{job}: finished in {wall['running_s']:.0f} s running time")
            return


def main() -> int:
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", required=True)
    p.add_argument("--check", required=True)
    p.add_argument("--wait", required=True)
    p.add_argument("jobs", nargs="+")
    args = p.parse_args()
    sup = Supervisor(Path(args.base), args.check, args.wait)
    for job in args.jobs:
        sup.run(job)
    say(f"all jobs done; waited {sup.waited:.0f} s in this supervisor")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
