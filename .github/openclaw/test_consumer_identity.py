import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from qualification import consumer_identity as consumer, compile_cache, harness_adapters as harness
import xml.etree.ElementTree as ET



def seed_build_tools(root, arm, record):
    """Synthetic fixed-command provenance; no build is executed by these fixtures."""
    cwd = Path('/fixture') / ('bun-baseline' if arm == 'baseline' else 'bun')
    before = {'index_tree': consumer.CONFIG[arm]['tree'], 'other_patch_sha256':
              record['tracked_patch_sha256'] if arm == 'baseline' else record['overlay']['patch_sha256']}
    tools = {'schema_version': 1, 'arm': arm, 'phase': 'build', 'source': consumer.CONFIG[arm],
             'adapter': consumer.adapter_spec(arm, 'build'), 'restored': True, 'status': 0,
             'before': before, 'after': before, 'compiled_inputs_sha256': '1'*64,
             'engine_source': record['runtime']['webkit'], 'executable': record['executable'],
             'cwd': str(cwd), 'argv': ['/fixture/bootstrap-bun', 'run', 'build:release', '--lto=off',
             '--webkit-version='+record['runtime']['webkit'], '--buildDir='+str(cwd/'build'/('qualify-'+arm)), '--timings'],
             'bootstrap': {'path': '/fixture/bootstrap-bun', 'size': 1, 'sha256': '2'*64}}
    path = arm+'-build-tools.json'
    consumer.write_once(root/path, tools)
    record['build_tools'] = consumer.file_record(root, path)


def seed_consumer(root, arm):
    pin = consumer.CONFIG[arm]
    executable = consumer.BASELINE_EXECUTABLE if arm == 'baseline' else consumer.EXECUTABLE
    record = {'executable': {'path': executable, 'size': 1, 'sha256': '3'*64},
              'runtime': {'bun_revision': pin['commit'], 'webkit': pin.get('engine', 'e'*40),
                          'platform': 'linux', 'architecture': 'x64'}}
    if arm == 'baseline':
        record.update(source=pin, tracked_patch_sha256='4'*64)
    else:
        record.update(schema_version=1, candidate={'repository': consumer.CONFIG['bun_repository'],
            'commit': pin['commit'], 'tree': pin['tree'], 'index_tree': pin['tree']},
            engine={'source': 'e'*40, 'lane': consumer.LANE, 'archive':
            {'path': consumer.LANE+'.tar.gz', 'size': 1, 'sha256': '5'*64}, 'lane_manifest_sha256': '6'*64},
            overlay={'path': consumer.MANIFEST, 'base_blob': pin['manifest_blob'], 'sha256': '7'*64,
                     'patch_sha256': '4'*64, 'tracked_changed_paths': [consumer.MANIFEST]},
            fixture={'path': consumer.FIXTURE, 'size': 1, 'sha256': consumer.FIXTURE_SHA256},
            baseline=consumer.CONFIG['baseline'])
    seed_build_tools(root, arm, record)
    consumer.write_once(root/(arm+'-identity.json'), record)
    return record


def write_invocation(root, name, records):
    """Bind real fixture files so tests can distinguish byte custody from validation."""
    arm = 'baseline' if name == 'baseline' else 'candidate'
    identity_path = root/(arm+'-identity.json')
    record = json.loads(identity_path.read_text()) if identity_path.exists() else seed_consumer(root, arm)
    directory = root/name; directory.mkdir(exist_ok=True)
    for filename, value in records.items():
        (directory/filename).write_text(json.dumps(value))
    selected = records['selected.json']
    if arm == 'candidate' and 'test/js/node/net/node-net.test.ts' in selected:
        runtime = record['runtime']
        (directory/'net-direct.json').write_text(json.dumps({'testPath': 'test/js/node/net/node-net.test.ts',
            'revision': runtime['bun_revision'], 'webkit': runtime['webkit'], 'platform': runtime['platform'],
            'arch': runtime['architecture'], 'exitCode': 0, 'signalCode': None, 'error': None}))
    before = {'index_tree': consumer.CONFIG[arm]['tree'], 'other_patch_sha256':
              record['tracked_patch_sha256'] if arm == 'baseline' else record['overlay']['patch_sha256']}
    cwd = Path('/fixture')/('bun-baseline' if arm == 'baseline' else 'bun')
    argv = [str(cwd/'build'/('qualify-'+arm)/'bun'), 'scripts/openclaw-ci/tests.ts', 'test']
    if name == 'sync': argv += ['--junit-prefix', 'openclaw-sync-junit-'+'1'*32+'-']
    invocation = {'schema_version': 1, 'phase': 'test', 'arm': arm, 'source': consumer.CONFIG[arm],
                  'adapter': consumer.adapter_spec(arm, 'test'), 'restored': True, 'before': before, 'after': before,
                  'compiled_inputs_sha256': '1'*64, 'cwd': str(cwd), 'argv': argv,
                  'identity': consumer.file_record(root, arm+'-identity.json'), 'executable': record['executable'],
                  'selection': consumer.file_record(root, name+'/selected.json'), 'evidence': {}}
    for filename in ('results.json', 'runner-terminal.json', 'wrapper-terminal.json', 'net-direct.json'):
        invocation['evidence'][filename] = consumer.file_record(root, name+'/'+filename) if (directory/filename).is_file() else None
    (directory/'invocation.json').write_text(json.dumps(invocation))
    return invocation


