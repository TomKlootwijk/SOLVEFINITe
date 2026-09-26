"""Capture the complete GD suite, real GPU conformance and process-boundary replay."""

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
DEST = ROOT / 'docs/evidence/growth-v1'
FORMAL_COMMIT = '00b0e64decd2d8202725b71c101480843b1af1e2'
BASE_COMMIT = '5a304bcca77965778e1acb743d49d54e2a79e380'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(',', ':')).encode())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')


def run(args, timeout=600):
    result = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True,
                            text=True, encoding='utf-8', timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'Command failed: {args}\n{result.stdout}\n{result.stderr}')
    return result


def leaves(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from leaves(item)
        else:
            yield item


def main():
    started = perf_counter()
    print('Running the complete suite, including actual GPU tests.', flush=True)
    result = run(['-m', 'unittest', 'discover', '-s', 'tests', '-v'])
    log = result.stdout + result.stderr
    (DEST / 'full-tests.txt').write_text(log, encoding='utf-8', newline='\n')
    match = re.search(r'Ran (\d+) tests in ([0-9.]+)s', log)
    if match is None or '\nOK\n' not in log or 'skipped=' in log or '... skipped' in log:
        raise ValueError('The entire suite must pass with zero skips')
    tests = list(leaves(unittest.defaultTestLoader.discover(str(ROOT / 'tests'))))
    if len(tests) != int(match[1]):
        raise ValueError('Discovery differs from the executed suite')
    explicit = {'F8GpuTests', 'HadamardGpuTests', 'RealHadamardAgentTests', 'RealGrowthAgentTests',
                'RealGrowthContinuationTests', 'GrowthGpuTests'}
    actual_device = Counter(test.__class__.__name__ for test in tests
                            if test.__class__.__name__ in explicit or
                            (test.__class__.__name__.startswith('Real') and
                             'Gpu' in test.__class__.__name__))
    test_report = {'passed': int(match[1]), 'skipped': 0, 'elapsed_seconds': float(match[2]),
                   'module_counts': dict(Counter(test.__class__.__module__ for test in tests)),
                   'actual_device_methods': dict(actual_device)}
    print(json.dumps(test_report), flush=True)
    print('Running independent-reference growth conformance on CPU and GPU.', flush=True)
    conform_started = perf_counter()
    run(['-m', 'examples.growth_conformance', '--output', str(DEST / 'conformance.json')])
    conform_seconds = perf_counter() - conform_started
    conformance = json.loads((DEST / 'conformance.json').read_text(encoding='utf-8'))
    if not conformance['checks'] or any(value is not True for value in conformance['checks'].values()):
        raise ValueError('Every conformance check must pass')

    print('Capturing fresh-process GPU -> CPU -> GPU growth and inspection.', flush=True)
    scratch = ROOT / 'output/growth/cli' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    scratch.mkdir(parents=True)
    scenario, state = scratch / 'scenario.json', scratch / 'session.json'
    commands = [
        ['-m', 'solvefinite', 'agent', 'scenario', '--profile', 'growth', '--output', str(scenario)],
        ['-m', 'solvefinite', 'agent', 'run', '--scenario', str(scenario), '--state', str(state),
         '--steps', '4', '--capacity', '1', '--backend', 'gpu', '--index-sign', '-1'],
        ['-m', 'solvefinite', 'agent', 'run', '--state', str(state), '--steps', '1',
         '--capacity', '3', '--backend', 'cpu', '--index-epoch', '12', '--index-phase-origin', '192'],
        ['-m', 'solvefinite', 'agent', 'run', '--state', str(state), '--steps', '64',
         '--capacity', '2', '--backend', 'gpu', '--index-epoch', '20', '--index-sign', '-1'],
    ]
    outputs = [json.loads(run(command).stdout) for command in commands]
    before = state.read_bytes()
    inspection = ['-m', 'solvefinite', 'agent', 'inspect', str(state), '--backend', 'cpu']
    commands.append(inspection)
    outputs.append(json.loads(run(inspection).stdout))
    if (outputs[1]['state']['status'] != 'GROWTH_PENDING'
            or outputs[2]['state']['geometry_epoch'] != 1
            or outputs[-1]['state']['energy'] != 64 or state.read_bytes() != before):
        raise ValueError('Fresh process growth, energy or read-only inspection failed')
    archive_hash = canonical(json.loads(before)['agent'])
    if archive_hash != conformance['canonical_archive_sha256']:
        raise ValueError('Conformance and CLI canonical histories differ')
    write(DEST / 'cli-replay.json', {'commands': commands, 'outputs': outputs,
          'inspection_kept_saved_bytes': True, 'saved_bytes_sha256': digest(before),
          'canonical_archive_sha256': archive_hash})

    import wgpu
    source_paths = sorted({path for directory in ('solvefinite', 'tests', 'examples')
                           for path in (ROOT / directory).rglob('*')
                           if path.is_file() and path.suffix in ('.py', '.wgsl', '.json')})
    source_paths += [Path(__file__), DEST / 'reference-builder.py', DEST / 'formal-reference.json']
    source_hashes = {path.relative_to(ROOT).as_posix(): digest(path.read_bytes().replace(b'\r\n', b'\n'))
                     for path in source_paths}
    report_hashes = {name: digest((DEST / name).read_bytes().replace(b'\r\n', b'\n'))
                     for name in ('full-tests.txt', 'conformance.json', 'cli-replay.json')}
    report = {
        'format': 'growth-verification-v1', 'captured_utc': datetime.now(timezone.utc).isoformat(),
        'formal_binding_commit': FORMAL_COMMIT, 'base_commit': BASE_COMMIT,
        'initial_formal_binding_commit': 'ec1181e00f40c3663e73974885573ebfae784e08',
        'tests': test_report, 'conformance_checks_passed': len(conformance['checks']),
        'conformance_elapsed_seconds': round(conform_seconds, 3),
        'capture_elapsed_seconds': round(perf_counter() - started, 3),
        'canonical_archive_sha256': archive_hash,
        'final_state': outputs[-1]['state'], 'execution_info': outputs[3]['execution_info'],
        'environment': {'python': sys.version, 'platform': platform.platform(), 'wgpu': wgpu.__version__,
                        'adapter': outputs[3]['execution_info']['adapter']},
        'source_sha256_lf': source_hashes, 'report_sha256_lf': report_hashes,
        'eli5_pdf_unchanged_sha256': digest((ROOT / 'output/pdf/Tom_Klootwijk_Paradigm_ELI5.pdf').read_bytes()),
        'commands': ['python -m unittest discover -s tests -v',
                     'python -m examples.growth_conformance --output docs/evidence/growth-v1/conformance.json',
                     'Fresh process commands retained in cli-replay.json'],
        'remaining_obligations': ['General production grammars', 'Global spectral traversal',
                                  'Physical adapters', 'Wider temporal continuation',
                                  'Comparative hardware measurements'],
        'scope': 'Finite GD1-GD8 correctness and continuation evidence; no throughput or physical-energy claim.',
    }
    write(DEST / 'verification.json', report)
    print(json.dumps({'tests': test_report, 'checks': len(conformance['checks']),
                      'canonical_archive_sha256': archive_hash, 'verification': str(DEST / 'verification.json')}), flush=True)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    main()
