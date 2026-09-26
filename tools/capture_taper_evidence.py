"""Capture DP1-DP10 tests and CPU/device/continuation evidence without skips.

The full suite and both conformance programs must pass against an unchanged
source inventory. Reports are tied to the committed preimplementation PDF.
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
DEST = ROOT / "docs/evidence/directional-v1"
FORMAL_COMMIT = "1979e66634c10fc8ede019fd677434bb1dba4a7d"
BASE_COMMIT = "1ea93207ae8545a5c5d344677cb73a5c459dc91c"
FORMAL_PDF_SHA = "b11d6ab9037578dc2d46fe806dc45502ab0002d23ca8d79f044ef94edb29bd77"
ELI5_SHA = "06556d7bbae0de54e99f3abb9329869da1fbf085c6c1aab66d563528989c3ea0"
HOST_ONLY_GPU_CLASS_METHODS = {
    "test_taper_gpu.TaperGpuTests.test_preflight_rejection_allocates_no_device",
    "test_organogram_gpu.OrganogramGpuTests.test_invalid_tape_preflight_allocates_no_device",
    "test_gpu.RealGpuTests.test_unavailable_or_software_adapter_is_not_silently_replaced_by_cpu",
    "test_gpu.RealGpuTests.test_invalid_upload_configuration_and_paths_are_rejected",
    "test_welip_gpu.WelipGpuTests.test_cpu_wrapper_uses_codec_and_field_only_controls_preserve_history",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def run(args, timeout=1800):
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
    for directory in ("directional-v1", "welip-v1", "organogram-v1", "growth-v1"):
        for name in ("reference-builder.py", "formal-reference.json"):
            paths.add(ROOT / "docs/evidence" / directory / name)
    for name in ("geometry-audit.py", "geometry-audit.json"):
        paths.add(DEST / name)
    return {path.relative_to(ROOT).as_posix(): digest(path.read_bytes().replace(b"\r\n", b"\n"))
            for path in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEST)
    args = parser.parse_args()
    dest = args.output_dir.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    sources_before = source_manifest()
    tests = list(leaves(unittest.defaultTestLoader.discover(str(ROOT / "tests"))))
    test_args = ["-m", "unittest", "discover", "-s", "tests", "-v"]
    print("Running the complete suite, including actual GPU tests.", flush=True)
    result = run(test_args)
    log = result.stdout + result.stderr
    (dest / "full-tests.txt").write_text(log, encoding="utf-8", newline="\n")
    match = re.search(r"Ran (\d+) tests in ([0-9.]+)s", log)
    if (match is None or not log.rstrip().endswith("OK")
            or "skipped=" in log or "... skipped" in log):
        raise ValueError("Complete suite must pass with zero skips")
    if len(tests) != int(match[1]):
        raise ValueError("Discovered test count differs from the executed suite")
    explicit = {"F8GpuTests", "HadamardGpuTests", "RealHadamardAgentTests",
                "RealGrowthAgentTests", "RealGrowthContinuationTests", "GrowthGpuTests",
                "OrganogramGpuTests", "RealOrganogramAgentTests", "RealOrganogramContinuationTests",
                "WelipGpuTests", "TaperGpuTests", "RealTaperAgentTests",
                "RealTaperContinuationTests", "TaperWelipGpuTests"}
    if not HOST_ONLY_GPU_CLASS_METHODS <= {test.id() for test in tests}:
        raise ValueError("GPU method accounting exclusions no longer match the test inventory")
    actual_device = Counter(test.__class__.__name__ for test in tests
                            if test.id() not in HOST_ONLY_GPU_CLASS_METHODS
                            and (test.__class__.__name__ in explicit
                                 or getattr(test, "backend", None) == "gpu"
                                 or (test.__class__.__name__.startswith("Real") and "Gpu" in test.__class__.__name__)))
    test_report = {"passed": int(match[1]), "skipped": 0, "elapsed_seconds": float(match[2]),
                   "complete_suite": True,
                   "module_counts": dict(Counter(test.__class__.__module__ for test in tests)),
                   "actual_device_methods": dict(actual_device),
                   "host_only_methods_excluded_from_device_count": sorted(HOST_ONLY_GPU_CLASS_METHODS)}
    print(json.dumps(test_report), flush=True)
    reports = {}
    commands = [[sys.executable, *test_args]]
    for module, filename in (("taper_conformance", "conformance.json"),
                             ("taper_welip_conformance", "welip-conformance.json")):
        print(f"Running {module} against frozen references and actual GPU.", flush=True)
        command = ["-m", f"examples.{module}", "--output", str(dest / filename)]
        run(command)
        commands.append([sys.executable, *command])
        value = json.loads((dest / filename).read_text(encoding="utf-8"))
        if (not value["checks"] or any(check is not True for check in value["checks"].values())
                or value["actual_GPU_capture"] is not True or value.get("partial", False)):
            raise ValueError("Actual-device conformance obligation failed: " + module)
        reports[filename] = value
    sources_after = source_manifest()
    if sources_before != sources_after:
        changed = sorted(name for name in sources_before.keys() | sources_after.keys()
                         if sources_before.get(name) != sources_after.get(name))
        raise ValueError("Sources changed during capture: " + ", ".join(changed))
    pdf = subprocess.check_output(["git", "show",
        f"{FORMAL_COMMIT}:output/pdf/Tom_Klootwijk_Ontological_Deterministic_Computing_v2.0.pdf"], cwd=ROOT)
    if digest(pdf) != FORMAL_PDF_SHA:
        raise ValueError("Preimplementation formal PDF identity differs")
    eli5_hash = digest((ROOT / "output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf").read_bytes())
    if eli5_hash != ELI5_SHA:
        raise ValueError("The separately completed ELI5 PDF has changed")
    conformance = reports["conformance.json"]
    welip = reports["welip-conformance.json"]
    import wgpu
    report = {
        "format": "directional-verification-v1", "captured_utc": datetime.now(timezone.utc).isoformat(),
        "formal_binding_commit": FORMAL_COMMIT, "base_commit": BASE_COMMIT,
        "preimplementation_formal_pdf_sha256": digest(pdf),
        "actual_GPU_capture": True, "partial": False, "tests": test_report,
        "conformance_checks_passed": len(conformance["checks"]),
        "welip_conformance_checks_passed": len(welip["checks"]),
        "capture_elapsed_seconds": round(perf_counter() - started, 3),
        "canonical_agent_archive_sha256": conformance["canonical_archive_sha256"],
        "welip_archive_sha256": welip["welip_archive_sha256"],
        "mission_results": {name: value["archive"]["expected"]
                            for name, value in conformance["CPU"]["cases"].items()},
        "lifecycle_counts": {"variants": 3, "operations_each": 19, "records_each": 20, "carrier_words_each": 41},
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "wgpu": wgpu.__version__, "adapter": welip["adapter"]},
        "source_sha256_lf": sources_after, "source_manifest_unchanged_during_capture": True,
        "report_sha256_lf": {name: digest((dest / name).read_bytes().replace(b"\r\n", b"\n"))
                             for name in ("full-tests.txt", "conformance.json", "welip-conformance.json")},
        "eli5_pdf_unchanged_sha256": eli5_hash,
        "original_source_sha256": {name: digest((ROOT / name).read_bytes()) for name in
            ("Tom_Klootwijk_Log_Encoded_Polar_LUT_Paradigm_v1.0.pdf",
             "sources/solus-ion-ad-infinitum.pdf", "sources/solipsism.pdf")},
        "commands": commands,
        "remaining_obligations": ["Distinct three-dimensional cone and pyramid volumes",
                                  "General graph productions", "Global spectral choices",
                                  "Physical adapters", "Universality proofs",
                                  "Comparative hardware and texture-cache measurements"],
        "scope": "Finite DP1-DP10 correctness: directional 2D section geometry, exact signed fields, "
                 "same-owner continuation and explicit Wv2 durability on CPU and actual GPU. "
                 "No universality, cache saturation, throughput or physical-energy claim.",
    }
    write(dest / "verification.json", report)
    print(json.dumps({"verification": str(dest / "verification.json"), "tests": test_report,
                      "conformance_checks_passed": report["conformance_checks_passed"],
                      "welip_conformance_checks_passed": report["welip_conformance_checks_passed"],
                      "canonical_agent_archive_sha256": report["canonical_agent_archive_sha256"],
                      "welip_archive_sha256": report["welip_archive_sha256"]}), flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
