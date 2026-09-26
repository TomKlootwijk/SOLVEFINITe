"""Independent revision-14 preservation and captured-evidence audit.

The formal revision-13 audit remains immutable. Historical W sources are checked
at their named commit; new DP capture sources are checked against this checkout.
This script imports neither solvefinite, tests, conformance producers nor the
formal builder. --rebuild invokes the builder as a separate process.
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
BASE = "1979e66634c10fc8ede019fd677434bb1dba4a7d"
W_BASE = "1ea93207ae8545a5c5d344677cb73a5c459dc91c"
PDF = "output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf"
BASE_PDF_SHA256 = "b11d6ab9037578dc2d46fe806dc45502ab0002d23ca8d79f044ef94edb29bd77"
BUILDER = "tools/build_formal_spec.py"
DIRECTORY = "docs/evidence/directional-v1"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def lf(data):
    return data.replace(b"\r\n", b"\n")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def historical(path, commit=BASE):
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT)


def helper_module():
    path = ROOT / DIRECTORY / "preservation-audit.py"
    require(lf(path.read_bytes()) == lf(historical(f"{DIRECTORY}/preservation-audit.py")),
            "Immutable formal preservation helper changed")
    spec = importlib.util.spec_from_file_location("frozen_directional_formal_auditor", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_source_inventory():
    # Independently enumerate the exact public capture boundary, without
    # importing the mutable capture program or discovering executable tests.
    paths = {path for directory in ("solvefinite", "tests", "examples")
             for path in (ROOT / directory).rglob("*")
             if path.is_file() and path.suffix in (".py", ".wgsl", ".json")}
    paths.add(ROOT / "tools/capture_taper_evidence.py")
    for directory in ("directional-v1", "welip-v1", "organogram-v1", "growth-v1"):
        for name in ("reference-builder.py", "formal-reference.json"):
            paths.add(ROOT / "docs/evidence" / directory / name)
    for name in ("geometry-audit.py", "geometry-audit.json"):
        paths.add(ROOT / DIRECTORY / name)
    return {path.relative_to(ROOT).as_posix(): sha(lf(path.read_bytes())) for path in sorted(paths)}


def captured_evidence(required):
    path = ROOT / DIRECTORY / "verification.json"
    if not path.exists():
        require(not required, "The final audit requires the complete DP verification capture")
        return {"status": "PENDING_CAPTURE"}
    raw = path.read_bytes()
    verification = json.loads(raw)
    require(verification["format"] == "directional-verification-v1", "Wrong DP capture type")
    require(verification["formal_binding_commit"] == BASE and verification["base_commit"] == W_BASE,
            "DP capture chronology differs from the named baselines")
    require(verification["preimplementation_formal_pdf_sha256"] == BASE_PDF_SHA256,
            "DP capture names another formal PDF")
    require(verification["actual_GPU_capture"] is True and verification["partial"] is False,
            "Measured revision requires a complete actual-GPU capture")
    require(verification["source_manifest_unchanged_during_capture"] is True,
            "Capture did not preserve its source snapshot")
    inventory = current_source_inventory()
    require(verification["source_sha256_lf"] == inventory, "Current source inventory differs from DP capture")
    report_hashes = verification["report_sha256_lf"]
    require(set(report_hashes) == {"full-tests.txt", "conformance.json", "welip-conformance.json"},
            "Incomplete or unexpected DP report inventory")
    for name, expected in report_hashes.items():
        require(sha(lf((path.parent / name).read_bytes())) == expected, "Capture report changed: " + name)

    log = (path.parent / "full-tests.txt").read_text(encoding="utf-8")
    tests = verification["tests"]
    require(tests["complete_suite"] is True and type(tests["passed"]) is int
            and tests["passed"] > 0 and type(tests["skipped"]) is int and tests["skipped"] == 0,
            "Incomplete or skipped unit suite")
    summary = re.search(r"Ran (\d+) tests in ([0-9.]+)s", log)
    require(summary is not None and int(summary[1]) == tests["passed"] and log.rstrip().endswith("OK")
            and "... skipped" not in log and "skipped=" not in log, "Test log and reported pass count disagree")
    identities = re.findall(r"^test\S* \(([^)]+)\) \.\.\. ok$", log, re.MULTILINE)
    require(len(identities) == tests["passed"], "Verbose log lacks one successful line per test")
    modules = Counter(identity.rsplit(".", 2)[0] for identity in identities)
    require(dict(modules) == tests["module_counts"], "Executed module counts differ from capture inventory")
    capture_ast = ast.parse((ROOT / "tools/capture_taper_evidence.py").read_bytes())
    assignments = [node for node in capture_ast.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "HOST_ONLY_GPU_CLASS_METHODS"
                           for target in node.targets)]
    require(len(assignments) == 1, "Capture lacks one explicit host-only GPU-class exclusion set")
    excluded = ast.literal_eval(assignments[0].value)
    require(type(excluded) is set and len(excluded) == 5 and all(type(x) is str for x in excluded),
            "Expected five named host-only methods, not an implicit class-wide exclusion")
    require(tests["host_only_methods_excluded_from_device_count"] == sorted(excluded)
            and excluded <= set(identities), "Reported GPU accounting exclusions differ from the executed test log")
    classes = Counter(identity.rsplit(".", 2)[1] for identity in identities if identity not in excluded)
    require(all(type(count) is int and count > 0 and classes.get(name) == count
                for name, count in tests["actual_device_methods"].items()), "GPU method counts disagree with executed log")

    conformance = json.loads((path.parent / "conformance.json").read_bytes())
    welip = json.loads((path.parent / "welip-conformance.json").read_bytes())
    for name, report, count_name in (("DP", conformance, "conformance_checks_passed"),
                                     ("Wv2", welip, "welip_conformance_checks_passed")):
        require(report["actual_GPU_capture"] is True and report.get("partial", False) is False,
                name + " conformance is partial")
        require(report["checks"] and all(value is True for value in report["checks"].values()),
                name + " conformance contains a failed or non-Boolean check")
        require(len(report["checks"]) == verification[count_name], name + " check count differs")
    reference_hash = sha(lf((path.parent / "formal-reference.json").read_bytes()))
    require(conformance["formal_commit"] == BASE and welip["formal_binding_commit"] == BASE,
            "Conformance reports reference another formal commit")
    require(conformance["formal_reference_sha256_lf"] == reference_hash
            and welip["reference_sha256_lf"] == reference_hash, "Conformance reference identity differs")
    for name, cpu in conformance["CPU"]["cases"].items():
        gpu = conformance["GPU"][name]
        require(cpu["archive"] == gpu["archive"], "DP CPU/GPU canonical history differs: " + name)
        require(sha(canonical(cpu["archive"])) == cpu["archive_sha256"] == gpu["archive_sha256"],
                "DP archive digest differs: " + name)
    require(verification["mission_results"] == {name: value["archive"]["expected"]
            for name, value in conformance["CPU"]["cases"].items()}, "Captured mission summaries differ")
    for name, cpu in welip["CPU"]["lifecycles"].items():
        gpu = welip["GPU"]["lifecycles"][name]
        require(cpu["archive"] == gpu["archive"], "Wv2 CPU/GPU canonical history differs: " + name)
        require(sha(canonical(cpu["archive"])) == cpu["welip_archive_sha256"] == gpu["welip_archive_sha256"],
                "Wv2 archive digest differs: " + name)
    agent_hash = conformance["CPU"]["cases"]["default"]["archive_sha256"]
    require(agent_hash == verification["canonical_agent_archive_sha256"] == welip["canonical_agent_archive_sha256"],
            "Agent archive identity disagrees across captures")
    require(verification["welip_archive_sha256"] == welip["welip_archive_sha256"], "Wv2 identity differs")
    require([entry["backend"] for entry in welip["fresh_process_recovery"]["captures"]] == ["gpu", "cpu", "gpu"],
            "Wv2 fresh-process recovery lacks the hardware round trip")
    require(verification["environment"]["adapter"] == welip["adapter"]
            and welip["adapter"]["adapter_type"] in ("DiscreteGPU", "IntegratedGPU"), "Hardware identity differs")
    return {"status": "PASS", "verification_sha256_lf": sha(lf(raw)), "source_count": len(inventory),
            "source_sha256_lf": inventory, "report_sha256_lf": report_hashes, "tests": tests,
            "conformance_checks_passed": len(conformance["checks"]),
            "welip_conformance_checks_passed": len(welip["checks"]),
            "adapter": welip["adapter"], "canonical_agent_archive_sha256": agent_hash,
            "welip_archive_sha256": welip["welip_archive_sha256"]}


def source_checks(helper, required):
    previous = historical(PDF)
    require(sha(previous) == BASE_PDF_SHA256, "Formal-first revision 13 PDF identity changed")
    old_calls = helper.page_calls(historical(BUILDER))
    builder = (ROOT / BUILDER).read_bytes()
    calls = helper.page_calls(builder)
    require(len(old_calls) == 96 and len(calls) == 99, "Expected 97 formal and 100 measured pages")
    page_hashes = []
    for number in range(4, 98):
        before, after = old_calls[number - 2], calls[number - 2]
        require(helper.ast_bytes(before) == helper.ast_bytes(after), f"Protected page {number} call AST changed")
        page_hashes.append({"page": number, "title": before.args[0].value,
                            "page_call_ast_sha256": sha(helper.ast_bytes(before))})
    changed = [i + 2 for i, (a, b) in enumerate(zip(old_calls, calls))
               if helper.ast_bytes(a) != helper.ast_bytes(b)]
    require(changed == [2], "Only old edition page 2 may change its page call")

    protected_formal = {}
    for name in ("preservation-audit.py", "preservation.json", "pdf-quality.json",
                 "reference-builder.py", "formal-reference.json", "geometry-audit.py", "geometry-audit.json"):
        path = f"{DIRECTORY}/{name}"
        actual = lf((ROOT / path).read_bytes())
        require(actual == lf(historical(path)), "Original formal evidence changed: " + path)
        protected_formal[path] = sha(actual)
    w_path = "docs/evidence/welip-v1/verification.json"
    w_bytes = historical(w_path, W_BASE)
    require(lf((ROOT / w_path).read_bytes()) == lf(w_bytes), "Historical W verification changed")
    w = json.loads(w_bytes)
    require(len(w["source_sha256_lf"]) == 106, "Historical W source inventory is incomplete")
    for path, expected in w["source_sha256_lf"].items():
        require(sha(lf(historical(path, W_BASE))) == expected, "Historical W source mismatch: " + path)
    protected_pdfs = dict(w["original_source_sha256"])
    require(len(protected_pdfs) == 3, "Expected three original source PDFs")
    protected_pdfs["output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf"] = w["eli5_pdf_unchanged_sha256"]
    for path, expected in protected_pdfs.items():
        require(sha(historical(path)) == expected == sha((ROOT / path).read_bytes()), "Protected PDF changed: " + path)
    capture = captured_evidence(required)
    return {"baseline_commit": BASE, "baseline_pdf_sha256": BASE_PDF_SHA256,
            "historical_W_commit": W_BASE, "historical_W_source_count": 106,
            "historical_W_source_scope": "Validated against git objects at 1ea9320, not the modified runtime checkout.",
            "historical_W_source_sha256_lf": w["source_sha256_lf"],
            "unchanged_page_call_ast": page_hashes, "changed_old_page_calls": changed,
            "protected_formal_evidence_sha256_lf": protected_formal, "protected_pdf_sha256": protected_pdfs,
            "builder_sha256_lf": sha(lf(builder)), "captured_evidence": capture}, previous, calls


def pdf_checks(helper, path, previous, calls, capture):
    raw = path.read_bytes()
    old, current = PdfReader(io.BytesIO(previous)), PdfReader(io.BytesIO(raw))
    require(len(old.pages) == 97 and len(current.pages) == 100, "Unexpected edition page count")
    require(len(current.outline) == 100 and all(not isinstance(item, list) for item in current.outline),
            "Expected 100 flat bookmarks")
    for index, entry in enumerate(current.outline):
        title = "The Infallible Contract" if index == 0 else calls[index - 1].args[0].value
        require(current.get_destination_page_number(entry) == index and str(entry["/Title"]) == title,
                "Bookmark target or title differs")
    bodies = []
    for number in range(4, 98):
        before, after = helper.body_text(old.pages[number - 1]), helper.body_text(current.pages[number - 1])
        require(before == after, f"Protected rendered page {number} changed")
        bodies.append({"page": number, "body_text_sha256": sha(after.encode("utf-8"))})
    edition = helper.body_text(current.pages[1])
    require("revision 14" in edition, "Edition page lacks revision 14")
    for number, marker in ((98, "IMPLEMENTATION CAPTURE"), (99, "MEASURED CONTINUATION"),
                           (100, "REPRODUCIBLE CAPTURE")):
        body = helper.body_text(current.pages[number - 1])
        require(marker in body, f"Measured page {number} lacks its declared evidence status")
    measured = " ".join(helper.body_text(current.pages[97]).split())
    for phrase in (f"passes {capture['tests']['passed']} tests with zero skips",
                   f"{sum(capture['tests']['actual_device_methods'].values())} actual-device GPU methods",
                   f"{capture['conformance_checks_passed']} geometry/mission conformance checks",
                   f"{capture['welip_conformance_checks_passed']} Wv2 checks"):
        require(phrase in measured, "Measured PDF count differs from captured evidence: " + phrase)
    internal, external = helper.link_checks(current)
    _, original_external = helper.link_checks(old)
    # ReportLab emits one annotation rectangle for each line fragment of an
    # inline link. Keep every rectangle in the report, but count navigation by
    # distinct source/target pair rather than treating a wrap as a new link.
    navigation = list(dict.fromkeys((item["from"], item["to"]) for item in internal))
    require(len(navigation) == 98 and sorted(target for _, target in navigation) == [i for i in range(2, 101) if i != 3],
            "Expected 98 complete distinct internal navigation links")
    repeated = Counter((item["from"], item["to"]) for item in internal)
    require(all(source == 2 and target in (98, 99, 100) for (source, target), count in repeated.items() if count > 1),
            "Only new inline edition links may have multiple line rectangles")
    require(sorted(target for source, target in navigation if source == 2) == [98, 99, 100],
            "Edition page must link all three appended measured pages")
    require(external == original_external and len(external) == 7, "Protected external references changed")
    bounds = []
    with pdfplumber.open(io.BytesIO(raw)) as document:
        for number, page in enumerate(document.pages, 1):
            require(abs(page.width - 595.2756) < .02 and abs(page.height - 841.8898) < .02, f"Non-A4 page {number}")
            chars = page.chars
            require(chars and all(-.1 <= c["x0"] <= c["x1"] <= page.width + .1
                    and -.1 <= c["top"] <= c["bottom"] <= page.height + .1 for c in chars),
                    f"A glyph exceeds page {number}")
            bounds.append({"page": number, "text_bounds_points": [round(value, 3) for value in
                           (min(c["x0"] for c in chars), min(c["top"] for c in chars),
                            max(c["x1"] for c in chars), max(c["bottom"] for c in chars))]})
    return {"path": PDF, "sha256": sha(raw), "pages": 100, "bookmarks": 100,
            "internal_links": internal, "external_links": external,
            "internal_navigation_count": len(navigation), "internal_link_rectangle_count": len(internal),
            "unchanged_rendered_page_bodies": bodies, "text_and_page_bounds": bounds,
            "automated_layout_scope": "Page/glyph/link bounds; independent visual review is reported separately."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--final", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--pdf", type=Path, default=ROOT / PDF)
    args = parser.parse_args()
    require(not args.rebuild or args.final, "--rebuild requires --final")
    helper = helper_module()
    report, previous, calls = source_checks(helper, args.final)
    report.update(format="directional-runtime-preservation-audit-v1",
                  status="PASS" if args.final else "PREPARED",
                  scope="Document preservation and identity checks of retained executed evidence; no test or GPU execution in this audit.",
                  auditor_sha256_lf=sha(lf(Path(__file__).read_bytes())))
    if args.final:
        report["pdf"] = pdf_checks(helper, args.pdf, previous, calls, report["captured_evidence"])
        if args.rebuild:
            with tempfile.TemporaryDirectory(prefix="dp-runtime-preservation-", dir=ROOT / "tmp/pdfs") as temporary:
                path = Path(temporary) / "rebuilt.pdf"
                result = subprocess.run([sys.executable, str(ROOT / BUILDER), "--output", str(path)],
                                        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
                require(result.returncode == 0, "Independent rebuild failed: " + result.stderr)
                require(sha(path.read_bytes()) == report["pdf"]["sha256"], "PDF rebuild is not byte-identical")
                report["rebuild"] = {"byte_identical": True, "sha256": report["pdf"]["sha256"],
                                     "command": "python tools/build_formal_spec.py --output <temporary.pdf>"}
    ending, _, _ = source_checks(helper, args.final)
    require(ending == {key: report[key] for key in ending}, "Audit inputs changed during verification")
    output = ROOT / DIRECTORY / "runtime-preservation.json"
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"], "output": output.relative_to(ROOT).as_posix(),
                      "protected_page_bodies": 94, "historical_W_sources": 106,
                      "capture_status": report["captured_evidence"]["status"],
                      "pdf_sha256": report.get("pdf", {}).get("sha256")}))


if __name__ == "__main__":
    main()