def release_fixture(inputs, source):
    """Complete distinct proof/binary artifact roots, without executing fixture bytes."""
    proof=inputs/'qualification';binaries=inputs/'linux-bun-executables'
    lane=inputs/consumer.LANE
    engine=consumer.engine_input(lane/(consumer.LANE+'.tar.gz'),lane/(consumer.LANE+'.manifest.json'),source)
    for path,data in [(consumer.EXECUTABLE,b'candidate'),(consumer.BASELINE_EXECUTABLE,b'baseline'),
                      (consumer.FIXTURE,(consumer.INPUTS/'worker-resource-limits.test.ts').read_bytes())]:
        file=binaries/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(data)
    overlay=proof/'candidate-input/artifacts.json';overlay.parent.mkdir();overlay.write_text(json.dumps(consumer.overlay_manifest(engine)))
    (proof/'candidate-manifest.patch').write_bytes(b'candidate overlay patch\n')
    (proof/'baseline-adapters.patch').write_bytes(b'baseline recorded patch\n')
    pin=consumer.CONFIG['candidate']
    identity={'schema_version':1,'candidate':{'repository':consumer.CONFIG['bun_repository'],'commit':pin['commit'],'tree':pin['tree'],'index_tree':pin['tree']},
        'engine':engine,'overlay':{'path':consumer.MANIFEST,'base_blob':pin['manifest_blob'],'sha256':consumer.sha(overlay),
        'patch_sha256':consumer.sha(proof/'candidate-manifest.patch'),'tracked_changed_paths':[consumer.MANIFEST]},
        'executable':consumer.file_record(binaries,consumer.EXECUTABLE),'fixture':consumer.file_record(binaries,consumer.FIXTURE),
        'runtime':{'bun_revision':pin['commit'],'webkit':source,'platform':'linux','architecture':'x64'},'baseline':consumer.CONFIG['baseline']}
    baseline={'source':consumer.CONFIG['baseline'],'tracked_patch_sha256':consumer.sha(proof/'baseline-adapters.patch'),
        'executable':consumer.file_record(binaries,consumer.BASELINE_EXECUTABLE),
        'runtime':{'bun_revision':consumer.CONFIG['baseline']['commit'],'webkit':consumer.CONFIG['baseline']['engine'],'platform':'linux','architecture':'x64'}}
    seed_build_tools(proof,'candidate',identity);seed_build_tools(proof,'baseline',baseline)
    consumer.write_once(proof/'candidate-identity.json',identity);consumer.write_once(proof/'baseline-identity.json',baseline)
    digest=consumer.sha(proof/'candidate-identity.json')
    report=proof/'sync/module-junit.xml';report.parent.mkdir()
    suites=ET.Element('testsuites');suite=ET.SubElement(suites,'testsuite',name=compile_cache.MODULE)
    for classname,name in compile_cache.CASES:
        ET.SubElement(suite,'testcase',classname=classname,name=name,file=compile_cache.MODULE)
    ET.ElementTree(suites).write(report,encoding='utf-8',xml_declaration=True)
    from test_compare_fork_ci import evidence
    from qualification import compare_fork_ci as comparison
    for name in ('baseline','candidate'):write_invocation(proof,name,evidence())
    historical=set(json.loads((consumer.INPUTS/'selected.json').read_text()))|set(json.loads((consumer.INPUTS/'sync/selected.json').read_text()))
    selected=historical|{'test/js/web/atomics.test.ts','test/js/bun/wasm/compile-rss.test.ts'}
    for index in range(85-len(selected)):selected.add('test/fixture-added-'+str(index)+'.test.ts')
    write_invocation(proof,'sync',evidence(selected=sorted(selected)))
    (proof/'faithfulness.json').write_text(json.dumps(comparison.compare(proof/'baseline',proof/'candidate')))
    gate={'passed':True,'source':source,'comparison':'bun-plus-engine-upgrade','selected_files':44,'result_files':46,
        'comparison_policy':comparison.POLICY,'faithfulness_sha256':consumer.sha(proof/'faithfulness.json'),
        'candidate_identity_sha256':digest,'baseline_identity_sha256':consumer.sha(proof/'baseline-identity.json'),
        'upstream_sync':{'passed':True,'source':source,'candidate_identity_sha256':digest,'historical_selected_files':82,'selected_files':85,'result_rows':87,'regressions':0,'compile_cache':compile_cache.evidence(report),'invocation':consumer.file_record(proof,'sync/invocation.json')},
        'engine':{'passed':True,'source':source},'compatibility':{'passed':True,'source':source,'candidate_identity_sha256':digest,'memory_tests':3,'startup':True}}
    (proof/'gate.json').write_text(json.dumps(gate))


