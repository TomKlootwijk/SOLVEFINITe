"""Capture HP verification after executing the full suite and hardware conformance.

Run with the GPU-enabled Python from the repository root. This deliberately
requires actual hardware; skipped tests do not constitute a successful capture.
The final PDF and its layout QA are produced separately from this source-bound
runtime evidence, avoiding a circular artifact hash.
"""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from time import perf_counter
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'docs/evidence/hadamard-v1'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


def run(args, timeout=300):
    result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True,
                            text=True, encoding='utf-8', timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Command failed: {args}\n{result.stdout}\n{result.stderr}')
    return result


def leaves(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from leaves(test)
        else:
            yield test


def main():
    started = perf_counter()
    DEST.mkdir(parents=True, exist_ok=True)
    print('Running the full suite.', flush=True)
    result = run(['-m', 'unittest', 'discover', '-s', 'tests', '-v'])
    log = result.stdout + result.stderr
    (DEST / 'full-tests.txt').write_text(log, encoding='utf-8', newline='\n')
    match = re.search(r'Ran (\d+) tests in ([0-9.]+)s', log)
    if match is None or '\nOK\n' not in log or 'skipped=' in log or '... skipped' in log:
        raise ValueError('The complete test log must pass without skips')
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    tests = list(leaves(suite))
    if len(tests) != int(match[1]):
        raise ValueError('Discovered tests differ from the executed count')
    module_counts = Counter(test.__class__.__module__ for test in tests)
    device_classes = {'F8GpuTests', 'HadamardGpuTests', 'RealHadamardGpuTests'}
    actual_device = Counter(test.__class__.__name__ for test in tests
                            if test.__class__.__name__ in device_classes or
                            (test.__class__.__name__.startswith('Real') and
                             'Gpu' in test.__class__.__name__) or
                            test.__class__.__name__ == 'RealHadamardAgentTests')
    test_report = {'passed': int(match[1]), 'skipped': 0,
                   'elapsed_seconds': float(match[2]),
                   'module_counts': dict(module_counts),
                   'actual_device_methods': dict(actual_device)}
    print(json.dumps(test_report), flush=True)
    print('Running actual-device HP conformance.', flush=True)
    conformance_started = perf_counter()
    run(['-m', 'examples.hadamard_conformance', '--output', str(DEST / 'conformance.json')])
    conformance_seconds = perf_counter() - conformance_started
    conformance = json.loads((DEST / 'conformance.json').read_text(encoding='utf-8'))
    if not conformance['checks'] or any(value is not True for value in conformance['checks'].values()):
        raise ValueError('Every named hardware conformance check must pass')

    print('Capturing fresh-process GPU -> CPU -> GPU CLI replay.', flush=True)
    scratch = ROOT / 'output/hadamard/cli' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    scratch.mkdir(parents=True)
    scenario, state, live_config = (scratch / name for name in ('scenario.json', 'session.json', 'live.json'))
    commands = [
        ['-m', 'solvefinite', 'agent', 'scenario', '--profile', 'hadamard', '--output', str(scenario)],
        ['-m', 'solvefinite', 'agent', 'live-config', '--profile', 'hadamard', '--output', str(live_config)],
        ['-m', 'solvefinite', 'agent', 'run', '--scenario', str(scenario), '--state', str(state),
         '--steps', '2', '--capacity', '1', '--backend', 'gpu', '--index-sign', '-1', '--index-phase-origin', '250'],
        ['-m', 'solvefinite', 'agent', 'run', '--state', str(state), '--steps', '20', '--capacity', '3',
         '--backend', 'cpu', '--index-epoch', '12', '--index-phase-origin', '192'],
    ]
    outputs = [json.loads(run(command).stdout) for command in commands]
    before = state.read_bytes()
    inspect = ['-m', 'solvefinite', 'agent', 'inspect', str(state), '--backend', 'gpu',
               '--index-sign', '-1', '--index-epoch', '20', '--index-phase-origin', '64']
    commands.append(inspect)
    outputs.append(json.loads(run(inspect).stdout))
    if before != state.read_bytes() or outputs[-1]['state']['energy'] != 86:
        raise ValueError('CLI replay changed durable bytes or the expected final energy')
    cli = {'commands': commands, 'outputs': outputs, 'inspection_kept_saved_bytes': True,
           'saved_bytes_sha256': digest(before), 'archive_sha256': canonical(json.loads(before)['agent'])}
    write(DEST / 'cli-replay.json', cli)

    from solvefinite.field_agent import FieldAgentManifest
    from solvefinite.session import Scenario
    from solvefinite.tomigidt import Tomigidt
    agent = Tomigidt(FieldAgentManifest())
    try:
        old_scenario = Scenario(agent.manifest, changes=((2, 'k:0:3', 70),))
        while agent.status != 'COMPLETE':
            agent.step(old_scenario.observe(agent.position, agent.cycle + 1))
        legacy_hash = canonical(agent.archive())
    finally:
        agent.close()
    if legacy_hash != '291b28c7f14634079fb262d69b87c8fca2b4749fe367519e9cb75a92e15aa9cb':
        raise ValueError('Existing FI/PX canonical mission changed')
    import wgpu
    source_paths = sorted({path for directory in ('solvefinite', 'tests', 'examples')
                           for path in (ROOT / directory).rglob('*')
                           if path.is_file() and path.suffix in ('.py', '.wgsl', '.json')})
    source_paths += [Path(__file__), DEST / 'reference-builder.py', DEST / 'formal-reference.json']
    source_hashes = {path.relative_to(ROOT).as_posix(): digest(path.read_bytes().replace(b'\r\n', b'\n'))
                     for path in source_paths}
    report_hashes = {name: digest((DEST / name).read_bytes().replace(b'\r\n', b'\n'))
                     for name in ('full-tests.txt', 'conformance.json', 'cli-replay.json')}
    execution = outputs[-1]['execution_info']
    if cli['archive_sha256'] != conformance['canonical_archive_sha256']:
        raise ValueError('Fresh CLI replay and the independent conformance mission disagree')
    verification = {
        'format': 'hadamard-verification-v1', 'captured_utc': datetime.now(timezone.utc).isoformat(),
        'formal_binding_commit': '0c862c310a13b0baef82065efc2464f14c280f9d',
        'base_commit': '4b8fa89ea68a98fe293c21b925a31cf5870e84c7',
        'tests': test_report, 'conformance_checks_passed': len(conformance['checks']),
        'conformance_elapsed_seconds': round(conformance_seconds, 3),
        'capture_elapsed_seconds': round(perf_counter() - started, 3),
        'environment': {'python': sys.version, 'platform': platform.platform(), 'wgpu': wgpu.__version__,
                        'adapter': execution['adapter']},
        'allocation_info': conformance['GPU']['execution_info']['allocation_info'],
        'deferred_mission_cycles': conformance['GPU_deferred']['archive']['expected']['cycle'],
        'gpu_domains': len(conformance['GPU_domains']),
        'gpu_nodes': sum(item['nodes'] for item in conformance['GPU_domains']),
        'gpu_penalty_checks': sum(item['penalty_checks'] for item in conformance['GPU_domains']),
        'canonical_archive_sha256': cli['archive_sha256'],
        'legacy_field_archive_sha256': legacy_hash, 'final_state': outputs[-1]['state'],
        'source_sha256_lf': source_hashes, 'report_sha256_lf': report_hashes,
        'eli5_pdf_unchanged_sha256': digest((ROOT / 'output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf').read_bytes()),
        'commands': ['python -m unittest discover -s tests -v',
                     'python -m examples.hadamard_conformance --output docs/evidence/hadamard-v1/conformance.json',
                     'See cli-replay.json for fresh-process GPU -> CPU -> GPU execution.'],
        'remaining_obligations': ['Global Psi traversal', 'geometry-changing growth',
                                  'active scale transitions', 'continuing semantic epochs',
                                  'physical adapters', 'comparative hardware performance'],
        'scope': 'Finite correctness evidence for the HP binding; no physical energy or throughput claim.',
    }
    write(DEST / 'verification.json', verification)
    print(json.dumps({'tests': test_report, 'conformance_checks': len(conformance['checks']),
                      'verification': str(DEST / 'verification.json')}), flush=True)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    main()
