# REDLAIN 3.0 implementation record

Baseline: `ee7c55d1062efd412c3767b2eec2194e68c1e1db`, 227 tests. Existing architecture inspected: PySide6 panel/studio/actions and QThread jobs; planner → painter/vector → normalized Plan/Stroke; DrawingExecutor → popup/HSV controls → Win32 SendInput; atomic JSON Store; local Qt canvas and screenshot feedback. Existing priority detection is CPU saliency/Haar, not semantic anime detection. Existing vector optimization already samples quadratic Bézier curves. No framework replacement is required.

Baseline reproduced with `tools/benchmark_v2.py`; raw result: `v3-baseline.json`. Actual app-local Qt event execution, not Roblox timing. Identical fixtures and execution conditions will be used for the comparison. Network and Windows-only checks must be reported separately.

Implementation sequence:

1. Backward-compatible stage metadata, seven-stage Human engine and measured timing breakdown.
2. Atomic project bundles, version/checksum validation, serialized checkpoint writer, exact cursor restoration and canvas verification.
3. Padding-only Smart Canvas Fill and editor; all decoration enters the image before stroke generation.
4. Event-driven Live Art Core, project/dashboard pages and premium desktop shell using existing controls.
5. Commons Discover with actual API results, provenance, bounded downloads, thumbnails/favorites/offline handling.
6. Speed presets and measured acceptance calibration; logo assets and Windows packaging.
7. Regression, local execution benchmarks, visual inspection, documentation, publish verified archive.

No claim of 10–20× acceleration, Roblox acceptance, semantic body-part recognition or restored server-side canvases is made without evidence.

Completed implementation and evidence:

- Seven-stage Human planner integrated with Legacy/Vector and calibrated controls. Large component masks are cropped, paths bounded, repairs capped. No semantic/AI claims.
- Versioned source/plan/masks/fill/checkpoints, fsync/atomic replacement and recovery manifest. Separate-process restore and fresh-UI resume both passed. Lost small strokes are rejected during canvas verification even on nearly blank canvases.
- Real event-driven Live Art Core, six-page shell, padding editor, actual Commons transport/cache/provenance/favorites, original SVG/PNG/ICO identity and Windows packaging integrated.
- Four-line physical acceptance calibration controls fast sampling. Cross-process OS input lease prevents conflicting senders. Native safeguards and old profiles remain.
- Fixed a native Qt exit crash by avoiding transient main-QThread wrappers in GuiBridge; repeated full suites and actual UI shutdown now exit 0.
- 261 tests passed, dependency compatibility check passed (33 installed packages), actual GUI startup/paused input captures passed at 1320×740 and 850×700.
- Repeated actual same-fixture Qt execution benchmark for Legacy/Vector and all Human modes. FAST measured 2.3–2.9× vs Vector, with a small landscape edge-quality tradeoff. Raw measurements in v3-benchmark.json; no 10–20× or Roblox speed claim.
- Official live Commons request was blocked by environment ProxyError 403. An additive environment-domain draft was saved but is not applied. Transport tests use explicit HTTP mocks; Windows normal Internet needs no Commons API key.
- Windows EXE, real SendInput and Roblox/server-disconnect tests cannot run in this Linux environment. Reproducible native checklist and limitations are supplied.

User guide, file/module report, benchmark/validation report and Windows/Roblox checklist are linked from README and START_HERE_RU.
