"""Bind the ordinary consumer source and real VM debug pre-push evidence."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
from xml.etree import ElementTree

SOURCE = Path('/work/source')
ENGINE = Path('/work/engine')
OUT = Path('/work/vm-debug-proof')
CONTROLS = Path(__file__).resolve().parent
BUN = 'd9be087429c21e563bb5ac29f8a11805e64b56a3'
TREE = '980068aa5aa9f51f40fc4125114a68fccd9bc9dc'
WEBKIT = '42e4245f4180941634b482a7e8ef7fca47467de5'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def state(files, adapted):
    assert git(SOURCE, 'rev-parse', 'HEAD', 'HEAD^{tree}').splitlines() == [BUN, TREE]
    assert git(SOURCE, 'write-tree') == TREE
    assert git(ENGINE, 'rev-parse', 'HEAD') == WEBKIT
    assert not git(ENGINE, 'status', '--porcelain')
    changed = set(git(SOURCE, 'diff', '--name-only', 'HEAD').splitlines())
    changed.update(git(SOURCE, 'ls-files', '--others', '--exclude-standard').splitlines())
    assert changed == (set(files) if adapted else set())
    for name, row in files.items():
        path = SOURCE / name
        assert path.is_file() and not path.is_symlink()
        assert sha(path) == row['after' if adapted else 'before'], name
        assert stat.S_IMODE(path.stat().st_mode) == int(row['mode'], 8) & 0o777, name
        assert git(SOURCE, 'hash-object', '--', name) == row['adapted_blob' if adapted else 'base_blob'], name


def main(mode):
    adapter = CONTROLS / 'harness-adapters.json'
    assert sha(adapter) == 'b8f26ddac333687c8bbfb8f0f9508822065d4ae7027059fcb4a979af426a321e'
    candidate = json.loads(adapter.read_text())['arms']['candidate']
    assert candidate['pin'] == BUN
    files = {}
    controls = {'harness-adapters.json': sha(adapter), 'debug-vm-consumer.py': sha(Path(__file__))}
    for phase in ('build', 'test'):
        spec = candidate[phase]
        assert not set(files).intersection(spec['files'])
        files.update(spec['files'])
        assert sha(CONTROLS / spec['patch']) == spec['sha256']
        controls[spec['patch']] = spec['sha256']
    assert len(files) == 20
    OUT.mkdir(exist_ok=True)
    if mode == 'prepare':
        assert not (OUT / 'proof.json').exists()
        state(files, False)
        for phase in ('build', 'test'):
            patch = str(CONTROLS / candidate[phase]['patch'])
            subprocess.run(['git', '-C', str(SOURCE), 'apply', '--check', patch], check=True)
            subprocess.run(['git', '-C', str(SOURCE), 'apply', patch], check=True)
        state(files, True)
        tools = {name: subprocess.check_output(command, text=True).strip()
                 for name, command in {'bun': ['bun', '--version'], 'rust': ['rustc', '--version'],
                                       'clang': ['clang', '--version']}.items()}
        (OUT / 'proof.json').write_text(json.dumps({'passed': False, 'mode': 'vm-debug-prepush',
            'bun': BUN, 'tree': TREE, 'webkit': WEBKIT, 'files': files, 'controls': controls,
            'tools': tools}, indent=2) + '\n')
    else:
        assert mode == 'verify'
        proof = json.loads((OUT / 'proof.json').read_text())
        assert proof['passed'] is False and proof['files'] == files and proof['controls'] == controls
        state(files, True)
        xml = OUT / 'vm-junit.xml'
        cases = list(ElementTree.parse(xml).iter('testcase'))
        assert cases and all(not any(case.find(tag) is not None for tag in ('failure', 'error')) for case in cases)
        targets = [case for case in cases if 'shared source buffers survive compilation-cache eviction:' in case.get('name', '')]
        assert len(targets) == 2 and all(case.find('skipped') is None for case in targets)
        for marker in ('é', 'λ🚀'):
            assert sum(marker in case.get('name', '') for case in targets) == 1
        binary = SOURCE / 'build/debug-prepush/bun-debug'
        proof.update(passed=True, testcases=len(cases), target_cases=[case.get('name') for case in targets],
                     junit_sha256=sha(xml), binary={'bytes': binary.stat().st_size, 'sha256': sha(binary)})
        (OUT / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')


if __name__ == '__main__':
    assert len(sys.argv) == 2
    main(sys.argv[1])
