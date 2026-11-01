"""Qualify frozen OpenClaw consumers against one admitted, unreleased Bun binary."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

TEMP = Path(os.environ['RUNNER_TEMP'])
WORKSPACE = Path(os.environ['GITHUB_WORKSPACE'])
ROOT = TEMP / 'downstream'
PROOF = TEMP / 'downstream-proof'
SOURCE = '9f5edfb699e35691497b06572a321b20994ca4e5'
BUN = 'd9be087429c21e563bb5ac29f8a11805e64b56a3'
OPENCLAW = '2952110b2a14efac009e1cc5fb758cd8ed15d193'
BIRDCLAW = '59c9ee27f39238654efc93ff7862b27ad474c044'
REPLAY = 41324678688
CARRIER = '9f03dbd21a64683d1b32e50ace51270248bf92a5'
EXECUTABLE = '2ec7cfd15b846d11d1f45e311fbc10fd7b447f6fcfb579485525ee1233e95513'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(name, value):
    (PROOF / name).write_text(json.dumps(value, indent=2) + '\n')


def head(repo, expected):
    assert subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip() == expected


def admit():
    PROOF.mkdir()
    ROOT.mkdir()
    helper = WORKSPACE / 'carrier/.github/openclaw/qualification/assemble-retained-matrix.py'
    spec = importlib.util.spec_from_file_location('retained', helper)
    retained = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retained)
    run, jobs = retained.run_identity(REPLAY, CARRIER, 'openclaw-current-linux-consumer.yml')
    assert run['conclusion'] == 'success' and jobs['current-consumer']['conclusion'] == 'success'
    records = {}
    for label, row in {
        'current-linux-consumer-proof': (13090894299, 407316, 'sha256:63c674db96939947df3671c2187c39db96bd2f6a43340f10f7edf413fa09148d'),
        'current-linux-bun-executables': (13090653410, 183705425, 'sha256:7b4599e44b1a68ace49cffa533209acb6a255542bb59dc6aa8ff250b15f5099e'),
    }.items():
        records[label] = retained.download(ROOT, label, row, REPLAY, CARRIER)
    evidence = ROOT / 'current-linux-consumer-proof'
    identity = read(evidence / 'candidate-identity.json')
    assert identity['candidate']['commit'] == BUN and identity['engine']['source'] == SOURCE
    assert identity['runtime'] == {'bun_revision': BUN, 'webkit': SOURCE, 'platform': 'linux', 'architecture': 'x64'}
    gate = read(evidence / 'gate.json')
    assert gate['passed'] is True and gate['candidate_identity_sha256'] == sha(evidence / 'candidate-identity.json')
    build = read(evidence / 'candidate-build-tools.json')
    assert sha(evidence / 'candidate-build-tools.json') == identity['build_tools']['sha256']
    assert build['compiled_inputs_sha256'] == '33c6f0b30bf33c45b2aab86ca7bf9692cbb30e2114d2e70e255e9ac43e52f614'
    binary = ROOT / 'current-linux-bun-executables' / identity['executable']['path']
    assert binary.stat().st_size == identity['executable']['size'] == 105658384
    assert sha(binary) == identity['executable']['sha256'] == EXECUTABLE
    binary.chmod(0o755)
    bindir = ROOT / 'bin'
    bindir.mkdir()
    (bindir / 'bun').symlink_to(binary)
    write('admission.json', {'passed': True, 'mode': 'downstream-smoke', 'source': SOURCE, 'bun': BUN,
          'binary': str(binary), 'sha256': EXECUTABLE, 'bytes': binary.stat().st_size,
          'compiled_inputs_sha256': build['compiled_inputs_sha256'], 'inputs': records,
          'controls': {'controller_sha256': sha(Path(__file__)), 'retained_helper_sha256': sha(helper)}})
    with Path(os.environ['GITHUB_ENV']).open('a') as stream:
        stream.write('BUN_BIN=' + str(binary) + '\n')
    with Path(os.environ['GITHUB_PATH']).open('a') as stream:
        stream.write(str(bindir) + '\n')


def candidate():
    admission = read(PROOF / 'admission.json')
    binary = Path(os.environ['BUN_BIN'])
    assert str(binary) == admission['binary'] and binary.is_absolute()
    assert binary.stat().st_size == admission['bytes'] and sha(binary) == admission['sha256'] == EXECUTABLE
    assert Path(shutil.which('bun')).resolve() == binary
    revision = subprocess.check_output([str(binary), '--revision'], text=True).strip()
    script = 'console.log(JSON.stringify({bun_revision:Bun.revision,webkit:process.versions.webkit,platform:process.platform,architecture:process.arch}))'
    observed = json.loads(subprocess.check_output([str(binary), '--no-env-file', '-e', script], text=True))
    assert observed == {'bun_revision': BUN, 'webkit': SOURCE, 'platform': 'linux', 'architecture': 'x64'}
    write('candidate-runtime.json', {'runtime': observed, 'cli_revision': revision, 'binary_sha256': sha(binary)})
    return binary, revision


def vitest(path, files):
    report = read(path)
    assert report['success'] is True
    total = sum(files.values())
    assert report['numTotalTests'] == report['numPassedTests'] == total
    assert all(report[key] == 0 for key in ('numFailedTests', 'numPendingTests', 'numTodoTests'))
    results = report['testResults']
    assert len(results) == len(files)
    for suffix, count in files.items():
        rows = [row for row in results if row['name'].endswith('/' + suffix)]
        assert len(rows) == 1 and rows[0]['status'] == 'passed'
        cases = rows[0]['assertionResults']
        assert len(cases) == count and all(case['status'] == 'passed' for case in cases)


def openclaw():
    binary, revision = candidate()
    repo = WORKSPACE / 'openclaw'
    head(repo, OPENCLAW)
    report = read(PROOF / 'openclaw-smoke/report.json')
    assert report['ok'] is True and not report.get('fatalError') and report['entry']
    assert Path(report['bun']).resolve() == binary and report['bunRevision'] == revision
    assert [row['name'] for row in report['steps']] == [
        'preconditions', 'install', 'cli', 'gateway', 'node-host', 'agent', 'doctor', 'terminals', 'browser', 'cleanup']
    assert all(row['status'] == 'passed' for row in report['steps'])
    assert all(report[key] == [] for key in ('blockers', 'attempts', 'unexpectedAttempts', 'staleBlockers', 'failedSteps'))
    vitest(PROOF / 'openclaw-sqlite.json', {'src/infra/sqlite-existing-database.bun.test.ts': 1,
                                         'src/infra/sqlite-worker-input.bun.test.ts': 1})
    write('openclaw-gate.json', {'passed': True, 'head': OPENCLAW, 'binary_sha256': sha(binary),
          'revision': revision, 'smoke_steps': 10, 'sqlite_cases': 2,
          'report_sha256': sha(PROOF / 'openclaw-smoke/report.json'),
          'package_sha256': sha(TEMP / 'package/candidate.tgz')})


def birdclaw():
    binary, revision = candidate()
    repo = WORKSPACE / 'birdclaw'
    head(repo, BIRDCLAW)
    vitest(PROOF / 'birdclaw-vitest.json', {'src/lib/sqlite.test.ts': 3,
        'src/lib/database-migrations.test.ts': 4, 'src/lib/production-server.test.ts': 5})
    report = read(PROOF / 'birdclaw-runtime.json')
    assert report['schemaVersion'] == 1 and report['gitSha'] == BIRDCLAW and report['iterations'] == 1
    assert report['runtime'] == {'executable': str(binary), 'args': ['--no-env-file'], 'identity': revision}
    assert Path(report['home']) == TEMP / 'birdclaw-home'
    assert report['inputDatabaseLogicalSha256'] == report['finalDatabaseLogicalSha256']
    for key, name in {'launcherSha256': 'bin/birdclaw.mjs', 'cliSha256': 'dist/cli/birdclaw.js',
                      'serverSha256': 'dist/server/server.js'}.items():
        assert report['artifacts'][key] == sha(repo / name)
    assert len(report['samples']['cliMs']) == len(report['samples']['server']) == 1
    for elapsed in report['samples']['cliMs']:
        assert math.isfinite(elapsed) and elapsed >= 0
    for row in report['samples']['server']:
        assert all(math.isfinite(row[key]) and row[key] >= 0 for key in ('listeningMs', 'firstResponseMs'))
    write('birdclaw-gate.json', {'passed': True, 'head': BIRDCLAW, 'binary_sha256': sha(binary),
          'revision': revision, 'test_cases': 12, 'runtime_iterations': 1,
          'report_sha256': sha(PROOF / 'birdclaw-runtime.json'), 'artifacts': report['artifacts']})


if __name__ == '__main__':
    {'admit': admit, 'identity': candidate, 'openclaw': openclaw, 'birdclaw': birdclaw}[sys.argv[1]]()
