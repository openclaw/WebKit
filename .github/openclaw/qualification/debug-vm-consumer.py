"""Bind the ordinary consumer source and real VM debug pre-push evidence."""
import hashlib
import json
from pathlib import Path
import stat
import shlex
import subprocess
import sys
from xml.etree import ElementTree

SOURCE = Path('/work/source')
ENGINE = Path('/work/engine')
OUT = Path('/work/vm-debug-proof')
CONTROLS = Path(__file__).resolve().parent
BUN = 'd9be087429c21e563bb5ac29f8a11805e64b56a3'
TREE = '980068aa5aa9f51f40fc4125114a68fccd9bc9dc'
WEBKIT = '4430cc2e4caa5720c2f78963be3566c87b958084'


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
    assert sha(adapter) == '0359c6c59e00cf85022dffa283f5631a1ed2ad6b0363fc9e3fbca23f5c0fdd11'
    candidate = json.loads(adapter.read_text())['arms']['candidate']
    assert candidate['pin'] == BUN
    files = {}
    controls = {'harness-adapters.json': sha(adapter), 'debug-vm-consumer.py': sha(Path(__file__))}
    for phase in ('build', 'current_test'):
        spec = candidate[phase]
        assert not set(files).intersection(spec['files'])
        files.update(spec['files'])
        assert sha(CONTROLS / spec['patch']) == spec['sha256']
        controls[spec['patch']] = spec['sha256']
    files['scripts/build/deps/webkit.ts'] = {'before': '6d9cbc1eda6cea88b185d1956a5947f2ed682ed09ff501617d64c869f3a12af7', 'after': 'ff61c61e17ead2dd9f8c5bb3b557e83b7df41e2f65080c28239b2df384cff622', 'base_blob': '0b631209150b8c2eb7c5020e0c5f0b1e598a3ef7', 'adapted_blob': '8be8d3de7c95c4f151aa07e6715d1785b79f952e', 'mode': '100644'}
    controls['harness-adapters/candidate-debug-local-build.patch'] = '8afbba5559780cb1c797b6ae095c1586684b2217ebe860adb56b6349ffefb204'
    assert sha(CONTROLS / 'harness-adapters/candidate-debug-local-build.patch') == controls['harness-adapters/candidate-debug-local-build.patch']
    assert len(files) == 22
    OUT.mkdir(exist_ok=True)
    if mode == 'prepare':
        assert not (OUT / 'proof.json').exists()
        state(files, False)
        for phase in ('build', 'current_test'):
            patch = str(CONTROLS / candidate[phase]['patch'])
            subprocess.run(['git', '-C', str(SOURCE), 'apply', '--check', patch], check=True)
            subprocess.run(['git', '-C', str(SOURCE), 'apply', patch], check=True)
        local_patch = str(CONTROLS / 'harness-adapters/candidate-debug-local-build.patch')
        subprocess.run(["git", "-C", str(SOURCE), "apply", "--check", local_patch], check=True)
        subprocess.run(["git", "-C", str(SOURCE), "apply", local_patch], check=True)
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
        build = SOURCE / 'build/debug-prepush'
        engine_build = build / 'deps/WebKit'
        build_command = ['bun', 'bd', '--webkit=local', '--webkit-version=' + WEBKIT,
            '--ci=off', '--buildkite=off', '--build-dir=build/debug-prepush', '-j2']
        cache_path = engine_build / 'CMakeCache.txt'
        cache = cache_path.read_text()
        assert 'CMAKE_BUILD_TYPE:STRING=Debug' in cache
        assert any(line.startswith('ENABLE_SANITIZERS:') and line.endswith('=address') for line in cache.splitlines())
        assert any(line.startswith('CMAKE_CXX_FLAGS:') and '-DENABLE_AOT=0' in line for line in cache.splitlines())
        commands_path = build / 'compile_commands.json'
        commands = json.loads(commands_path.read_text())
        actual = [row for row in commands if row.get('output')]
        pch = json.loads(subprocess.check_output(build_command + ['-t', 'compdb', 'pch'], cwd=SOURCE, text=True))
        for row in pch:
            row['arguments'] = shlex.split(row['command'])
        pch_file = build / 'pch/root-pch.h.hxx.pch'
        assert pch_file.is_file() and pch_file.stat().st_size > 0
        consumers = [row for row in actual if '-include-pch' in row['arguments']]
        assert pch and consumers
        for row in pch + consumers:
            args = row['arguments']
            assert all(flag in args for flag in ('-DENABLE_AOT=0', '-DBUN_DEBUG=1', '-DASSERT_ENABLED=1', '-fsanitize=address'))
        engine_commands_path = engine_build / 'compile_commands.json'
        engine_commands = json.loads(engine_commands_path.read_text())
        jsc = [row for row in engine_commands if '/JavaScriptCore/' in row['file'] and row['file'].endswith('.cpp')]
        assert jsc
        for row in jsc:
            args = row.get('arguments') or shlex.split(row['command'])
            assert '-DENABLE_AOT=0' in args and any(arg.startswith('-fsanitize=') and 'address' in arg.split('=', 1)[1].split(',') for arg in args)
        runtime = json.loads(subprocess.check_output(build_command + ['-p', 'JSON.stringify({revision:Bun.revision,webkit:process.versions.webkit,platform:process.platform,architecture:process.arch})'], cwd=SOURCE, text=True))
        assert runtime == {'revision': BUN, 'webkit': WEBKIT, 'platform': 'linux', 'architecture': 'x64'}
        (OUT / 'compile-flags.json').write_text(json.dumps({'bun_compile_commands': {'bytes': commands_path.stat().st_size, 'sha256': sha(commands_path)},
            'engine_compile_commands': {'bytes': engine_commands_path.stat().st_size, 'sha256': sha(engine_commands_path)},
            'engine_cache_sha256': sha(cache_path), 'pch_commands': pch,
            'pch_binary': {'bytes': pch_file.stat().st_size, 'sha256': sha(pch_file)},
            'bun_command_count': len(consumers), 'bun_sample': consumers[0], 'engine_command_count': len(jsc), 'engine_sample': jsc[0]}, indent=2) + '\n')
        proof.update(passed=True, runtime=runtime, compile_flags_sha256=sha(OUT / 'compile-flags.json'), testcases=len(cases), target_cases=[case.get('name') for case in targets],
                     junit_sha256=sha(xml), binary={'bytes': binary.stat().st_size, 'sha256': sha(binary)})
        (OUT / 'proof.json').write_text(json.dumps(proof, indent=2) + '\n')


if __name__ == '__main__':
    assert len(sys.argv) == 2
    main(sys.argv[1])