class ConsumerIdentity(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.repo=self.root/'bun';self.repo.mkdir()
        env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_SYSTEM='/dev/null',
            GIT_AUTHOR_NAME='Fixture',GIT_AUTHOR_EMAIL='fixture@example.invalid',GIT_COMMITTER_NAME='Fixture',
            GIT_COMMITTER_EMAIL='fixture@example.invalid',GIT_AUTHOR_DATE='2026-01-01T00:00:00Z',GIT_COMMITTER_DATE='2026-01-01T00:00:00Z')
        self.environment=patch.dict(os.environ,env,clear=True);self.environment.start();self.addCleanup(self.environment.stop)
        self.git('init','--quiet','--object-format=sha1')
        manifest=self.repo/consumer.MANIFEST;manifest.parent.mkdir(parents=True);manifest.write_text('{}\n')
        (self.repo/'source.js').write_text('original\n');(self.repo/'.gitignore').write_text('/build/\n')
        generated=self.repo/'src/string-map.generated.rs';generated.parent.mkdir();generated.write_text('tracked generated source\n')
        native=self.repo/'src/runtime/cli/main.cpp';native.parent.mkdir(parents=True);native.write_text('tracked native source\n')
        for name,target in {
            'src/cli':'runtime/cli', 'src/chain':'cli', 'src/parent':'../src/runtime/cli',
            'alias-file.cpp':'src/runtime/cli/main.cpp', 'chain-file.cpp':'alias-file.cpp',
            'tracked-to-untracked.cpp':'untracked.cpp', 'src/tracked-via-untracked':'untracked-alias',
            'tracked-intermediate.cpp':'src/untracked-alias/main.cpp',
            'escape.cpp':'../outside.cpp', 'dangling.cpp':'missing.cpp',
            'cyclic-a.cpp':'cyclic-b.cpp', 'cyclic-b.cpp':'cyclic-a.cpp',
        }.items():(self.repo/name).symlink_to(target)
        self.git('add','.');self.git('-c','commit.gpgsign=false','commit','--quiet','-m','fixture')
        commit=self.git('rev-parse','HEAD').strip();tree=self.git('rev-parse','HEAD^{tree}').strip();blob=self.git('rev-parse','HEAD:'+consumer.MANIFEST).strip()
        config={**consumer.CONFIG,'candidate':{'commit':commit,'tree':tree,'manifest_blob':blob}}
        self.config=patch.object(consumer,'CONFIG',config);self.config.start();self.addCleanup(self.config.stop)
        adapters=copy.deepcopy(consumer.ADAPTERS);adapters['arms']['candidate']['pin']=commit
        self.adapters=patch.object(consumer,'ADAPTERS',adapters);self.adapters.start();self.addCleanup(self.adapters.stop)
        self.source='e'*40;self.artifacts=self.root/'artifacts';self.artifacts.mkdir()
        self.archive=self.artifacts/(consumer.LANE+'.tar.gz');self.archive.write_bytes(b'engine archive')
        self.lane_manifest=self.artifacts/(consumer.LANE+'.manifest.json')
        self.lane_manifest.write_text(json.dumps({'source':self.source,'lane':{'label':consumer.LANE},
            'files':{self.archive.name:{'sha256':consumer.sha(self.archive),'size':self.archive.stat().st_size}}}))
        self.engine=consumer.engine_input(self.archive,self.lane_manifest,self.source)
        manifest.write_text(json.dumps(consumer.overlay_manifest(self.engine),indent=2)+'\n')
        self.runtime={'bun_revision':commit,'webkit':self.source,'platform':'linux','architecture':'x64'}
        self.binary=self.root/consumer.EXECUTABLE;self.binary.parent.mkdir(parents=True)
        self.write_binary(self.runtime)
        fixture=self.root/consumer.FIXTURE;fixture.parent.mkdir(parents=True);shutil.copyfile(consumer.INPUTS/'worker-resource-limits.test.ts',fixture)
        self.receipt=self.root/'candidate-identity.json'
        self.inspector=Path(sys.executable).resolve()
        self.inventory=['source.js','src/string-map.generated.rs']
        self.discovery=patch.object(consumer,'discover_build_inputs',side_effect=lambda repo,runtime:[str(repo/path) for path in self.inventory])
        self.discover_mock=self.discovery.start();self.addCleanup(self.discovery.stop)
        _,overlay=consumer.source_identity(self.repo,self.engine,self.inspector)
        seed_build_tools(self.root,'candidate',{'executable':consumer.file_record(self.root,consumer.EXECUTABLE),
            'runtime':self.runtime,'overlay':overlay})

    def git(self,*args):
        return subprocess.check_output(['git','-c','gc.auto=0','-c','maintenance.auto=false','-C',str(self.repo),*args],text=True)

    def write_binary(self,runtime):
        self.binary.write_text('#!/usr/bin/env python3\nimport os\nassert not any(k in os.environ for k in '+repr(consumer.BUILD_ENV)+')\nprint('+repr(json.dumps(runtime))+')\n')
        self.binary.chmod(0o755)

    def record(self):
        record=consumer.capture(self.root,self.engine,self.inspector);consumer.write_once(self.receipt,record);return record

    def test_measured_receipt_written_once_and_reused(self):
        record=self.record()
        self.assertEqual(consumer.verify(self.root,self.engine,self.receipt,self.inspector),record)
        self.assertEqual(record['overlay']['patch_sha256'],__import__('hashlib').sha256(consumer.git(self.repo,'diff','--binary','HEAD','--',consumer.MANIFEST)).hexdigest())
        with self.assertRaises(FileExistsError):consumer.write_once(self.receipt,record)

    def test_wrong_checkout_commit_or_tree_rejected(self):
        for key in ['commit','tree','manifest_blob']:
            with self.subTest(key=key),patch.dict(consumer.CONFIG['candidate'],{key:'f'*40}):
                with self.assertRaises(ValueError):consumer.capture(self.root,self.engine,self.inspector)

    def test_index_and_extra_tracked_changes_rejected(self):
        (self.repo/'source.js').write_text('changed\n')
        with self.assertRaises(ValueError):consumer.capture(self.root,self.engine,self.inspector)
        self.git('add','source.js')
        with self.assertRaises(ValueError):consumer.capture(self.root,self.engine,self.inspector)

    def test_staged_manifest_rejected(self):
        self.git('add',consumer.MANIFEST)
        with self.assertRaises(ValueError):consumer.capture(self.root,self.engine,self.inspector)

    def test_runtime_identity_is_measured(self):
        for key,value in [('bun_revision','f'*40),('webkit','f'*40),('platform','darwin'),('architecture','arm64')]:
            with self.subTest(key=key):
                self.write_binary({**self.runtime,key:value})
                with self.assertRaises(ValueError):consumer.capture(self.root,self.engine,self.inspector)

    def test_build_only_overrides_removed_for_measurement(self):
        with patch.dict(os.environ,{key:'fixture-build-only' for key in consumer.BUILD_ENV}):
            self.assertEqual(consumer.capture(self.root,self.engine,self.inspector)['runtime'],self.runtime)

    def test_binary_fixture_and_overlay_tampering_rejected(self):
        self.record()
        for path in [self.binary,self.root/consumer.FIXTURE,self.repo/consumer.MANIFEST]:
            original=path.read_bytes()
            with self.subTest(path=str(path.relative_to(self.root))):
                path.write_bytes(original+b'\n')
                with self.assertRaises(ValueError):consumer.verify(self.root,self.engine,self.receipt,self.inspector)
                path.write_bytes(original)

    def test_fixture_must_remain_outside_compiled_index(self):
        self.git('add',str(Path(consumer.FIXTURE).relative_to('bun')))
        with self.assertRaises(ValueError):consumer.capture(self.root,self.engine,self.inspector)

    def test_archive_and_lane_manifest_mismatch_rejected(self):
        self.archive.write_bytes(b'wrong engine')
        with self.assertRaises(ValueError):consumer.engine_input(self.archive,self.lane_manifest,self.source)
        record=consumer.capture(self.root,self.engine,self.inspector)
        wrong=copy.deepcopy(self.engine);wrong['archive']['sha256']='f'*64
        with self.assertRaises(ValueError):consumer.validate(record,self.source,wrong)

    def test_stale_receipt_rejected(self):
        record=self.record();record['overlay']['patch_sha256']='f'*64;self.receipt.write_text(json.dumps(record))
        with self.assertRaises(ValueError):consumer.verify(self.root,self.engine,self.receipt,self.inspector)

    def test_receipt_rejects_wrong_pins_extra_paths_and_fixture(self):
        record=consumer.capture(self.root,self.engine,self.inspector)
        for section,key,value in [('candidate','commit','f'*40),('candidate','tree','f'*40),('candidate','index_tree','f'*40),
            ('overlay','tracked_changed_paths',[consumer.MANIFEST,'source.js']),('fixture','sha256','f'*64),
            ('runtime','webkit','f'*40),('runtime','bun_revision','f'*40)]:
            with self.subTest(section=section,key=key):
                changed=copy.deepcopy(record);changed[section][key]=value
                with self.assertRaises(ValueError):consumer.validate(changed,self.source)

    def test_staging_uses_only_measured_lane_and_rejects_wrong_source_before_output(self):
        command=[sys.executable,str(consumer.INPUTS/'stage-sync-artifact.py'),str(self.archive),'--lane-manifest',str(self.lane_manifest),'--version',self.source]
        output=self.root/'staged';subprocess.run([*command,'--output',str(output)],check=True,capture_output=True)
        self.assertEqual(json.loads((output/'artifacts.json').read_text()),consumer.overlay_manifest(self.engine))
        self.assertEqual((output/'prefetch/by-sha256'/self.engine['archive']['sha256']).read_bytes(),self.archive.read_bytes())
        bad=self.root/'wrong';command[-1]='f'*40
        result=subprocess.run([*command,'--output',str(bad)],capture_output=True)
        self.assertNotEqual(result.returncode,0);self.assertFalse(bad.exists())


    @contextmanager
    def source_arm(self, arm):
        if arm=='candidate':
            yield lambda:consumer.source_identity(self.repo,self.engine,self.inspector)
            return
        original=self.repo;self.repo=self.root/'bun-baseline';original.rename(self.repo)
        pin=consumer.CONFIG['candidate']
        (self.root/'baseline-adapters.patch').write_bytes(consumer.git(self.repo,'diff','--binary','HEAD'))
        try:
            with patch.dict(consumer.CONFIG,{'baseline':{**consumer.CONFIG['baseline'],'commit':pin['commit'],'tree':pin['tree']}}),patch.object(consumer,'baseline_inputs'):
                yield lambda:consumer.baseline_source(self.root,self.inspector)
        finally:self.repo.rename(original);self.repo=original

    def test_both_arms_reject_untracked_and_ignored_consumed_inputs(self):
        for arm in ['candidate','baseline']:
            for path,ignored in [('src/jsc/bindings/unreviewed.cpp',False),('src/jsc/bindings/unreviewed.cpp',True),('src/js/rogue.generated.ts',True)]:
                with self.subTest(arm=arm,path=path,ignored=ignored),self.source_arm(arm) as check:
                    file=self.repo/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('unreviewed source\n')
                    exclude=self.repo/'.git/info/exclude';original=exclude.read_text()
                    if ignored:exclude.write_text(original+'\n'+path+'\n')
                    self.inventory.append(path)
                    try:
                        with self.assertRaisesRegex(ValueError,'untracked build input'):check()
                    finally:self.inventory.pop();file.unlink();exclude.write_text(original)

    def test_both_arms_accept_outputs_excluded_by_actual_inventory(self):
        for arm in ['candidate','baseline']:
            with self.subTest(arm=arm),self.source_arm(arm) as check:
                paths=['src/runtime/bake/generated.ts','build/codegen/generated.cpp','node_modules/dependency/index.js']
                for path in paths:
                    file=self.repo/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('output\n')
                try:check()
                finally:
                    for path in paths:(self.repo/path).unlink()

    def test_both_arms_reject_tracked_generated_source_before_discovery(self):
        for arm in ['candidate','baseline']:
            with self.subTest(arm=arm),self.source_arm(arm) as check:
                file=self.repo/'src/string-map.generated.rs';original=file.read_text();file.write_text('altered\n')
                self.discover_mock.reset_mock()
                try:
                    with self.assertRaises(ValueError):check()
                    self.discover_mock.assert_not_called()
                finally:file.write_text(original)

    def test_inventory_failures_and_malformed_paths_fail_closed(self):
        outside=self.root/'outside.cpp';outside.write_text('outside\n')
        for arm in ['candidate','baseline']:
            with self.source_arm(arm) as check:
                for value in [{},[],[None],['source.js'],[str(outside)], [str(self.repo/'missing.cpp')]]:
                    with self.subTest(arm=arm,value=value),patch.object(consumer,'discover_build_inputs',return_value=value):
                        with self.assertRaises(ValueError):check()
                with patch.object(consumer,'discover_build_inputs',side_effect=subprocess.CalledProcessError(1,['inspector'])):
                    with self.assertRaises(subprocess.CalledProcessError):check()

    def test_both_arms_accept_tracked_aliases_and_chains(self):
        paths=['src/cli/main.cpp','src/chain/main.cpp','src/parent/main.cpp','alias-file.cpp','chain-file.cpp']
        for arm in ['candidate','baseline']:
            with self.subTest(arm=arm),self.source_arm(arm) as check:
                with patch.object(consumer,'discover_build_inputs',return_value=[str(self.repo/path) for path in paths]):check()

    def test_both_arms_reject_untracked_aliases_and_targets(self):
        for arm in ['candidate','baseline']:
            with self.source_arm(arm) as check:
                (self.repo/'untracked.cpp').write_text('untracked source\n')
                (self.repo/'untracked-alias.cpp').symlink_to('source.js')
                (self.repo/'src/untracked-alias').symlink_to('runtime/cli')
                try:
                    for path in ['untracked-alias.cpp','tracked-to-untracked.cpp','src/tracked-via-untracked/main.cpp','tracked-intermediate.cpp']:
                        with self.subTest(arm=arm,path=path),patch.object(consumer,'discover_build_inputs',return_value=[str(self.repo/path)]):
                            with self.assertRaisesRegex(ValueError,'untracked build input'):check()
                finally:
                    for path in ['untracked.cpp','untracked-alias.cpp','src/untracked-alias']:(self.repo/path).unlink()

    def test_both_arms_reject_changed_tracked_alias_before_discovery(self):
        for arm in ['candidate','baseline']:
            with self.subTest(arm=arm),self.source_arm(arm) as check:
                link=self.repo/'alias-file.cpp';target=os.readlink(link);link.unlink();link.symlink_to('source.js')
                self.discover_mock.reset_mock()
                try:
                    with self.assertRaises(ValueError):check()
                    self.discover_mock.assert_not_called()
                finally:link.unlink();link.symlink_to(target)

    def test_both_arms_reject_dangling_cyclic_and_escaping_aliases(self):
        outside=self.root/'outside.cpp';outside.write_text('outside\n')
        for arm in ['candidate','baseline']:
            with self.source_arm(arm) as check:
                for path,message in [('escape.cpp','escapes checkout'),('dangling.cpp','invalid build source path'),('cyclic-a.cpp','cyclic build source alias')]:
                    with self.subTest(arm=arm,path=path),patch.object(consumer,'discover_build_inputs',return_value=[str(self.repo/path)]):
                        with self.assertRaisesRegex(ValueError,message):check()

    def test_discovery_uses_absolute_inspector_and_frozen_module(self):
        self.discovery.stop()
        with patch.object(consumer.subprocess,'check_output',return_value=b'[]') as run:
            self.assertEqual(consumer.discover_build_inputs(self.repo,self.inspector),[])
            args=run.call_args.args[0]
            self.assertEqual(args[0],str(self.inspector));self.assertEqual(args[-1],(self.repo.resolve()/'scripts/glob-sources.ts').as_uri())
            self.assertIn('globAllSources',args[2]);self.assertEqual(run.call_args.kwargs['cwd'],self.repo)
        with patch.object(consumer.subprocess,'check_output',return_value=b'not JSON'):
            with self.assertRaises(ValueError):consumer.discover_build_inputs(self.repo,self.inspector)
        with self.assertRaisesRegex(ValueError,'absolute source inspector'):
            consumer.discover_build_inputs(self.repo,Path('bun'))



