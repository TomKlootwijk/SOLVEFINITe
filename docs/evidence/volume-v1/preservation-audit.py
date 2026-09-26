"""Independent preservation audit for formal volume revision 15.

The 100-page revision 14 and its executed DP evidence are protected at 2943578.
This auditor imports only the hash-checked, frozen document auditor, never a
solvefinite module, test, reference producer or formal builder. --rebuild invokes
the builder in a separate process. No volume runtime or GPU claim is made.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import pdfplumber
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[3]
BASE = "2943578d6d8cb998281469fd4d93d677bf393259"
BASE_PDF_SHA256 = "63ceb47473b9e44c7e3b287ebaf25c413d4027099dc964e8a58e8f02f047247e"
PDF = "output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf"
BUILDER = "tools/build_formal_spec.py"
DIRECTORY = "docs/evidence/volume-v1"
DP_DIRECTORY = "docs/evidence/directional-v1"
OLD_PAGES, NEW_PAGES = 100, 117
VOLUME_PINS = {
    "reference-builder.py": "ad0917629ec4a29105db477609b2c707861cc3ab73b998546faf41a6ddb3874d",
    "formal-reference.json": "a6f06509ff83133d4ef1381f02ab991e5207948459c5e8479b01b0af3471a1a1",
    "geometry-audit.py": "a5cee1c990ab751b24b982fb3fbb255328661180facec7d8315fc3c407462ae8",
    "geometry-audit.json": "3e061ad2b04ac85db204115fff8a3f6642b4407f89f6562d2bf037459a8fb284",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def lf(data):
    return data.replace(b"\r\n", b"\n")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def historical(path):
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT)


def frozen_auditor():
    relative = f"{DP_DIRECTORY}/runtime-preservation-audit.py"
    path = ROOT / relative
    require(lf(path.read_bytes()) == lf(historical(relative)), "Frozen DP auditor changed")
    spec = importlib.util.spec_from_file_location("frozen_dp_capture_auditor_for_vp", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def page_calls(source):
    return sorted((node for node in ast.walk(ast.parse(source))
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "page"), key=lambda node: node.lineno)


def ast_bytes(node):
    return ast.dump(node, include_attributes=False).encode("utf-8")


def retained_evidence():
    paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", BASE, "docs/evidence"], cwd=ROOT
    ).decode("utf-8").splitlines()
    require(paths and not any(path.startswith(DIRECTORY + "/") for path in paths),
            "Volume evidence must be new after the declared baseline")
    result = {}
    text_suffixes = {".py", ".json", ".md", ".txt", ".csv", ".toml", ".wgsl"}
    for path in paths:
        before, after = historical(path), (ROOT / path).read_bytes()
        normalize = lf if Path(path).suffix in text_suffixes else bytes
        require(normalize(before) == normalize(after), "Retained evidence changed: " + path)
        result[path] = {"sha256": sha(normalize(after)),
                        "normalization": "LF" if normalize is lf else "raw bytes"}
    return result


def volume_evidence(required):
    names = ("reference-builder.py", "formal-reference.json", "geometry-audit.py", "geometry-audit.json")
    missing = [name for name in names if not (ROOT / DIRECTORY / name).is_file()]
    if missing:
        require(not required, "Missing completed volume mathematical evidence: " + ", ".join(missing))
        return {"status": "PENDING_REFERENCE", "missing": missing}
    hashes = {name: sha(lf((ROOT / DIRECTORY / name).read_bytes())) for name in names}
    require(hashes == VOLUME_PINS, "Volume mathematical evidence differs from the frozen reference/audit identities")
    reference = json.loads((ROOT / DIRECTORY / "formal-reference.json").read_bytes())
    audit = json.loads((ROOT / DIRECTORY / "geometry-audit.json").read_bytes())
    require(reference["format"] == "volume-independent-formal-reference-v1", "Wrong volume reference format")
    require(reference["status"] == "formal-only" and "No measured runtime behavior" in reference["scope"],
            "Volume reference must declare its formal-only scope")
    require(reference["generator_sha256_lf"] == hashes["reference-builder.py"],
            "Volume reference generator identity differs")
    for path, expected in reference["independent_source_sha256_lf"].items():
        require(sha(lf((ROOT / path).read_bytes())) == expected == sha(lf(historical(path))),
                "Independent reference helper differs from the baseline: " + path)
    require(audit["format"] == "solvefinite-volume-geometry-audit-v1", "Wrong volume geometry audit format")
    require(audit["script_sha256_lf"] == hashes["geometry-audit.py"], "Volume geometry auditor identity differs")
    require(audit["checks"] and all(value is True for value in audit["checks"].values()),
            "Volume mathematical audit contains failed or non-Boolean checks")
    require("no CPU/GPU runtime conformance asserted" in audit["status"],
            "Volume mathematical audit must declare its preimplementation scope")
    require(reference.get("actual_GPU_capture", False) is False
            and audit.get("actual_GPU_capture", False) is False, "Mathematical evidence cannot claim a GPU capture")
    return {"status": "PASS", "scope": "Independent mathematical expectations; no volume CPU/GPU execution.",
            "artifact_sha256_lf": hashes, "reference_format": reference["format"],
            "reference_status": reference["status"], "reference_scope": reference["scope"],
            "reference_helper_sha256_lf": reference["independent_source_sha256_lf"],
            "geometry_checks": audit["checks"], "topology_counts": audit["topology_counts"],
            "geometry_counts": audit["geometry_counts"], "arithmetic_counts": audit["arithmetic_counts"]}


def source_checks(auditor, required):
    old_pdf = historical(PDF)
    require(sha(old_pdf) == BASE_PDF_SHA256, "Historical revision 14 PDF identity differs")
    builder = (ROOT / BUILDER).read_bytes()
    old_calls, calls = page_calls(historical(BUILDER)), page_calls(builder)
    require(len(old_calls) == OLD_PAGES - 1, "Baseline page-call count differs")
    require(len(calls) == NEW_PAGES - 1 if required else OLD_PAGES - 1 <= len(calls) <= NEW_PAGES - 1,
            "Unexpected revision 15 page-call count")
    protected_calls = []
    for number in range(4, OLD_PAGES + 1):
        before, after = old_calls[number - 2], calls[number - 2]
        require(ast_bytes(before) == ast_bytes(after), f"Protected page {number} call AST changed")
        protected_calls.append({"page": number, "title": before.args[0].value,
                                "page_call_ast_sha256": sha(ast_bytes(before))})
    changed = [number + 2 for number, (before, after) in enumerate(zip(old_calls, calls))
               if ast_bytes(before) != ast_bytes(after)]
    require(changed == [2] if required else set(changed) <= {2},
            "Only the old edition page 2 may change its page-call AST")

    preserved = retained_evidence()
    verification = json.loads(historical(f"{DP_DIRECTORY}/verification.json"))
    inventory = verification["source_sha256_lf"]
    require(len(inventory) == 120, "Historical DP capture must identify exactly 120 sources")
    for path, expected in inventory.items():
        require(sha(lf(historical(path))) == expected, "DP historical capture source differs: " + path)
        require(sha(lf((ROOT / path).read_bytes())) == expected, "DP current capture source changed: " + path)
    capture = auditor.captured_evidence(True)
    require(capture["source_sha256_lf"] == inventory and capture["source_count"] == 120,
            "Freshly enumerated current capture boundary differs from the historical inventory")
    require(capture["tests"]["passed"] == 796 and capture["tests"]["skipped"] == 0,
            "Historical DP test counts changed")
    protected = dict(verification["original_source_sha256"])
    require(len(protected) == 3, "Expected exactly three original source PDFs")
    protected["output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf"] = verification["eli5_pdf_unchanged_sha256"]
    for path, expected in protected.items():
        require(sha(historical(path)) == expected == sha((ROOT / path).read_bytes()), "Protected PDF changed: " + path)
    return {"baseline_commit": BASE, "baseline_pdf_sha256": BASE_PDF_SHA256,
            "permitted_document_changes": "Cover, edition page 2, generated contents page 3, running revision/count furniture, and appended pages 101-117.",
            "unchanged_page_call_ast": protected_calls, "changed_old_page_calls": changed,
            "protected_evidence": preserved, "protected_pdf_sha256": protected,
            "historical_DP_capture": {"validation_commit": BASE,
                "scope": "Existing DP capture validated against historical git objects and the unchanged current 120-file inventory; no tests rerun.",
                **capture}, "builder_sha256_lf": sha(lf(builder)),
            "volume_mathematical_evidence": volume_evidence(required)}, old_pdf, calls


def body_text(page):
    lines = page.extract_text().splitlines()
    require(re.fullmatch(r"TK-LPLUT-2\.0 / REVISION \d+", lines[0]) is not None, "Unexpected running header")
    require(lines[1] == "TOM KLOOTWIJK  /  26 SEPTEMBER 2026", "Author/date header changed")
    require(lines[-2] == "FORMAL CONTRACT  /  EVIDENCE SCOPED TO DECLARED PROFILES", "Footer changed")
    require(re.fullmatch(r"\d+ / \d+", lines[-1]) is not None, "Unexpected page-count footer")
    return "\n".join(lines[2:-2])


def body_glyphs(page):
    # Header glyphs end before y44; footer glyphs start after y803. Include the
    # title, subtitle and every body glyph, preserving content and actual layout.
    return [{"text": c["text"], "font": c["fontname"],
             "fill_color": c.get("non_stroking_color"), "stroke_color": c.get("stroking_color"),
             **{key: round(c[key], 5) for key in ("x0", "x1", "top", "bottom", "size")}}
            for c in page.chars if c["top"] >= 60 and c["bottom"] <= 798]


def pdf_checks(auditor, path, previous, calls):
    raw = path.read_bytes()
    old, current = PdfReader(io.BytesIO(previous)), PdfReader(io.BytesIO(raw))
    require(len(old.pages) == OLD_PAGES and len(current.pages) == NEW_PAGES, "Unexpected PDF page counts")
    require(len(current.outline) == NEW_PAGES and all(not isinstance(x, list) for x in current.outline),
            "Expected one flat bookmark per page")
    for i, bookmark in enumerate(current.outline):
        title = "The Infallible Contract" if i == 0 else calls[i - 1].args[0].value
        require(current.get_destination_page_number(bookmark) == i and str(bookmark["/Title"]) == title,
                f"Bookmark target/title mismatch on page {i + 1}")
    require("revision 15" in body_text(current.pages[1]), "Edition page lacks revision 15")
    require("revision 15" in str(current.metadata.title), "PDF metadata title lacks revision 15")
    bodies = []
    for number in range(4, OLD_PAGES + 1):
        before, after = body_text(old.pages[number - 1]), body_text(current.pages[number - 1])
        require(before == after, f"Protected rendered page {number} body text changed")
        bodies.append({"page": number, "body_text_sha256": sha(after.encode("utf-8"))})
    for number in range(2, NEW_PAGES + 1):
        text = current.pages[number - 1].extract_text()
        require(text.splitlines()[0] == "TK-LPLUT-2.0 / REVISION 15", f"Wrong revision header on page {number}")
        require(text.splitlines()[-1] == f"{number} / {NEW_PAGES}", f"Wrong page-count footer on page {number}")
        require("\ufffd" not in text and "\x00" not in text, f"Replacement/null glyph on page {number}")
        if number > OLD_PAGES:
            require("FORMAL ONLY" in body_text(current.pages[number - 1]), f"New page {number} lacks formal-only status")
    helper = auditor.helper_module()
    internal, external = helper.link_checks(current)
    old_internal, old_external = helper.link_checks(old)
    navigation = list(dict.fromkeys((item["from"], item["to"]) for item in internal))
    require(len(navigation) == NEW_PAGES - 2
            and {target for _, target in navigation} == set(range(2, NEW_PAGES + 1)) - {3},
            "Expected 115 logical internal links reaching every content page exactly once")
    require(Counter(external) >= Counter(old_external), "A retained external reference disappeared")
    require([item for item in internal if 4 <= item["from"] <= OLD_PAGES]
            == [item for item in old_internal if item["from"] >= 4], "Protected page navigation changed")

    bounds, glyphs = [], []
    with pdfplumber.open(io.BytesIO(raw)) as document, pdfplumber.open(io.BytesIO(previous)) as baseline:
        for number, page in enumerate(document.pages, 1):
            require(abs(page.width - 595.2756) < .02 and abs(page.height - 841.8898) < .02, f"Non-A4 page {number}")
            chars = page.chars
            require(chars and all(-.1 <= c["x0"] <= c["x1"] <= page.width + .1
                    and -.1 <= c["top"] <= c["bottom"] <= page.height + .1 for c in chars),
                    f"A glyph exceeds page {number}")
            require(all("\ufffd" not in c["text"] and "\x00" not in c["text"] for c in chars),
                    f"Replacement/null glyph on page {number}")
            bounds.append({"page": number, "text_bounds_points": [round(value, 3) for value in
                           (min(c["x0"] for c in chars), min(c["top"] for c in chars),
                            max(c["x1"] for c in chars), max(c["bottom"] for c in chars))]})
            if 4 <= number <= OLD_PAGES:
                before, after = body_glyphs(baseline.pages[number - 1]), body_glyphs(page)
                require(before == after, f"Protected page {number} body glyph content or placement changed")
                glyphs.append({"page": number, "glyph_count": len(after), "body_glyph_sha256": sha(canonical(after))})
    return {"path": PDF, "sha256": sha(raw), "pages": NEW_PAGES, "bookmarks": NEW_PAGES,
            "internal_links": internal, "external_links": external,
            "internal_navigation_count": len(navigation), "internal_link_rectangle_count": len(internal),
            "unchanged_rendered_page_bodies": bodies, "unchanged_body_glyph_layouts": glyphs,
            "text_and_page_bounds": bounds, "replacement_glyphs": 0,
            "automated_layout_scope": "All page/glyph/link bounds and protected body glyph placement; visual review of rendered pages remains separate."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--final", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--pdf", type=Path, default=ROOT / PDF)
    args = parser.parse_args()
    require(not args.rebuild or args.final, "--rebuild requires --final")
    auditor = frozen_auditor()
    report, previous, calls = source_checks(auditor, args.final)
    report.update(format="volume-formal-preservation-audit-v1", status="PASS" if args.final else "PREPARED",
                  scope="Independent document/source preservation and retained DP evidence validation; no volume CPU/GPU runtime execution.",
                  auditor_sha256_lf=sha(lf(Path(__file__).read_bytes())))
    if args.final:
        report["pdf"] = pdf_checks(auditor, args.pdf, previous, calls)
        if args.rebuild:
            with tempfile.TemporaryDirectory(prefix="vp-preservation-", dir=ROOT / "tmp/pdfs") as temporary:
                path = Path(temporary) / "rebuilt.pdf"
                result = subprocess.run([sys.executable, str(ROOT / BUILDER), "--output", str(path)],
                                        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                require(result.returncode == 0, "Independent rebuild failed: " + result.stderr)
                require(sha(path.read_bytes()) == report["pdf"]["sha256"], "PDF rebuild is not byte-identical")
                report["rebuild"] = {"byte_identical": True, "sha256": report["pdf"]["sha256"],
                                     "command": "python tools/build_formal_spec.py --output <temporary.pdf>"}
    ending, _, _ = source_checks(auditor, args.final)
    require(ending == {key: report[key] for key in ending}, "Audit inputs changed during verification")
    if args.final:
        require(sha(args.pdf.read_bytes()) == report["pdf"]["sha256"], "Audited PDF changed during verification")
    output = ROOT / DIRECTORY / "preservation.json"
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"], "output": output.relative_to(ROOT).as_posix(),
                      "protected_page_bodies": 97, "historical_and_current_DP_sources": 120,
                      "protected_prior_evidence": len(report["protected_evidence"]),
                      "volume_evidence_status": report["volume_mathematical_evidence"]["status"],
                      "pdf_sha256": report.get("pdf", {}).get("sha256")}, sort_keys=True))


if __name__ == "__main__":
    main()
