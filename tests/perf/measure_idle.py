from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import psutil

from privacy_guardian.config import Settings


def process_tree(process: psutil.Process) -> list[psutil.Process]:
    try:
        return [process, *process.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return [process]


def tree_rss(process: psutil.Process) -> int:
    total = 0
    for member in process_tree(process):
        try:
            total += member.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def tree_cpu_snapshot(process: psutil.Process) -> dict[int, float]:
    result: dict[int, float] = {}
    for member in process_tree(process):
        try:
            cpu = member.cpu_times()
            result[member.pid] = cpu.user + cpu.system
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return result


def main(duration: float = 300.0) -> int:
    with tempfile.TemporaryDirectory(
        prefix="pg-perf-", dir="/tmp" if sys.platform != "win32" else None
    ) as data_dir:
        Settings(data_dir=Path(data_dir), autostart=False, onboarding_complete=True).save()
        environment = os.environ.copy()
        environment["PRIVACY_GUARDIAN_DATA_DIR"] = data_dir
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        started = time.perf_counter()
        child = subprocess.Popen(
            [sys.executable, "-m", "privacy_guardian"],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        process = psutil.Process(child.pid)
        samples: list[tuple[float, int]] = []
        ready_at: float | None = None
        launch_deadline = time.monotonic() + 15
        idle_deadline: float | None = None
        cpu_previous: dict[int, float] = {}
        cpu_total = 0.0
        try:
            while idle_deadline is None or time.monotonic() < idle_deadline:
                if child.poll() is not None:
                    raise RuntimeError(f"desktop app exited: {child.stderr.read()}")
                elapsed = time.perf_counter() - started
                if ready_at is None and (Path(data_dir) / "tray-ready").exists():
                    ready_at = elapsed
                    # Report cold start separately, then allow background setup to settle.
                    idle_deadline = time.monotonic() + 10.0 + duration
                if ready_at is None and time.monotonic() > launch_deadline:
                    raise RuntimeError("desktop app did not write its tray-ready marker")
                idle_elapsed = elapsed - (ready_at or elapsed) - 10.0
                current_cpu = tree_cpu_snapshot(process)
                if idle_elapsed >= 0:
                    for pid, value in current_cpu.items():
                        prior = cpu_previous.get(pid)
                        if prior is not None:
                            cpu_total += max(0.0, value - prior)
                    if not samples or idle_elapsed - samples[-1][0] >= 5.0:
                        samples.append((idle_elapsed, tree_rss(process)))
                if idle_elapsed < 0:
                    cpu_previous = current_cpu
                else:
                    cpu_previous.update(current_cpu)
                time.sleep(0.05)
        finally:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)
        rss_values = [rss for _, rss in samples]
        warm_values = [rss for elapsed, rss in samples if elapsed >= min(30, duration / 2)]
        cpu_average = 100 * cpu_total / duration
        result = {
            "duration_seconds": duration,
            "tray_ready_seconds_upper_bound": ready_at,
            "samples": len(samples),
            "process_tree_rss_initial_mib": rss_values[0] / 1024**2,
            "process_tree_rss_warm_median_mib": statistics.median(warm_values) / 1024**2,
            "process_tree_rss_peak_mib": max(rss_values) / 1024**2,
            "process_tree_rss_final_mib": rss_values[-1] / 1024**2,
            "process_tree_cpu_average_percent": cpu_average,
            "budgets": {
                "tray_ready_seconds": 3.0,
                "idle_rss_mib": 200.0,
                "idle_cpu_percent": 1.0,
                "gate_tolerance_percent": 25,
            },
        }
        print(json.dumps(result, indent=2))
        if ready_at is None or ready_at > 3.75:
            return 1
        if statistics.median(warm_values) / 1024**2 > 250:
            return 1
        if cpu_average > 1.25:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 300.0))