class HarnessAdapters(unittest.TestCase):
    git = ConsumerIdentity.git
    write_binary = ConsumerIdentity.write_binary

    def setUp(self):
        previous_mask=os.umask(0o022)  # Match qualify.sh while Git recreates adapted files.
        self.addCleanup(os.umask,previous_mask)
        ConsumerIdentity.setUp(self)
        self.file=self.repo/'harness.js';self.file.write_text('original harness\n')
        self.git('add','harness.js');self.git('-c','commit.gpgsign=false','commit','--quiet','-m','harness fixture')
        pin=consumer.CONFIG['candidate'];pin.update(commit=self.git('rev-parse','HEAD').strip(),tree=self.git('rev-parse','HEAD^{tree}').strip())
        self.runtime['bun_revision']=pin['commit'];self.write_binary(self.runtime)
        before=consumer.sha(self.file);self.file.write_text('adapted harness\n');after=consumer.sha(self.file)
        self.adapter=self.root/'harness.patch';self.adapter.write_bytes(consumer.git(self.repo,'diff','--binary','HEAD','--','harness.js'))
        self.file.write_text('original harness\n')
        spec={'patch':str(self.adapter),'sha256':consumer.sha(self.adapter),
              'files':{'harness.js':{'before':before,'after':after,'mode':'100644'}}}
        consumer.ADAPTERS['arms']['candidate']={'pin':pin['commit'],'build':spec,'test':spec}
        (self.root/'candidate-build-tools.json').unlink()
        _,overlay=consumer.source_identity(self.repo,self.engine,self.inspector)
        seed_build_tools(self.root,'candidate',{'executable':consumer.file_record(self.root,consumer.EXECUTABLE),
            'runtime':self.runtime,'overlay':overlay})
        consumer.write_once(self.receipt,consumer.capture(self.root,self.engine,self.inspector))
        directory=self.root/'candidate';directory.mkdir()
        for name in ('home','tmp','bin'):(directory/name).mkdir()
        self.raw=self.repo/'build/openclaw-ci';self.raw.mkdir(parents=True)
        for path in (self.raw/'selected.json',directory/'selected.json'):path.write_text('["test/fixture.test.ts"]')
        self.final=directory/'invocation.json';self.pending=directory/'invocation.pending.json'
        self.calls=[];self.child=None;self.real_run=subprocess.run
        def dispatch(argv,*args,**kwargs):
            if len(argv)>1 and argv[1] in ('scripts/openclaw-ci/tests.ts','run'):
                self.calls.append((list(argv),kwargs))
                if self.child:return self.child(argv,kwargs)
                if argv[1]=='scripts/openclaw-ci/tests.ts':
                    (self.raw/'results.json').write_text('[]')
                    (self.raw/'runner-terminal.json').write_text('{"status":0,"signal":null,"spawnError":false}')
                return subprocess.CompletedProcess(argv,0)
            return self.real_run(argv,*args,**kwargs)
        self.dispatch=dispatch

    def run_owner(self,phase='test'):
        with patch.object(harness.subprocess,'run',side_effect=self.dispatch):
            return harness.run(self.root,'candidate',phase,self.engine,self.inspector)

    def assert_restored(self,final=False,pending=False):
        self.assertEqual(self.file.read_text(),'original harness\n')
        consumer.source_identity(self.repo,self.engine,self.inspector)
        self.assertEqual(self.final.exists(),final);self.assertEqual(self.pending.exists(),pending)

    def test_fixed_test_command_environment_and_immutable_receipt(self):
        with patch.dict(os.environ,{key:'build-only' for key in consumer.BUILD_ENV}):
            self.assertEqual(self.run_owner(),0)
            for key in consumer.BUILD_ENV:self.assertEqual(os.environ[key],'build-only')
        self.assert_restored(final=True)
        argv,options=self.calls[0]
        self.assertEqual(argv,[str(self.binary),'scripts/openclaw-ci/tests.ts','test'])
        self.assertEqual(options['cwd'],self.repo)
        self.assertFalse(any(key in options['env'] for key in consumer.BUILD_ENV))
        self.assertEqual(options['env']['HOME'],str(self.root/'candidate/home'))
        self.assertEqual(options['env']['TMPDIR'],str(self.root/'candidate/tmp'))
        record=json.loads(self.final.read_text())
        self.assertEqual(record['argv'],argv);self.assertTrue(record['restored'])
        self.assertEqual(record['before'],record['after'])
        self.assertEqual(record['evidence']['results.json'],consumer.file_record(self.root,'candidate/results.json'))
        original=self.final.read_bytes();(self.raw/'results.json').write_text('retained raw evidence')
        with self.assertRaisesRegex(ValueError,'receipt already exists'):self.run_owner()
        self.assertEqual(self.final.read_bytes(),original)
        self.assertEqual((self.raw/'results.json').read_text(),'retained raw evidence');self.assertEqual(len(self.calls),1)

    def test_fixed_build_command_keeps_parent_environment(self):
        receipt=self.root/'candidate-build-tools.json';receipt.unlink()
        values={key:'parent-only' for key in ('GITHUB_SHA','BUILDKITE_COMMIT','GIT_SHA')}
        with patch.dict(os.environ,values):
            self.assertEqual(self.run_owner('build'),0)
            self.assertTrue(all(os.environ[key]==value for key,value in values.items()))
        argv,options=self.calls[0]
        self.assertEqual(argv,[str(self.inspector),'run','build:release','--lto=off','--webkit-version='+self.source,
            '--buildDir='+str(self.repo/'build/qualify-candidate'),'--timings'])
        self.assertFalse(any(key in options['env'] for key in values))
        record=json.loads(receipt.read_text());self.assertEqual(record['argv'],argv)
        consumer.validate_build_tools(record,'candidate',consumer.file_record(self.root,consumer.EXECUTABLE))
        self.assertTrue((self.root/'build-candidate.log').exists());self.assert_restored()

    def test_source_refusal_preserves_raw_output_and_does_not_execute(self):
        (self.raw/'results.json').write_text('retained raw evidence')
        (self.repo/'source.js').write_text('foreign edit\n')
        with self.assertRaises(ValueError):self.run_owner()
        self.assertEqual((self.raw/'results.json').read_text(),'retained raw evidence')
        self.assertEqual(self.calls,[]);self.assertFalse(self.pending.exists());self.assertFalse(self.final.exists())

    def test_post_apply_failure_restores_without_final_receipt(self):
        original=harness.files;failed=False
        def checked(repo,spec,stage):
            nonlocal failed
            if stage=='after' and not failed:failed=True;raise ValueError('post-apply fixture failure')
            return original(repo,spec,stage)
        with patch.object(harness,'files',side_effect=checked):
            with self.assertRaisesRegex(ValueError,'post-apply fixture failure'):self.run_owner()
        self.assertTrue(failed);self.assertEqual(self.calls,[]);self.assert_restored()

    def test_atomic_apply_refusal_settles_original_source(self):
        dispatch=self.dispatch
        def fail(argv,*args,**kwargs):
            if argv[:4]==['git','-C',str(self.repo),'apply'] and '--check' not in argv and '--reverse' not in argv:
                raise subprocess.CalledProcessError(1,argv)
            return dispatch(argv,*args,**kwargs)
        self.dispatch=fail
        with self.assertRaises(subprocess.CalledProcessError):self.run_owner()
        self.assertEqual(self.calls,[]);self.assert_restored()

    def test_unknown_adapted_edit_stays_visible_without_final_receipt(self):
        def child(argv,kwargs):
            self.file.write_text('unexpected edit\n')
            return subprocess.CompletedProcess(argv,0)
        self.child=child
        with self.assertRaisesRegex(ValueError,'unexpected harness bytes'):self.run_owner()
        self.assertEqual(self.file.read_text(),'unexpected edit\n')
        self.assertTrue(self.pending.exists());self.assertFalse(self.final.exists())

    def test_reverse_failure_retains_pending_and_adapted_source(self):
        dispatch=self.dispatch
        def fail(argv,*args,**kwargs):
            if argv[:4]==['git','-C',str(self.repo),'apply'] and '--reverse' in argv:
                raise subprocess.CalledProcessError(1,argv)
            return dispatch(argv,*args,**kwargs)
        self.dispatch=fail
        with self.assertRaises(subprocess.CalledProcessError):self.run_owner()
        self.assertEqual(self.file.read_text(),'adapted harness\n')
        self.assertTrue(self.pending.exists());self.assertFalse(self.final.exists())

    def test_post_restore_guard_failure_retains_pending_without_final(self):
        original=harness.source;calls=0
        def guarded(*args):
            nonlocal calls
            calls+=1
            if calls==2:raise ValueError('post-restore fixture failure')
            return original(*args)
        with patch.object(harness,'source',side_effect=guarded):
            with self.assertRaisesRegex(ValueError,'post-restore fixture failure'):self.run_owner()
        self.assert_restored(pending=True)

    def test_pending_cleanup_failure_cannot_leave_accepted_receipt(self):
        original=Path.unlink
        def unlink(path,*args,**kwargs):
            if path==self.pending:raise OSError('pending cleanup fixture failure')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',unlink):
            with self.assertRaisesRegex(OSError,'pending cleanup fixture failure'):self.run_owner()
        self.assert_restored(pending=True)

    def test_compiled_input_adapter_is_rejected_before_mutation(self):
        self.inventory.append('harness.js')
        with self.assertRaisesRegex(ValueError,'enters compiled source inventory'):self.run_owner()
        self.assertEqual(self.calls,[]);self.assert_restored()


    def test_spawn_error_records_unknown_status_and_restores_source(self):
        def child(argv,kwargs):raise OSError('fixture spawn failure')
        self.child=child
        self.assertEqual(self.run_owner(),1);self.assert_restored(final=True)
        self.assertEqual(json.loads((self.root/'candidate/wrapper-terminal.json').read_text()),{'status':None})
        with self.assertRaises(ValueError):consumer.validate_invocation(self.root,'candidate')

    def test_final_write_failure_leaves_no_acceptable_receipt(self):
        original=consumer.write_once
        def write(path,record):
            if path==self.final:raise OSError('final receipt fixture failure')
            return original(path,record)
        with patch.object(consumer,'write_once',side_effect=write):
            with self.assertRaisesRegex(OSError,'final receipt fixture failure'):self.run_owner()
        self.assert_restored()

    def test_package_and_cli_import_entrypoints(self):
        result=subprocess.run([sys.executable,str(Path(harness.__file__)),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('--inspector-runtime',result.stdout)


if __name__=='__main__':unittest.main()
