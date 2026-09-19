# Performance

## Available baselines

The only reported benchmark result so far is a synthetic 205 KB policy analysis in **1.405 s** and terms analysis in **0.642 s**. The first spaCy import was about **20 s**; warm suites were about **2 s**. These measurements were taken during the initial build on macOS 27 arm64 and are not a release benchmark.

The policy measurement is within the project’s 2.5-second offline policy budget for that one fixture. The cold spaCy import is an unresolved performance risk against the 3-second tray-ready objective, so the implementation relies on lazy loading and no claim of cold-start compliance is made.

The corrected native-Cocoa five-minute baseline (12:57–13:02) measured tray readiness at **2.51014 s**, peak RSS at **151.828 MiB**, warm median RSS at **131.656 MiB**, and cumulative CPU at **0.10126%**. It meets the startup, 200 MB RSS, and under-1% CPU targets for that build. A new light-worker-retention change needs a final re-measurement, so these values do not automatically apply to the latest source.

Document-path measurements include a 38 MB mixed PDF at **1.4866 s cold** and **0.1633 s warm**. The 5 MiB text latency test passes its allowed 25% tolerance. The exact raw-passport browser flow is still **1.83–2.39 s**, above the 1.5-second target, and is being optimized.

## Targets and status

| Target | Status |
|---|---|
| Idle CPU under 1% averaged over 5 minutes | 0.10126% on corrected baseline; final re-measurement pending |
| Idle RSS under 200 MB | Peak 151.828 MiB, warm median 131.656 MiB; final re-measurement pending |
| Form observation to badge ≤300 ms | Headed browser coverage exists; final aggregate latency pending |
| File up to 5 MB to decision ≤1.5 s | 5 MiB text tolerance test passes; raw passport 1.83–2.39 s remains over target |
| Consent verdict ≤400 ms | 213.5 ms; consent CPU 0.05 ms |
| 200 KB policy offline ≤2.5 s | One 205 KB synthetic policy: 1.405 s; repeatable perf test TODO |
| Cold start to tray-ready ≤3 s | 2.51014 s corrected baseline; final re-measurement pending |

## Measurement notes

The project’s perf suite measures controlled paths and permits a 25% tolerance where configured. Clipboard evidence is 185.7 ms for the real clipboard/spawn-worker path; an earlier 7.6 ms inline-pool number is superseded. Do not compare isolated policy/terms timings directly with UI or browser latency: they do not include process startup, browser transport, rendering, or OCR.
