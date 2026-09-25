# Consolidated formal edition: measured baseline

The single formal document is
[TK-LPLUT-2.0](../../../output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf).
Runtime implementation was parked while it was prepared.

Evidence was captured on 25 September 2026 against clean commit
`8f4b87bed131f5c084ef59aec558f3f9eb6ddedc`, before documentation changes.

- `verification.json`: exact commands, commit, timestamps and exit codes.
- `full-tests.txt`: 262 passing tests, zero skipped; 21 actual-device GPU methods.
- `field-conformance.json`: all eight finite field checks pass.
- `cross-adapter-trace.json`: complete 64-tick CPU/GPU traces and both directions
  of 32+32 continuation, identical to uninterrupted execution.
- `cross-adapter-probe-source.txt`: source for that independent comparison.
- `readiness-matrix.json`: architecture-level scope and remaining work.
- `summary.txt`: concise measured facts.
- `pdf-quality.json`: final PDF hash, 34-page structural checks, link counts,
  text bounds, visual review and byte-identical rebuild result.

The GPU was an NVIDIA GeForce RTX 5070 Ti Laptop GPU, Vulkan driver 591.59,
using wgpu 0.32.0 and Python 3.12.14. The final 64-tick field pair was
`1102046C01020494`, at node `n4`. The Klein extension was specification only;
it has no runtime implementation at this baseline. These test counts are not
a completion percentage or a general performance claim.

Reproduce correctness with the GPU dependencies installed:

```sh
python -m unittest discover -s tests -v
python -m examples.field_conformance --output output/field-conformance.json
```

Rebuild the PDF with a Python environment containing ReportLab and pypdf:

```sh
python tools/build_formal_spec.py
```

The builder uses Segoe UI and Consolas from `C:/Windows/Fonts` by default;
`--font-dir` selects another directory containing those font files. It embeds
font subsets, creates bookmarks and linked contents, and rejects page overflow.
It is reproducible for the same font files and dependency versions. The final
artifact lives under `output/pdf/`; only that named PDF is tracked there.

Visual QA renders every page with Poppler. Page bounds and extracted content
are checked separately; all pages are reviewed in contact sheets and selected
dense/formal pages at full resolution. QA intermediates remain in ignored
`tmp/pdfs/` and are not part of the formal source corpus.
