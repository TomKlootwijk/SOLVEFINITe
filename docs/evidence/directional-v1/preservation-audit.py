"""Independent preservation audit for formal directional revision 13.

No solvefinite module, reference producer, or formal builder is imported. --prepare
checks source preservation before rendering; --final additionally checks the PDF.
--rebuild independently invokes the builder and compares exact PDF bytes. This is
document preservation evidence, never directional runtime or GPU evidence.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from pypdf import PdfReader
import pdfplumber


ROOT = Path(__file__).resolve().parents[3]
BASE = "1ea93207ae8545a5c5d344677cb73a5c459dc91c"
BUILDER = "tools/build_formal_spec.py"
PDF = "output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf"
EVIDENCE = "docs/evidence/directional-v1"
BASE_PDF_SHA256 = "64ce7f7189cd94b28959a7245b9c7a4989d03cb5ad360a8b8e041e0195b64840"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def lf(data):
    return data.replace(b"\r\n", b"\n")


def at_base(path):
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT)


def page_calls(source):
    calls = [node for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
             and node.func.id == "page"]
    return sorted(calls, key=lambda node: node.lineno)


def ast_bytes(node):
    return ast.dump(node, include_attributes=False).encode("utf-8")


def source_checks():
    old_pdf = at_base(PDF)
    require(digest(old_pdf) == BASE_PDF_SHA256, "Historical revision 12 PDF identity changed")
    old_builder, current_builder = at_base(BUILDER), (ROOT / BUILDER).read_bytes()
    old_calls, new_calls = page_calls(old_builder), page_calls(current_builder)
    require(len(old_calls) == 82 and len(new_calls) == 96, "Expected 83 and 97 total pages")
    pages = []
    for number in range(4, 84):
        before, after = old_calls[number - 2], new_calls[number - 2]
        require(ast_bytes(before) == ast_bytes(after), f"Protected page {number} call AST changed")
        pages.append({"page": number, "title": before.args[0].value,
                      "page_call_ast_sha256": digest(ast_bytes(before))})
    changed_calls = [i + 2 for i, (a, b) in enumerate(zip(old_calls, new_calls))
                     if ast_bytes(a) != ast_bytes(b)]
    require(changed_calls == [2], "Only the edition page may change among old page calls")

    verification_path = "docs/evidence/welip-v1/verification.json"
    raw_verification = (ROOT / verification_path).read_bytes()
    require(lf(raw_verification) == lf(at_base(verification_path)), "Historical W capture changed")
    verification = json.loads(raw_verification)
    inventory = verification["source_sha256_lf"]
    require(len(inventory) == 106, "Expected complete 106-file historical W inventory")
    for path, expected in inventory.items():
        require(digest(lf(at_base(path))) == expected, f"Historical capture source mismatch: {path}")
        require(digest(lf((ROOT / path).read_bytes())) == expected, f"Current W source changed: {path}")

    protected = dict(verification["original_source_sha256"])
    require(len(protected) == 3, "Exactly three original source PDFs must be protected")
    protected["output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf"] = verification["eli5_pdf_unchanged_sha256"]
    for path, expected in protected.items():
        require(digest(at_base(path)) == expected, f"Historical protected document mismatch: {path}")
        require(digest((ROOT / path).read_bytes()) == expected, f"Protected PDF changed: {path}")

    artifact_hashes = {BUILDER: digest(lf(current_builder))}
    for name in ("reference-builder.py", "formal-reference.json", "geometry-audit.py", "geometry-audit.json"):
        path = f"{EVIDENCE}/{name}"
        artifact_hashes[path] = digest(lf((ROOT / path).read_bytes()))
    reference = json.loads((ROOT / EVIDENCE / "formal-reference.json").read_bytes())
    require(reference["format"] == "directional-independent-formal-reference-v1", "Wrong directional reference type")
    require(reference["generator_sha256_lf"] == artifact_hashes[f"{EVIDENCE}/reference-builder.py"],
            "Directional reference does not identify its generator")
    for path, expected in reference["independent_source_sha256_lf"].items():
        require(digest(lf((ROOT / path).read_bytes())) == expected, f"Reference helper changed: {path}")
    return {
        "baseline_commit": BASE,
        "baseline_pdf_sha256": BASE_PDF_SHA256,
        "unchanged_page_call_ast": pages,
        "changed_old_page_calls": changed_calls,
        "permitted_document_changes": "Cover, edition page 2, generated contents page 3, running revision/count furniture, and appended pages 84-97.",
        "historical_W_source_count": len(inventory),
        "historical_W_source_sha256_lf": inventory,
        "protected_pdf_sha256": protected,
        "artifact_sha256_lf": artifact_hashes,
    }, old_pdf, new_calls


def body_text(page):
    lines = page.extract_text().splitlines()
    require(re.fullmatch(r"TK-LPLUT-2\.0 / REVISION \d+", lines[0]) is not None,
            "Unexpected running header")
    require(lines[1] == "TOM KLOOTWIJK  /  26 SEPTEMBER 2026", "Author/date header changed")
    require(lines[-2] == "FORMAL CONTRACT  /  EVIDENCE SCOPED TO DECLARED PROFILES", "Footer changed")
    require(re.fullmatch(r"\d+ / \d+", lines[-1]) is not None, "Unexpected page-count footer")
    return "\n".join(lines[2:-2])


def link_checks(reader):
    page_numbers = {page.indirect_reference.idnum: index + 1 for index, page in enumerate(reader.pages)}
    internal, external = [], []
    for number, page in enumerate(reader.pages, 1):
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        for ref in page.get("/Annots", []):
            annotation = ref.get_object()
            require(annotation.get("/Subtype") == "/Link", "Unexpected PDF annotation kind")
            x0, y0, x1, y1 = map(float, annotation["/Rect"])
            require(0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height,
                    f"Out-of-page link rectangle on page {number}")
            if "/Dest" in annotation:
                dest = annotation["/Dest"]
                require(dest[1] == "/Fit" and len(dest) == 2, "Unexpected internal destination")
                target = page_numbers.get(dest[0].idnum)
                require(target is not None, "Dangling PDF page link")
                internal.append({"from": number, "to": target})
            else:
                action = annotation["/A"]
                require(action.get("/S") == "/URI", "Unexpected external link action")
                external.append(str(action["/URI"]))
    return internal, external


def pdf_checks(path, previous, new_calls):
    raw = path.read_bytes()
    old, current = PdfReader(io.BytesIO(previous)), PdfReader(io.BytesIO(raw))
    require(len(old.pages) == 83 and len(current.pages) == 97, "Incorrect edition page counts")
    require(len(current.outline) == 97 and all(not isinstance(x, list) for x in current.outline),
            "Expected 97 flat page bookmarks")
    for i, outline in enumerate(current.outline):
        require(current.get_destination_page_number(outline) == i, "Misordered page bookmark")
        title = "The Infallible Contract" if i == 0 else new_calls[i - 1].args[0].value
        require(str(outline["/Title"]) == title, f"Bookmark title mismatch on page {i + 1}")

    bodies = []
    for number in range(4, 84):
        before, after = body_text(old.pages[number - 1]), body_text(current.pages[number - 1])
        require(before == after, f"Protected rendered body changed on page {number}")
        bodies.append({"page": number, "body_text_sha256": digest(after.encode("utf-8"))})
    for number in range(84, 98):
        require("FORMAL ONLY" in body_text(current.pages[number - 1]), f"Unscoped new page {number}")
    require("revision 13" in body_text(current.pages[1]), "Edition page does not identify revision 13")
    require("698" in body_text(current.pages[81]), "Historical measured page lost its scoped count")
    require("implementation remains pending" in body_text(current.pages[1]), "New runtime status missing")
    internal, external = link_checks(current)
    _, old_external = link_checks(old)
    require(len(internal) == 95, "Expected 95 internal navigation links")
    require(sorted(link["to"] for link in internal) == [n for n in range(2, 98) if n != 3],
            "Internal navigation must reach every content page exactly once")
    require(external == old_external, "Protected external references changed")

    geometry = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            require(abs(page.width - 595.2756) < .02 and abs(page.height - 841.8898) < .02,
                    f"Non-A4 page {number}")
            chars = page.chars
            require(chars, f"Empty page {number}")
            require(all(-.1 <= c["x0"] <= c["x1"] <= page.width + .1
                        and -.1 <= c["top"] <= c["bottom"] <= page.height + .1 for c in chars),
                    f"A text glyph lies outside page {number}")
            bounds = [min(c["x0"] for c in chars), min(c["top"] for c in chars),
                      max(c["x1"] for c in chars), max(c["bottom"] for c in chars)]
            geometry.append({"page": number, "text_bounds_points": [round(x, 3) for x in bounds]})
    return {"path": PDF, "sha256": digest(raw), "pages": 97, "bookmarks": 97,
            "internal_links": internal, "external_links": external,
            "unchanged_rendered_page_bodies": bodies, "text_and_page_bounds": geometry,
            "automated_layout_scope": "Page and glyph bounds plus link rectangles; visual review remains separate."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--final", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--pdf", type=Path, default=ROOT / PDF)
    args = parser.parse_args()
    require(not args.rebuild or args.final, "--rebuild requires --final")
    report, old_pdf, calls = source_checks()
    report.update(format="directional-formal-preservation-audit-v1",
                  scope="Independent document/source preservation; no directional runtime or GPU execution.",
                  status="PREPARED" if args.prepare else "PASS",
                  auditor_sha256_lf=digest(lf(Path(__file__).read_bytes())))
    if args.final:
        report["pdf"] = pdf_checks(args.pdf, old_pdf, calls)
        if args.rebuild:
            with tempfile.TemporaryDirectory(prefix="dp-preservation-", dir=ROOT / "tmp/pdfs") as tmp:
                output = Path(tmp) / "rebuilt.pdf"
                command = [sys.executable, str(ROOT / BUILDER), "--output", str(output)]
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                require(completed.returncode == 0, "Independent PDF rebuild failed: " + completed.stderr)
                rebuilt = digest(output.read_bytes())
                require(rebuilt == report["pdf"]["sha256"], "PDF rebuild is not byte-identical")
                report["rebuild"] = {"byte_identical": True, "sha256": rebuilt,
                                     "command": "python tools/build_formal_spec.py --output <temporary.pdf>"}
    ending, _, _ = source_checks()
    require(ending == {key: report[key] for key in ending}, "Audit inputs changed during verification")
    destination = ROOT / EVIDENCE / "preservation.json"
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": destination.relative_to(ROOT).as_posix(),
                      "protected_W_sources": 106, "protected_page_bodies": 80,
                      "pdf_sha256": report.get("pdf", {}).get("sha256")}, sort_keys=True))


if __name__ == "__main__":
    main()
