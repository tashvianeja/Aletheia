# Performance

## Available baselines

The only reported benchmark result so far is a synthetic 205 KB policy analysis in **1.405 s** and terms analysis in **0.642 s**. The first spaCy import was about **20 s**; warm suites were about **2 s**. These measurements were taken during the initial build on macOS 27 arm64 and are not a release benchmark.

The policy measurement is within the project’s 2.5-second offline policy budget for that one fixture. The cold spaCy import is an unresolved performance risk against the 3-second tray-ready objective, so the implementation relies on lazy loading and no claim of cold-start compliance is made.

An earlier full-app measurement reported 3.783 s startup, 151.69 MiB median RSS (148.13 MiB final), and 1.613% CPU. It failed the startup and idle-CPU targets; the CPU accounting also undercounted a retired worker. `tests/perf/measure_idle.py` has since been corrected to wait for tray readiness, settle for 10 seconds, and account for per-PID cumulative CPU. A replacement run is pending, so neither baseline is release performance evidence.

## Targets and status

| Target | Status |
|---|---|
| Idle CPU under 1% averaged over 5 minutes | Earlier 1.613% failed; corrected re-measurement pending |
| Idle RSS under 200 MB | Earlier median 151.69 MiB met target, but corrected final run pending |
| Form observation to badge ≤300 ms | TODO: extension/service E2E absent |
| File up to 5 MB to decision ≤1.5 s | TODO: no end-to-end measurement |
| Consent verdict ≤400 ms | TODO: no browser measurement |
| 200 KB policy offline ≤2.5 s | One 205 KB synthetic policy: 1.405 s; repeatable perf test TODO |
| Cold start to tray-ready ≤3 s | Earlier 3.783 s failed; lazy-NER fix and re-measurement pending |

## Measurement notes

The project’s intended `tests/perf/` suite should run under controlled conditions and fail when a budget is exceeded by more than 25%, as specified in the build plan. That suite and its artifact record are TODO. Do not compare the isolated policy/terms timings directly with UI or browser latency: they do not include process startup, browser transport, rendering, or OCR.
