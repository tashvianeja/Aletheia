# Performance

## Available baselines

The final 205 KB policy measurement was **0.306559 s** in the root run and **0.346333 s** in an independent Sol run, within the 2.5-second target. These replace the earlier initial-build policy baseline. Cold spaCy import remains intentionally lazy; it is not part of tray readiness.

The final 300-second native-Cocoa whole-tree measurement recorded tray readiness at **0.823200875 s**, initial RSS at **200.5 MiB**, warm median RSS at **197.734375 MiB** (**207.33952 MB**), peak RSS at **200.78125 MiB** (**210.5344 MB**), final RSS at **192.78125 MiB**, and cumulative CPU at **0.0442277493%**. CPU meets its target. The raw decimal-200-MB criterion is missed by **7.33952 MB** at the median and **10.5344 MB** at peak, although the configured 25% tolerance gate passes. The script reports MiB; both units are shown to avoid treating them as interchangeable.

Document-path measurements include a 38 MB mixed PDF at **1.4866 s cold** and **0.1633 s warm**. The bounded full 5 MiB text scan measured **1.822472 s**: it misses the raw 1.5-second target by **0.322472 s**, while passing the 1.875-second 25%-tolerance gate. Keep cold and connected measurements distinct. Intel policy performance passed at `d3390ba`; its historical passport DOM warning was 2.1257 seconds, **0.6257 s** over the 1.5-second raw target and **0.2507 s** over the 1.875-second tolerated target. The completed later Intel job `105910359735` passed installed lifecycle at 14:40:13, but measured passport DOM at **3.1154 s**: **+1.6154 s** raw and **+1.2404 s** over the tolerated target. Its other runtime cases had 33 passes and one skip; no threshold was changed.

## On-device sentence encoder

Adding the form-intent encoder was measured on the ARM development machine at `analyze_fields` level. Loading `onnxruntime` plus the int8 weights costs **+95.0 MB resident**; the first judgement including that load is **135.1 ms**, and reloading after an idle release is **31 ms**, both inside the 300 ms form-observation budget. Steady-state judgement is **0.08 ms** median on an unchanged page (embeddings are cached by text) and **2.51 ms** median when every page is new. The existing 40-field microbenchmark moved from roughly 1 ms to **27.9 ms** against its 300 ms budget.

The resident cost is the reason the session is released after 90 idle seconds rather than held: the idle-memory target is already exceeded, and a permanently loaded encoder would push the median from 207.3 MB to roughly 302 MB. Idle figures in the table below predate the encoder and have not been re-measured with it; the release path is what keeps them applicable, and a fresh whole-tree run is pending.

## Targets and status

| Target | Status |
|---|---|
| Idle CPU under 1% averaged over 5 minutes | 0.0442277493% over 300 seconds |
| Idle RSS under 200 MB | Raw decimal target misses: median 207.33952 MB (+7.33952 MB), peak 210.5344 MB (+10.5344 MB); 25% tolerance gate passes |
| Form observation to badge ≤300 ms | Connected DOM badge 137.8 ms; separate host-side comparison 252.649 ms |
| File up to 5 MB to decision ≤1.5 s | Full 5 MiB scan 1.822472 s: raw target missed by 0.322472 s; 1.875 s tolerance gate passes |
| Consent verdict ≤400 ms | 213.5 ms; consent CPU 0.05 ms |
| 200 KB policy offline ≤2.5 s | 0.306559 s root / 0.346333 s independent Sol |
| Cold start to tray-ready ≤3 s | 0.823200875 s on the final 300-second measurement |

## Measurement notes

The project’s perf suite measures controlled paths and permits a 25% tolerance where configured. Clipboard evidence is 185.7 ms for the real clipboard/spawn-worker path; an earlier 7.6 ms inline-pool number is superseded. Do not compare isolated policy/terms timings directly with UI or browser latency: they do not include process startup, browser transport, rendering, or OCR.

Known raw misses are retained rather than averaged away: the native-Cocoa warm median is **+7.33952 MB** over the decimal 200-MB target; the full 5 MiB scan is **+0.322472 s** over its raw target; the latest completed Intel passport DOM run was **+1.6154 s** (an earlier Intel run was +0.6257 s); an ARM cold-bridge run was **+1.552899 s** over its five-second raw target; and a Windows policy run was **+2.702934 s** over the 2.5-second raw target while orphaned processes remained. The latter condition is suspected, not established, as a contributor. The Windows measurement has not been rerun after process-cleanup fixes, so it is diagnostic evidence rather than a current Windows performance result.
