"""Capture source-bound W1--W8 tests, hardware conformance and private recovery.

The default run requires the complete suite with zero skips and an actual GPU.
--cpu-only writes explicitly partial reports under separate filenames.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from time import perf_counter
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "docs/evidence/welip-v1"
FORMAL_COMMIT = "74e00f4af54a341815c64e47f7f58334adda5709"
BASE_COMMIT = "f125a76b75052c3611c39557779c08e4553e620a"
ELI5_SHA = "06556d7bbae0de54e99f3abb9329869da1fbf085c6c1aab66d563528989c3ea0"
CPU_MODULES = ("tests.test_welip", "tests.test_welip_cache", "tests.test_welip_cli",
               "tests.test_welip_session")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def run(args, timeout=1200):
    result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", timeout=timeout,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if result.returncode:
        raise RuntimeError(f"Command failed: {args}\n{result.stdout}\n{result.stderr}")
    return result


def leaves(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from leaves(item)
        else:
            yield item


def source_manifest():
    paths = {path for directory in ("solvefinite", "tests", "examples")
             for path in (ROOT / directory).rglob("*")
             if path.is_file() and path.suffix in (".py", ".wgsl", ".json")}
    paths.add(Path(__file__).resolve())
    for directory in ("welip-v1", "organogram-v1", "growth-v1"):
        for name in ("reference-builder.py", "formal-reference.json"):
            paths.add(ROOT / "docs/evidence" / directory / name)
    return {path.relative_to(ROOT).as_posix(): digest(path.read_bytes().replace(b"\r\n", b"\n"))
            for path in sorted(paths)}


def test_inventory(cpu_only):
    suite = (unittest.defaultTestLoader.loadTestsFromNames(CPU_MODULES) if cpu_only
             else unittest.defaultTestLoader.discover(str(ROOT / "tests")))
    return list(leaves(suite))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEST)
    parser.add_argument("--cpu-only", action="store_true")
    args = parser.parse_args()
    dest = args.output_dir.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    sources_before = source_manifest()
    tests = test_inventory(args.cpu_only)
    test_args = (["-m", "unittest", *CPU_MODULES, "-v"] if args.cpu_only
                 else ["-m", "unittest", "discover", "-s", "tests", "-v"])
    test_name = "partial-tests.txt" if args.cpu_only else "full-tests.txt"
    conformance_name = "partial-conformance.json" if args.cpu_only else "conformance.json"
    verification_name = "partial-verification.json" if args.cpu_only else "verification.json"
    print("Running explicitly partial CPU W tests." if args.cpu_only
          else "Running the complete test suite, including actual hardware GPU tests.", flush=True)
    result = run(test_args)
    log = result.stdout + result.stderr
    (dest / test_name).write_text(log, encoding="utf-8", newline="\n")
    match = re.search(r"Ran (\d+) tests in ([0-9.]+)s", log)
    if match is None or not log.rstrip().endswith("OK") or "skipped=" in log or "... skipped" in log:
        raise ValueError("The selected suite must pass with zero skips")
    if len(tests) != int(match[1]):
        raise ValueError("Discovered test count differs from the executed suite")
    explicit = {"F8GpuTests", "HadamardGpuTests", "RealHadamardAgentTests",
                "RealGrowthAgentTests", "RealGrowthContinuationTests", "GrowthGpuTests",
                "OrganogramGpuTests", "RealOrganogramAgentTests", "RealOrganogramContinuationTests",
                "WelipGpuTests"}
    actual_device = Counter(test.__class__.__name__ for test in tests
                            if test.__class__.__name__ in explicit
                            or getattr(test, "backend", None) == "gpu"
                            or (test.__class__.__name__.startswith("Real") and "Gpu" in test.__class__.__name__))
    test_report = {"passed": int(match[1]), "skipped": 0, "elapsed_seconds": float(match[2]),
                   "complete_suite": not args.cpu_only,
                   "module_counts": dict(Counter(test.__class__.__module__ for test in tests)),
                   "actual_device_methods": dict(actual_device)}
    print(json.dumps(test_report), flush=True)
    print("Running W frozen-reference conformance and fresh-process recovery.", flush=True)
    conform_started = perf_counter()
    conformance_args = ["-m", "examples.welip_conformance", "--output", str(dest / conformance_name)]
    if args.cpu_only:
        conformance_args.append("--cpu-only")
    run(conformance_args)
    conformance_seconds = perf_counter() - conform_started
    conformance = json.loads((dest / conformance_name).read_text(encoding="utf-8"))
    if (not conformance["checks"] or any(value is not True for value in conformance["checks"].values())
            or conformance["partial"] is not args.cpu_only
            or conformance["actual_GPU_capture"] is not (not args.cpu_only)):
        raise ValueError("Capture scope or a conformance obligation failed")
    sources_after = source_manifest()
    if sources_before != sources_after:
        changed = sorted(name for name in sources_before.keys() | sources_after.keys()
                         if sources_before.get(name) != sources_after.get(name))
        raise ValueError("Sources changed during capture: " + ", ".join(changed))
    pdf = subprocess.check_output(["git", "show",
        f"{FORMAL_COMMIT}:output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf"], cwd=ROOT)
    eli5_hash = digest((ROOT / "output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf").read_bytes())
    if eli5_hash != ELI5_SHA:
        raise ValueError("The separately completed ELI5 PDF has changed")
    report_hashes = {name: digest((dest / name).read_bytes().replace(b"\r\n", b"\n"))
                     for name in (test_name, conformance_name)}
    environment = {"python": sys.version, "platform": platform.platform()}
    if not args.cpu_only:
        import wgpu
        environment.update(wgpu=wgpu.__version__, adapter=conformance["adapter"])
    final = conformance["CPU"]["lifecycles"]["main_lifecycle"]["archive"]
    report = {
        "format": "welip-verification-v1", "captured_utc": datetime.now(timezone.utc).isoformat(),
        "formal_binding_commit": FORMAL_COMMIT, "base_commit": BASE_COMMIT,
        "preimplementation_formal_pdf_sha256": digest(pdf),
        "actual_GPU_capture": conformance["actual_GPU_capture"], "partial": args.cpu_only,
        "tests": test_report, "conformance_checks_passed": len(conformance["checks"]),
        "conformance_elapsed_seconds": round(conformance_seconds, 3),
        "capture_elapsed_seconds": round(perf_counter() - started, 3),
        "canonical_agent_archive_sha256": conformance["canonical_agent_archive_sha256"],
        "welip_archive_sha256": conformance["welip_archive_sha256"],
        "final_state": final["agent"]["expected"], "final_W_state": final["expected"],
        "lifecycle_counts": {"variants": 3, "operations_each": 17, "records_each": 18, "carrier_words_each": 37},
        "fresh_process_backends": [row["backend"] for row in conformance["fresh_process_recovery"]["captures"]],
        "session_fault_cases": sorted(conformance.get("session_faults", {})),
        "environment": environment, "source_sha256_lf": sources_after,
        "source_manifest_unchanged_during_capture": True, "report_sha256_lf": report_hashes,
        "eli5_pdf_unchanged_sha256": eli5_hash,
        "original_source_sha256": {name: digest((ROOT / name).read_bytes()) for name in
            ("Tom_Klootwijk_Log_Encoded_Polar_LUT_Paradigm_v1.0.pdf",
             "sources/solus-ion-ad-infinitum.pdf", "sources/solipsism.pdf")},
        "commands": [[sys.executable, *test_args], [sys.executable, *conformance_args]],
        "remaining_obligations": ["Arbitrary cone/pyramid and graph productions", "Global spectral choices",
                                  "Physical adapters", "Comparative hardware and texture-cache measurements"],
        "scope": "Explicitly partial CPU development evidence." if args.cpu_only else
                 "Finite W1-W8 correctness, actual-device carrier emission and durable private reconstruction. "
                 "No universality, cache saturation, throughput or physical-energy claim.",
    }
    write(dest / verification_name, report)
    print(json.dumps({"verification": str(dest / verification_name), "tests": test_report,
                      "conformance_checks_passed": report["conformance_checks_passed"],
                      "actual_GPU_capture": report["actual_GPU_capture"], "partial": report["partial"],
                      "canonical_agent_archive_sha256": report["canonical_agent_archive_sha256"],
                      "welip_archive_sha256": report["welip_archive_sha256"]}), flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
