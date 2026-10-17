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
from qualification import consumer_identity as consumer, compile_cache
import xml.etree.ElementTree as ET


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
    consumer.write_once(proof/'candidate-identity.json',identity);consumer.write_once(proof/'baseline-identity.json',baseline)
    digest=consumer.sha(proof/'candidate-identity.json')
    report=proof/'sync/module-junit.xml';report.parent.mkdir()
    suites=ET.Element('testsuites');suite=ET.SubElement(suites,'testsuite',name=compile_cache.MODULE)
    for classname,name in compile_cache.CASES:
        ET.SubElement(suite,'testcase',classname=classname,name=name,file=compile_cache.MODULE)
    ET.ElementTree(suites).write(report,encoding='utf-8',xml_declaration=True)
    gate={'passed':True,'source':source,'comparison':'bun-plus-engine-upgrade','selected_files':44,'result_files':46,
        'candidate_identity_sha256':digest,'baseline_identity_sha256':consumer.sha(proof/'baseline-identity.json'),
        'upstream_sync':{'passed':True,'source':source,'candidate_identity_sha256':digest,'historical_selected_files':82,'selected_files':85,'regressions':0,'compile_cache':compile_cache.evidence(report)},
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


if __name__=='__main__':unittest.main()
