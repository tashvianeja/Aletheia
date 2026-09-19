# Performance

## Available baselines

The only reported benchmark result so far is a synthetic 205 KB policy analysis in **1.405 s** and terms analysis in **0.642 s**. The first spaCy import was about **20 s**; warm suites were about **2 s**. These measurements were taken during the initial build on macOS 27 arm64 and are not a release benchmark.

The policy measurement is within the project’s 2.5-second offline policy budget for that one fixture. The cold spaCy import is an unresolved performance risk against the 3-second tray-ready objective, so the implementation relies on lazy loading and no claim of cold-start compliance is made.

The final 300-second native-Cocoa whole-tree measurement recorded tray readiness at **0.823200875 s**, initial RSS at **200.5 MiB**, warm median RSS at **197.734375 MiB**, peak RSS at **200.78125 MiB**, final RSS at **192.78125 MiB**, and cumulative CPU at **0.0442277493%**. The warm median is below the 200 MiB criterion and CPU is below 1%; peak RSS exceeds 200 MiB by 0.78125 MiB. The product target is written in MB while this script reports MiB, so these units are retained rather than treated as interchangeable.

Document-path measurements include a 38 MB mixed PDF at **1.4866 s cold** and **0.1633 s warm**. The bounded 5 MiB full-text path now uses full tail inspection and passes the current 25%-tolerance gate; an implementation diagnostic measured **1.762 s** with full NER, below the 1.875-second tolerated threshold but still 0.262 seconds above the raw 1.5-second target. Keep cold and connected measurements distinct. Intel policy timing remains an open optimization: 205 KB measured 3.39851 seconds against its 3.125-second 25%-tolerance gate.

## Targets and status

| Target | Status |
|---|---|
| Idle CPU under 1% averaged over 5 minutes | 0.0442277493% over 300 seconds |
| Idle RSS under 200 MB | Warm median 197.734375 MiB passes; peak 200.78125 MiB is 0.78125 MiB over |
| Form observation to badge ≤300 ms | Headed browser coverage exists; final aggregate latency pending |
| File up to 5 MB to decision ≤1.5 s | Bounded 5 MiB full-text path passes the 1.875 s tolerance gate; diagnostic 1.762 s remains over raw 1.5 s |
| Consent verdict ≤400 ms | 213.5 ms; consent CPU 0.05 ms |
| 200 KB policy offline ≤2.5 s | ARM synthetic policy: 1.405 s; Intel 3.39851 s exceeds the 3.125 s tolerance gate and is being optimized |
| Cold start to tray-ready ≤3 s | 0.823200875 s on the final 300-second measurement |

## Measurement notes

The project’s perf suite measures controlled paths and permits a 25% tolerance where configured. Clipboard evidence is 185.7 ms for the real clipboard/spawn-worker path; an earlier 7.6 ms inline-pool number is superseded. Do not compare isolated policy/terms timings directly with UI or browser latency: they do not include process startup, browser transport, rendering, or OCR.
