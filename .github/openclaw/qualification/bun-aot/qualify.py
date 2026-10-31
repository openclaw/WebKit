#!/usr/bin/env python3
"""Qualify the pinned Bun AOT consumer against an exact local engine checkout."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import tarfile
import io
import tomllib
import time
from xml.etree import ElementTree

SOURCE = Path('/work/source')
ENGINE = Path('/work/engine')
OUT = Path('/work/aot-proof')
INPUTS = Path(__file__).resolve().parent
BUN = 'fd40ba44187c721ee023062fa153a6a27560e6b1'
WEBKIT = '5ec9ac8557722128588184ed9cf77347d9a30cf1'
PIPELINE = '7b573c05d0c52dffc67d4d25daf108bed5930cf2'
BUILD = SOURCE / 'build/aot-linux-arm64'
LIMIT = 128 * 1024**2
STEPS = []
START = time.monotonic()
DEADLINE = START + 270 * 60
ENV = {k: v for k, v in os.environ.items() if not any(t in k.upper() for t in ('TOKEN', 'PASSWORD', 'SECRET'))}
ENV.update(CI='true', BUN_WEBKIT_PATH=str(ENGINE))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], timeout=120).decode().strip()


def save():
    (OUT / 'proof.json').write_text(json.dumps({
        'passed': False, 'bun': BUN, 'webkit': WEBKIT, 'pipeline': PIPELINE,
        'steps': STEPS, 'seconds': time.monotonic() - START,
    }, indent=2) + '\n')


def run(name, command, seconds, env=None, expected=0):
    log = OUT / (name + '.log')
    started = time.monotonic()
    record = {'name': name, 'command': command, 'exitCode': None, 'timedOut': False}
    STEPS.append(record)
    save()
    with log.open('xb') as stream:
        proc = subprocess.Popen(command, cwd=SOURCE, env=env or ENV, stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while proc.poll() is None:
                if time.monotonic() >= min(started + seconds, DEADLINE):
                    record['timedOut'] = True
                    raise TimeoutError(name)
                if sum(p.stat().st_size for p in OUT.iterdir() if p.is_file()) > LIMIT:
                    raise RuntimeError('proof output exceeds 128 MiB')
                time.sleep(1)
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            stream.flush()
            record.update(exitCode=proc.returncode, seconds=time.monotonic() - started)
            save()
    assert proc.returncode == expected and not record['timedOut'], name
    assert log.stat().st_size <= LIMIT, name + ' oversized log'
    return log.read_text(errors='replace')


def source_state(adapted):
    assert git(SOURCE, 'rev-parse', 'HEAD') == BUN
    assert git(ENGINE, 'rev-parse', 'HEAD') == WEBKIT
    assert git(SOURCE, 'write-tree') == original_tree
    assert not git(ENGINE, 'diff', '--name-only', 'HEAD')
    changed = set(git(SOURCE, 'diff', '--no-renames', '--name-only', 'HEAD').splitlines())
    changed.update(git(SOURCE, 'ls-files', '--others', '--exclude-standard').splitlines())
    assert changed == (set(spec['files']) if adapted else set()), changed
    for name, identity in spec['files'].items():
        relative = Path(name)
        assert not relative.is_absolute() and '..' not in relative.parts and relative.parts[0] != '.git'
        path = SOURCE / relative
        indexed = git(SOURCE, 'ls-files', '-s', '--', name).split()
        if identity['base_blob'] is None:
            assert not indexed and identity['before'] is None, name
        else:
            assert indexed[:2] == [identity['mode'], identity['base_blob']], name
        expected = identity['after' if adapted else 'before']
        expected_blob = identity['adapted_blob' if adapted else 'base_blob']
        assert (expected is None) == (expected_blob is None), name
        if expected is None:
            assert not os.path.lexists(path), name
            continue
        metadata = path.lstat()
        assert stat.S_ISREG(metadata.st_mode), name
        assert ('100755' if metadata.st_mode & 0o111 else '100644') == identity['mode'], name
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected, name
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        assert blob == expected_blob, name


def restore_source():
    # The admitted index is untouched. Restore tracked preimages and remove only
    # exact candidate files proven absent from that index before this run.
    source_state(True)
    tracked = [name for name, identity in spec['files'].items() if identity['base_blob'] is not None]
    if tracked:
        run('restore-source', ['git', 'restore', '--source=' + BUN, '--worktree', '--', *tracked], 120)
    for name, identity in spec['files'].items():
        if identity['base_blob'] is None:
            (SOURCE / name).unlink()
    source_state(False)


def junit(path, expected=None, selected=None):
    cases = list(ElementTree.parse(path).iter('testcase'))
    if selected is not None:
        excluded = [case for case in cases if case.get('name') not in selected]
        assert all(case.find('skipped') is not None and
                   all(case.find(tag) is None for tag in ('failure', 'error')) for case in excluded)
        cases = [case for case in cases if case.get('name') in selected]
    assert cases and all(not any(c.find(tag) is not None for tag in ('skipped', 'failure', 'error')) for c in cases)
    names = [c.get('name') for c in cases]
    assert len(names) == len(set(names)) and all(names)
    if expected is not None:
        assert names == [expected], names
    return names


def prepare_source():
    # Preparation produces reviewable source bytes, never a qualified executable.
    source_state(True)
    inputs = {name: identity['after'] for name, identity in spec['files'].items()}
    lock_path = SOURCE / 'Cargo.lock'
    lock_before = lock_path.read_bytes()
    inputs.setdefault('Cargo.lock', hashlib.sha256(lock_before).hexdigest())
    rust_paths = [name for name, identity in spec['files'].items()
                  if name.endswith('.rs') and identity['after'] is not None]
    if rust_paths:
        run('prepare-rustfmt', ['rustup', 'run', 'nightly-2026-09-15', 'rustfmt',
            '--edition', '2024', '--config-path', 'rustfmt.toml', '--config', 'skip_children=true',
            '--', *rust_paths], 600)
    cache = str(BUILD / 'prep-tarballs')
    run('prepare-lolhtml', ['bun', 'scripts/build/fetch-cli.ts', 'dep', 'lolhtml', 'oven-sh/lol-html',
        '725ce499aa9b71e38b7a2d0a9fbb6d7294a4079e', str(SOURCE / 'vendor/lolhtml'), cache], 600)
    run('prepare-argon2', ['bun', 'scripts/build/fetch-cli.ts', 'dep', 'rust-argon2', 'sru-systems/rust-argon2',
        'ed81866f163f0c7026aa6fd8388adf37242eb32a', str(SOURCE / 'vendor/rust-argon2'), cache,
        str(SOURCE / 'patches/rust-argon2/legacy-low-memory.patch'),
        str(SOURCE / 'patches/rust-argon2/fallible-memory.patch')], 600)
    run('prepare-lockfile', ['cargo', '+nightly-2026-09-15', 'update', '--manifest-path', 'Cargo.toml', '-p', 'bun_aot'], 600)
    before, after = tomllib.loads(lock_before.decode()), tomllib.loads(lock_path.read_text())
    def packages(lock):
        return {(p['name'], p['version'], p.get('source')): p for p in lock['package']}
    old, current = packages(before), packages(after)
    assert old.keys() == current.keys(), 'lockfile package identities changed'
    assert {k: v for k, v in before.items() if k != 'package'} == {k: v for k, v in after.items() if k != 'package'}
    for key, package in old.items():
        if key[0] != 'bun_aot':
            assert current[key] == package, key
            continue
        assert {k: v for k, v in package.items() if k != 'dependencies'} == {k: v for k, v in current[key].items() if k != 'dependencies'}
        assert set(current[key]['dependencies']) == set(package['dependencies']) | {'bun_js_parser'}
    changed = set(git(SOURCE, 'diff', '--no-renames', '--name-only', 'HEAD').splitlines())
    changed.update(git(SOURCE, 'ls-files', '--others', '--exclude-standard').splitlines())
    assert changed <= set(spec['files']) | {'Cargo.lock'}, changed
    prepared = {}
    for name in [*rust_paths, 'Cargo.lock']:
        path = SOURCE / name
        assert stat.S_ISREG(path.lstat().st_mode) and not path.lstat().st_mode & 0o111, name
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest == inputs[name]:
            continue
        prepared[name] = dict(input_sha256=inputs[name], sha256=digest, bytes=len(data))
        if name not in spec['files']:
            indexed = git(SOURCE, 'ls-files', '-s', '--', name).split()
            assert indexed[0] == '100644'
            spec['files'][name] = dict(before=inputs[name], base_blob=indexed[1], mode='100644')
        spec['files'][name].update(after=digest,
            adapted_blob=hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest())
    source_state(True)
    archive = OUT / 'prepared-source.tar.gz'
    manifest = json.dumps({'patch_sha256': spec['patch_sha256'], 'files': prepared}, indent=2).encode() + b'\n'
    assert sum(entry['bytes'] for entry in prepared.values()) <= 32 * 1024**2
    with tarfile.open(archive, 'w:gz') as stream:
        for name, data in [('manifest.json', manifest), *[(name, (SOURCE / name).read_bytes()) for name in prepared]]:
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o644
            stream.addfile(info, io.BytesIO(data))
    assert archive.stat().st_size <= 16 * 1024**2
    restore_source()
    result = json.loads((OUT / 'proof.json').read_text())
    result.update(passed=False, prepared=True, preparation_files=prepared,
                  prepared_archive_sha256=sha(archive), patch_sha256=spec['patch_sha256'])
    (OUT / 'proof.json').write_text(json.dumps(result, indent=2) + '\n')


def target_icu():
    # Provisioner ICU70 serves LLVM, not this isolated target's ICU79.1 development inputs.
    directory = Path('/work/aot-icu')
    directory.mkdir()
    archive = directory / 'icu.tar.gz'
    upstream = 'e66916298091dd12469076fd854e135b03fb16ff'
    digest = '6646a34d74a096453fd9b33f797db6d1c24f49f0e978277046f8380379e0b815'
    url = 'https://github.com/oven-sh/WebKit/releases/download/autobuild-' + upstream + '/bun-webkit-linux-arm64.tar.gz'
    run('icu-download', ['curl', '--fail', '--location', '--retry', '3', '--max-time', '600',
                         '--output', str(archive), url], 660)
    assert archive.stat().st_size == 254968780 and sha(archive) == digest
    prefix = directory / 'root'
    libraries = {'lib/libicui18n.a', 'lib/libicuuc.a', 'lib/libicudata.a'}
    files = {}
    total = 0
    with tarfile.open(archive, 'r:gz') as stream:
        for member in stream:
            name = Path(member.name)
            assert not name.is_absolute() and '..' not in name.parts
            if not member.name.startswith('bun-webkit/'):
                continue
            relative = member.name.removeprefix('bun-webkit/')
            if relative not in libraries and not relative.startswith('include/unicode/'):
                continue
            if member.isdir():
                continue
            assert member.isfile() and relative not in files and len(files) < 512
            total += member.size
            assert total <= 512 * 1024**2
            path = prefix / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with stream.extractfile(member) as source, path.open('xb') as output:
                shutil.copyfileobj(source, output)
            files[relative] = {'bytes': path.stat().st_size, 'sha256': sha(path)}
    assert libraries <= files.keys() and 'include/unicode/utypes.h' in files
    version = (prefix / 'include/unicode/uvernum.h').read_text()
    assert re.search(r'^#define U_ICU_VERSION_MAJOR_NUM\s+79\s*$', version, re.M)
    assert re.search(r'^#define U_ICU_VERSION_MINOR_NUM\s+1\s*$', version, re.M)
    for relative in sorted(libraries):
        path = str(prefix / relative)
        members = subprocess.check_output(['llvm-ar', 't', path], timeout=60, text=True).splitlines()
        headers = run('icu-elf-' + Path(relative).stem, ['llvm-readelf', '--file-header', path], 60)
        machines = re.findall(r'^\s*Machine:\s*(\S+)\s*$', headers, re.M)
        assert members and len(machines) == len(members) and set(machines) == {'AArch64'}
    symbols = run('icu-data-symbols', ['llvm-nm', '--defined-only', str(prefix / 'lib/libicudata.a')], 60)
    for symbol in ('icudt79_dat', 'bun_icu_zstd_dict', 'bun_icu_zstd_dict_size'):
        assert re.search(r'\b[BDR]\s+' + symbol + r'\s*$', symbols, re.M), symbol
    receipt = {'upstream': upstream, 'asset_id': 693843702, 'archive_bytes': archive.stat().st_size,
               'archive_sha256': digest, 'version': '79.1', 'files': files}
    (OUT / 'icu.json').write_text(json.dumps(receipt, indent=2) + '\n')
    ENV['BUN_ICU_ROOT'] = str(prefix)
    return receipt


OUT.mkdir(exist_ok=True)
assert git(Path('/work/pipeline'), 'rev-parse', 'HEAD') == PIPELINE
spec = json.loads((INPUTS / 'source-adapter.json').read_text())
assert spec['bun'] == BUN and spec['webkit'] == WEBKIT
assert spec['files']
assert sha(INPUTS / 'candidate.patch') == spec['patch_sha256']
original_tree = git(SOURCE, 'rev-parse', 'HEAD^{tree}')
source_state(False)
save()
jsc = ENGINE / 'Source/JavaScriptCore'
baseline = ['bun', 'run', str(jsc / 'aot/ir/generator/index.ts'), '--schema', str(jsc / 'aot/ir/AOTSchema.def')]
for name in [jsc / 'aot', SOURCE / 'src/aot', jsc / 'b3/B3Limits.h', jsc / 'ffi/JSFFICallback.cpp',
             jsc / 'runtime/AbstractModuleRecord.cpp', SOURCE / 'src/bundler/aot/data_values.rs',
             SOURCE / 'src/runtime/cli/compile_command/reports.rs']:
    baseline += ['--check-uses', str(name)]
text = run('baseline-generator', baseline, 120, expected=1)
assert re.search(r'(?:unknown|unexpected|unrecognized) (?:option|argument)[^\n]*check-uses', text, re.I), text[-2000:]
source_state(False)
run('apply-adapter', ['git', 'apply', '--check', str(INPUTS / 'candidate.patch')], 120)
run('apply-adapter-write', ['git', 'apply', str(INPUTS / 'candidate.patch')], 120)
source_state(True)
if spec.get('prepare_only', False):
    prepare_source()
    raise SystemExit(0)
icu = target_icu()
build_command = ['bun', 'scripts/build.ts', '--profile=release-local', '--webkit=local',
                 '--webkit-version=' + WEBKIT, '--aot=on', '--ci=on', '--buildkite=off',
                 '--os=linux', '--arch=aarch64', '--abi=gnu', '--build-dir=build/aot-linux-arm64', '-j2']
run('configure', [*build_command, '--configure-only'], 600)
source_state(True)
run('generate-builtin-table', [*build_command, '--target=codegen/aot_builtin_table.json'], 600)
source_state(True)
run('build', build_command, 14400)
source_state(True)
binary = BUILD / 'bun'
table = BUILD / 'codegen/aot_builtin_table.json'
assert all(p.is_file() and os.access(p, os.X_OK) for p in (binary, BUILD / 'jsc', BUILD / 'testaot'))
assert table.stat().st_size > 0
identities = {name: sha(BUILD / name) for name in ['bun', 'jsc', 'testaot', 'codegen/aot_builtin_table.json', 'build.ninja']}
smoke = "if(new Intl.DisplayNames(['fr'],{type:'region'}).of('DE')!=='Allemagne')throw Error('ICU compressed region data');(typeof print==='function'?print:console.log)('ICU79.1 French region data passed')"
for name in ['bun', 'jsc']:
    assert run('icu-smoke-' + name, [str(BUILD / name), '-e', smoke], 60).strip() == 'ICU79.1 French region data passed'
rust_env = dict(ENV, BUN_CODEGEN_DIR=str(BUILD / 'codegen'), TESTAOT=str(BUILD / 'testaot'),
                CARGO_PROFILE_DEV_OPT_LEVEL='1', CARGO_BUILD_JOBS='2',
                CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_RUSTFLAGS='-Cforce-frame-pointers=yes')
rust_cases = [
    ('bun_sema_parser', 'analysis_fold', 'ordinary_run_await_branches_keep_test_effects'),
    ('bun_sema_parser', 'analysis_fold', 'build_only_conditions_leave_ordinary_run_await_live'),
    ('bun_aot', None, 'link::marks::tests::expected_result_keeps_its_layouts'),
    ('bun_aot', None, 'emit::tests::engine_prints_same_text'),
    ('bun_aot', None, 'modules::plan::tests::the_commonjs_files_of_a_graph_run_first'),
    ('bun_aot', None, 'modules::imports::tests::strict_import_survives_a_soft_typescript_re_export_of_the_same_name'),
    ('bun_aot', None, 'link::module_records::tests::missing_commonjs_re_export_preserves_alias_and_written_specifier'),
    ('bun_aot', None, 'ir::tests::property_keys::created_symbols_differ_by_module_and_call_number'),
    ('bun_aot', None, 'engine::used_features::tests::every_engine_cause_maps'),
    ('bun_aot', None, 'report::causes::tests::only_property_accesses_have_property_causes'),
    ('bun_aot', None, 'load::typed_packages::tests::one_rejected_file_is_compiled_from_the_installed_file'),
    ('bun_aot', None, 'builtins::table::tests::lookup::names_stored_by_native_code'),
    ('bun_aot', None, 'link::unused_records::tests::a_name_that_only_native_code_stores_stays_required'),
    ('bun_aot', None, 'link::unused_records::tests::an_optional_field_that_only_native_code_stores_is_never_written'),
    ('bun_aot', None, 'link::unused_records::tests::a_brand_that_nothing_stores_is_not_required'),
    ('bun_aot', None, 'builtins::runtime_uses::tests::language_lists_nothing_else'),
    ('bun_aot', None, 'builtins::runtime_uses::tests::function_of_other_platform_is_excluded'),
    ('bun_aot', None, 'builtins::runtime_uses::tests::program_that_can_have_a_method_for_the_host_to_print_with_gets_what_unseen_code_gets'),
    ('bun_aot', None, 'builtins::resolve::tests::symbol_lookups_retain_startup_code_only_when_the_host_can_use_them'),
    ('bun_aot', None, 'compile::tests::only_functions_of_loaded_files_are_registered'),
    ('bun_aot', None, 'compile::tests::startup_retention_falls_back_for_unseen_and_host_code'),
    ('bun_trim', None, 'decide::tests::dynamic_import_keeps_what_is_used_and_what_loads_files_from_disk'),
    ('bun_trim', None, 'decide::tests::dynamic_import_of_code_keeps_what_transpiles_and_interprets_a_file'),
]


def rust_result(text):
    assert len(re.findall(r'^test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured;', text, re.M)) == 1
    assert not re.search(r'^(?:FAIL|PANIC|SKIP)(?:[: ]|$)', text, re.M), 'Rust/engine contract was skipped or failed'


for index, (package, target, selector) in enumerate(rust_cases):
    command = ['cargo', '+nightly-2026-09-15', 'test', '--locked', '-p', package]
    command += ['--test', target] if target else ['--lib']
    text = run('rust-contract-' + str(index), [*command, selector, '--', '--exact', '--nocapture'],
               1800, env=rust_env)
    rust_result(text)
    source_state(True)
ir_files = {}
for index, selector in enumerate([
    'lower/coroutines/',
    'lower/functions/key-in-brackets-names-function.ts',
    'lower/functions/symbol-key-names-function.js',
    'lower/expected-results/',
    'lower/installed-types/rows-of-a-query-repository-types/main.ts',
    'lower/modules/required-names.ts',
    'lower/modules/es-module-imports-names-of-commonjs.mjs',
]):
    # The Rust runner permits an empty post-filter selection. Admit actual files first.
    files = sorted(str(path.relative_to(SOURCE)) for path in (SOURCE / 'test/aot/ir/lower').rglob('*')
                   if path.is_file() and selector in str(path.relative_to(SOURCE))
                   and not {'imports', 'node_modules'} & set(path.relative_to(SOURCE / 'test/aot/ir/lower').parts)
                   and path.name.endswith(('.ts', '.tsx', '.mts', '.cts', '.js', '.jsx', '.mjs', '.cjs'))
                   and not path.name.endswith(('.d.ts', '.d.mts', '.d.cts')))
    assert files, 'IR selector matched no test files: ' + selector
    ir_files[selector] = files
    text = run('ir-contract-' + str(index), ['cargo', '+nightly-2026-09-15', 'test', '--locked',
               '-p', 'bun_aot', '--test', 'ir_tests', 'lower', '--', '--exact', '--nocapture'],
               1800, env=dict(rust_env, AOT_IR_FILTER=selector, AOT_IR_JOBS='1'))
    rust_result(text)
    source_state(True)
internal_cases = {}
for name, file in [('build-contracts', 'build-aot-codegen-declared-outputs.test.ts'),
                   ('local-webkit-contracts', 'build-local-webkit.test.ts')]:
    xml = OUT / (name + '.xml')
    run(name, [str(binary), 'test', 'test/internal/' + file,
               '--reporter=junit', '--reporter-outfile=' + str(xml)], 600)
    internal_cases[file] = junit(xml)
    assert len(internal_cases[file]) >= 10
xml = OUT / 'callback-contracts.xml'
run('callback-contracts', [str(binary), 'test', 'test/internal/builtins-table/places-of-callbacks.test.ts',
                           '--reporter=junit', '--reporter-outfile=' + str(xml)], 600)
callback_cases = junit(xml)
assert set(callback_cases) == {
    'what a constructed callback sees as new.target is written as a place',
    'a bare name is no place',
    'a called function is told its `this` and its arguments',
    'a called function says what native code does afterwards',
} and len(callback_cases) == 4
internal_cases['builtins-table/places-of-callbacks.test.ts'] = callback_cases
realm_names = [
    'the table lists every own name of the global object but ShadowRealm, which a compiled program does not have',
    'the table lists every own name of the global object of an executable',
]
xml = OUT / 'realm-contracts.xml'
run('realm-contracts', [str(binary), 'test', 'test/aot/builtins/realm-agreement.test.ts',
                        '--test-name-pattern=^(?:' + '|'.join(re.escape(name) for name in realm_names) + ')$',
                        '--reporter=junit', '--reporter-outfile=' + str(xml)], 900)
realm_cases = junit(xml, selected=set(realm_names))
assert set(realm_cases) == set(realm_names) and len(realm_cases) == 2
internal_cases['aot/builtins/realm-agreement.test.ts'] = realm_cases
source_state(True)
cases = []
for part, name in [('calls-of-proxies', 'strict--empty--two'), ('calls-of-proxies', 'strict--trap--method'),
                   ('builtin-modules', 'async-local-storage-get-store'),
                   ('errors', 'names-in-frames-of-async-functions-that-never-reach-their-await'),
                   ('async-and-generators', 'what-the-names-of-the-parameters-of-a-suspended-function-hold'),
                   ('errors', 'functions-declared-under-a-constant-key-in-brackets-show-the-key-as-their-name'),
                   ('parsed-records', 'nested-objects-and-arrays'),
                   ('builtin-modules', 'sqlite-in-memory-with-no-optional-pass'),
                   ('modules', 'names-known-at-link'),
                   ('symbol-fields', 'two-symbols-with-one-description'),
                   ('symbol-fields', 'one-place-in-the-text-makes-several-symbols')]:
    expected = part + '/' + name
    case_env = dict(ENV, TEST_PART='aot/' + part, AOT_PROGRAMS=expected, AOT_SHARE='all',
                    AOT_PROGRAMS_JOBS='1', AOT_BUILTIN_TABLE=str(table))
    xml = OUT / (name + '.xml')
    text = run(name, [str(binary), 'test', 'test/aot/parts.test.ts', '--reporter=junit',
                      '--reporter-outfile=' + str(xml)], 600, env=case_env)
    assert not re.search(r'(?:SKIPPED:|TODO:|SHARE:|NOT THROUGH:)', text), expected
    cases += junit(xml, expected)
    source_state(True)
startup_names = [
    'console.write',
    'process.stdout and process.stderr',
    'a tick that native code queues',
    'a warning from native code',
    'a message with buffers that only arrives',
    'require of a file',
    'a custom inspector in what nobody catches',
    "a host object's own inspector, found by reflection",
]
xml = OUT / 'startup-builtins.xml'
startup_env = dict(ENV, AOT_PROGRAMS_JOBS='1', AOT_SHARE='all', AOT_PROGRAMS='',
                   AOT_BUILTIN_TABLE=str(table))
text = run('startup-builtins', [str(binary), 'test', 'test/aot/built-in-functions-by-use.test.ts',
           '--test-name-pattern=(?:' + '|'.join(re.escape(name) for name in startup_names) + ')$',
           '--reporter=junit', '--reporter-outfile=' + str(xml)], 1800, env=startup_env)
assert not re.search(r'(?:SKIPPED:|TODO:|SHARE:|NOT THROUGH:)', text), 'startup native program skipped'
startup_cases = junit(xml, selected=set(startup_names))
assert set(startup_cases) == set(startup_names) and len(startup_cases) == 8
internal_cases['aot/built-in-functions-by-use.test.ts'] = startup_cases
source_state(True)
restore_source()
assert identities == {name: sha(BUILD / name) for name in identities}
result = json.loads((OUT / 'proof.json').read_text())
result.update(passed=True, binary_sha256=identities, program_cases=cases, build_contract_cases=internal_cases,
              rust_contract_cases=rust_cases, ir_contract_files=ir_files,
              patch_sha256=spec['patch_sha256'], source_tree=original_tree, icu=icu)
(OUT / 'proof.json').write_text(json.dumps(result, indent=2) + '\n')
