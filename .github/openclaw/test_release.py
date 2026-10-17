import importlib.util
import json
import base64
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from test_consumer_identity import release_fixture

spec=importlib.util.spec_from_file_location('release',Path(__file__).with_name('release.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
SOURCE='a'*40
PATCHES=[{'commit':commit,'subject':'fixture'+str(index),'patch_sha256':str(index+1)*64}
    for index,commit in enumerate(['b'*40,'c'*40,SOURCE])]

class ReleaseIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.inputs=self.root/'inputs';self.inputs.mkdir()
        self.out=self.root/'release'
        config=json.loads((release.ROOT/'.github/openclaw/variants.json').read_text())
        q=self.inputs/'qualification';q.mkdir()
        for lane in config['lanes']:
            label=lane['label'];d=self.inputs/label;d.mkdir();(d/'provenance').mkdir()
            f=d/(label+'.tar.gz');f.write_bytes(label.encode())
            (d/(label+'.manifest.json')).write_text(json.dumps({'source':SOURCE,'base':release.artifact_source.BASE,'history_floor':release.artifact_source.HISTORY_FLOOR,'patches':PATCHES,'lane':{'label':label},'files':{f.name:{'sha256':release.sha(f),'size':f.stat().st_size}}}))
        release_fixture(self.inputs,SOURCE)
        w=self.inputs/'windows-arm64-qualification';w.mkdir()
        archive=self.inputs/'bun-webkit-windows-arm64/bun-webkit-windows-arm64.tar.gz'
        (w/'gate.json').write_text(json.dumps({'passed':True,'source':SOURCE,'lane':'bun-webkit-windows-arm64','architecture':'arm64','sha256':release.sha(archive),'startup':True,'dfg':True,'ffi':True,'arraybuffer_accounting':True,'arraybuffer_modes':5}))
    def test_windows_gate_rejects_wrong_source_digest_or_failed_probe(self):
        p=self.inputs/'windows-arm64-qualification/gate.json';original=json.loads(p.read_text())
        for key,value in [('source','b'*40),('sha256','0'*64),('architecture','x64'),('startup',False),('dfg',False),('ffi',False),('arraybuffer_accounting',False),('arraybuffer_accounting',None),('arraybuffer_modes',4),('arraybuffer_modes',None)]:
            with self.subTest(key=key):
                p.write_text(json.dumps({**original,key:value}))
                with self.assertRaisesRegex(ValueError,'native Windows ARM64'):self.assemble()
                import shutil
                shutil.rmtree(self.out)
    def test_windows_gate_is_required(self):
        (self.inputs/'windows-arm64-qualification/gate.json').unlink()
        with self.assertRaises(FileNotFoundError):self.assemble()
    def assemble(self):release.assemble(self.inputs,self.out,SOURCE)
    def test_invalid_lane_history_provenance_rejected(self):
        p=next(self.inputs.glob('*/*.manifest.json'));original_text=p.read_text();original=json.loads(original_text)
        cases=[]
        for key in ['base','history_floor','patches']:
            manifest={**original};del manifest[key];cases.append(('missing-'+key,manifest))
        for key,value in [('base','0'*40),('history_floor','0'*40),('patches',{}),('patches',None),('patches',[])]:
            cases.append(('wrong-'+key+'-'+repr(value),{**original,key:value}))
        cases.append(('nonobject-row',{**original,'patches':[None,*PATCHES[1:]]}))
        for key,value in [('commit','A'*40),('commit',None),('subject',None),('patch_sha256','0'*63),('patch_sha256',None)]:
            cases.append(('bad-row-'+key+'-'+repr(value),{**original,'patches':[{**PATCHES[0],key:value},*PATCHES[1:]]}))
        missing={**PATCHES[0]};del missing['subject']
        cases.extend([
            ('missing-row-key',{**original,'patches':[missing,*PATCHES[1:]]}),
            ('extra-row-key',{**original,'patches':[{**PATCHES[0],'extra':True},*PATCHES[1:]]}),
            ('duplicate-commit',{**original,'patches':[PATCHES[0],PATCHES[0],PATCHES[2]]}),
            ('missing-final-source',{**original,'patches':PATCHES[:-1]}),
        ])
        for index,(name,manifest) in enumerate(cases):
            with self.subTest(name=name):
                try:
                    p.write_text(json.dumps(manifest))
                    with self.assertRaisesRegex(ValueError,'invalid lane history provenance'):
                        release.assemble(self.inputs,self.root/('invalid-history-'+str(index)),SOURCE)
                finally:
                    p.write_text(original_text)

    def test_lane_patch_provenance_must_match_exactly(self):
        label=sorted(lane['label'] for lane in release.consumer_identity.CONFIG['lanes']
            if lane['label']!=release.consumer_identity.LANE)[0]
        p=self.inputs/label/(label+'.manifest.json');original_text=p.read_text();original=json.loads(original_text)
        records=[
            [{**PATCHES[0],'subject':'different'},*PATCHES[1:]],
            [{**PATCHES[0],'patch_sha256':'f'*64},*PATCHES[1:]],
            [{**PATCHES[0],'commit':'d'*40},*PATCHES[1:]],
            [PATCHES[1],PATCHES[0],PATCHES[2]],
            PATCHES[1:],
        ]
        for index,patches in enumerate(records):
            with self.subTest(index=index):
                try:
                    p.write_text(json.dumps({**original,'patches':patches}))
                    with self.assertRaisesRegex(ValueError,'lane patch provenance mismatch'):
                        release.assemble(self.inputs,self.root/('mismatched-history-'+str(index)),SOURCE)
                finally:
                    p.write_text(original_text)

    def test_candidate_lane_patch_provenance_is_bound_to_receipt(self):
        label=release.consumer_identity.LANE
        p=self.inputs/label/(label+'.manifest.json');manifest=json.loads(p.read_text())
        manifest['patches'][0]['subject']='different';p.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'candidate archive identity mismatch'):self.assemble()

    def test_base_source_allows_empty_patch_history(self):
        manifest={'base':release.artifact_source.BASE,'history_floor':release.artifact_source.HISTORY_FLOOR,'patches':[]}
        self.assertEqual(release.lane_patch_records(manifest,release.artifact_source.BASE),[])

    def test_complete_set_roundtrip(self):
        self.assemble();self.assertEqual(len(release.verify(self.out,SOURCE)['artifacts']),10)
    def test_changed_lane_bytes_rejected(self):
        next(self.inputs.glob('*/*.tar.gz')).write_bytes(b'tampered')
        with self.assertRaises(ValueError):self.assemble()
    def test_wrong_source_rejected(self):
        p=next(self.inputs.glob('*/*.manifest.json'));m=json.loads(p.read_text());m['source']='b'*40;p.write_text(json.dumps(m))
        with self.assertRaises(ValueError):self.assemble()
    def test_failed_gate_rejected(self):
        p=self.inputs/'qualification/gate.json';m=json.loads(p.read_text());m['passed']=False;p.write_text(json.dumps(m))
        with self.assertRaises(ValueError):self.assemble()
    def test_extra_asset_rejected(self):
        self.assemble();(self.out/'unreviewed').write_text('x')
        with self.assertRaises(ValueError):release.verify(self.out,SOURCE)
    def test_manifest_tampering_rejected(self):
        self.assemble();p=self.out/'manifest.json';p.write_text(p.read_text()+' ')
        with self.assertRaises(ValueError):release.verify(self.out,SOURCE)
    def test_existing_tag_stops_before_release_write(self):
        self.assemble()
        with patch.dict('os.environ',self.authorization()), patch.object(release,'api',side_effect=subprocess.CalledProcessError(1,['gh'])),patch.object(release,'execute') as execute:
            with self.assertRaises(subprocess.CalledProcessError):release.publish(self.out,SOURCE)
            execute.assert_not_called()
    def test_mutable_repository_stops_before_tag(self):
        self.assemble()
        with patch.object(release,'api',return_value={'enabled':False}) as api,patch.object(release,'execute') as execute:
            with self.assertRaises(ValueError):release.authorize(SOURCE,42)
            self.assertEqual(api.call_count,1);execute.assert_not_called()

    def authorization(self,**changes):
        receipt={'source':SOURCE,'run_id':'42','run_attempt':'1','verified_at':time.time(),'immutable_enabled':True,**changes}
        return {'GITHUB_REF':'refs/heads/openclaw/main','GITHUB_SHA':SOURCE,'GITHUB_RUN_ID':'42','GITHUB_RUN_ATTEMPT':'1','IMMUTABILITY_RECEIPT':json.dumps(receipt)}
    def test_receipt_is_bound_to_run_source_attempt_and_time(self):
        for changes in [{'source':'b'*40},{'run_id':'43'},{'run_attempt':'2'},{'verified_at':time.time()-901},{'immutable_enabled':False}]:
            with self.subTest(changes=changes),patch.dict('os.environ',self.authorization(**changes)):
                with self.assertRaises(ValueError):release.validate_authorization(SOURCE)
    def test_draft_digest_lookup_uses_release_id(self):
        self.assemble()
        def api(*args):
            if args[:2]==('-X','POST') and args[2].endswith('/git/refs'):return {}
            if args[:2]==('-X','POST') and args[2].endswith('/releases'):return {'id':123}
            if args==(f'repos/{release.REPO}/releases/123',):return {'assets':[]}
            self.fail('unexpected API lookup: '+repr(args))
        with patch.dict('os.environ',self.authorization()),patch.object(release,'api',side_effect=api),patch.object(release,'execute'):
            with self.assertRaisesRegex(ValueError,'uploaded asset digest mismatch'):release.publish(self.out,SOURCE)

    def test_authorization_requires_every_exact_green_job(self):
        run={'head_sha':SOURCE,'head_branch':'openclaw/main','event':'workflow_dispatch','path':'.github/workflows/openclaw-artifacts.yml@openclaw/main','run_attempt':1}
        with patch.object(release,'api',side_effect=[{'enabled':True},run,{'jobs':[{'name':'test','conclusion':'success','run_attempt':1}]}]),patch.object(release,'execute') as execute:
            with self.assertRaisesRegex(ValueError,'all exact build'):release.authorize(SOURCE,42)
            execute.assert_not_called()

    def test_authorization_accepts_ref_qualified_path(self):
        run={'head_sha':SOURCE,'head_branch':'openclaw/main','event':'workflow_dispatch','path':'.github/workflows/openclaw-artifacts.yml@openclaw/main','run_attempt':1}
        config=json.loads((release.ROOT/'.github/openclaw/variants.json').read_text())
        names=['preflight','test','windows-arm64','assemble']+['build ('+l['label']+')' for l in config['lanes']]
        jobs={'jobs':[{'name':n,'conclusion':'success','run_attempt':1} for n in names]}
        pending=[{'environment':{'name':'openclaw-artifacts','id':99},'current_user_can_approve':True}]
        with patch.object(release,'api',side_effect=[{'enabled':True},run,jobs,pending,{}]) as api,patch.object(release,'execute') as execute:
            release.authorize(SOURCE,42)
            self.assertEqual(execute.call_count,1)
            self.assertIn('state=approved',api.call_args.args)

    def test_authorization_accepts_protected_batch_branch(self):
        run={'head_sha':SOURCE,'head_branch':'openclaw/batch-1','event':'workflow_dispatch','path':'.github/workflows/openclaw-artifacts.yml@openclaw/batch-1','run_attempt':1}
        config=json.loads((release.ROOT/'.github/openclaw/variants.json').read_text())
        names=['preflight','test','windows-arm64','assemble']+['build ('+l['label']+')' for l in config['lanes']]
        jobs={'jobs':[{'name':n,'conclusion':'success','run_attempt':1} for n in names]}
        pending=[{'environment':{'name':'openclaw-artifacts','id':99},'current_user_can_approve':True}]
        with patch.object(release,'api',side_effect=[{'enabled':True},run,jobs,pending,{}]),patch.object(release,'execute') as execute:
            release.authorize(SOURCE,42)
            self.assertEqual(execute.call_count,1)
    def test_missing_upstream_sync_gate_rejected(self):
        p=self.inputs/'qualification/gate.json';m=json.loads(p.read_text());del m['upstream_sync'];p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'upstream-sync'):self.assemble()
    def test_missing_paired_compatibility_rejected(self):
        p=self.inputs/'qualification/gate.json';m=json.loads(p.read_text());del m['compatibility'];p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'candidate compatibility'):self.assemble()
    def test_missing_or_failed_startup_rejected(self):
        p=self.inputs/'qualification/gate.json'
        for value in [None,False]:
            with self.subTest(startup=value):
                m=json.loads(p.read_text())
                if value is None:m['compatibility'].pop('startup',None)
                else:m['compatibility']['startup']=value
                p.write_text(json.dumps(m))
                with self.assertRaisesRegex(ValueError,'candidate compatibility'):self.assemble()
                if self.out.exists():self.out.rmdir()
    def test_candidate_receipt_rejects_wrong_source_tree_index_or_runtime(self):
        p=self.inputs/'qualification/candidate-identity.json';original=p.read_text()
        for index,(section,key,value) in enumerate([
            ('candidate','commit','b'*40),('candidate','tree','b'*40),('candidate','index_tree','b'*40),
            ('overlay','tracked_changed_paths',['other.cpp']),('runtime','webkit','b'*40),
            ('runtime','bun_revision','b'*40),('fixture','sha256','0'*64)]):
            with self.subTest(section=section,key=key):
                try:
                    record=json.loads(original);record[section][key]=value;p.write_text(json.dumps(record))
                    with self.assertRaises(ValueError):
                        release.assemble(self.inputs,self.root/('bad-identity-'+str(index)),SOURCE)
                finally:p.write_text(original)
    def test_actual_consumer_bytes_and_overlay_are_required(self):
        paths=[
            'linux-bun-executables/'+release.consumer_identity.EXECUTABLE,
            'linux-bun-executables/'+release.consumer_identity.BASELINE_EXECUTABLE,
            'linux-bun-executables/'+release.consumer_identity.FIXTURE,
            'qualification/candidate-input/artifacts.json',
            'qualification/candidate-manifest.patch','qualification/baseline-adapters.patch']
        for index,path in enumerate(paths):
            file=self.inputs/path;original=file.read_bytes()
            with self.subTest(path=path):
                try:
                    file.write_bytes(original+b'tampered')
                    with self.assertRaises(ValueError):
                        release.assemble(self.inputs,self.root/('bad-bytes-'+str(index)),SOURCE)
                finally:file.write_bytes(original)
    def test_qualification_cannot_substitute_for_binary_artifact_root(self):
        import shutil
        binary=self.inputs/'linux-bun-executables'/release.consumer_identity.EXECUTABLE
        misplaced=self.inputs/'qualification'/release.consumer_identity.EXECUTABLE
        misplaced.parent.mkdir(parents=True);shutil.move(binary,misplaced)
        with self.assertRaises(ValueError):self.assemble()
    def test_stale_receipt_binding_rejected_in_every_gate(self):
        p=self.inputs/'qualification/gate.json';original=p.read_text()
        for index,section in enumerate([None,'compatibility','upstream_sync']):
            with self.subTest(section=section):
                try:
                    gate=json.loads(original);target=gate if section is None else gate[section]
                    target['candidate_identity_sha256']='0'*64;p.write_text(json.dumps(gate))
                    with self.assertRaises(ValueError):
                        release.assemble(self.inputs,self.root/('stale-receipt-'+str(index)),SOURCE)
                finally:p.write_text(original)
    def test_candidate_archive_must_match_assembled_lane(self):
        lane=self.inputs/release.consumer_identity.LANE
        archive=lane/(release.consumer_identity.LANE+'.tar.gz');archive.write_bytes(b'replaced archive')
        manifest=lane/(release.consumer_identity.LANE+'.manifest.json');record=json.loads(manifest.read_text())
        record['files'][archive.name]={'size':archive.stat().st_size,'sha256':release.sha(archive)}
        manifest.write_text(json.dumps(record))
        with self.assertRaises(ValueError):self.assemble()
    def test_wrong_engine_gate_source_rejected(self):
        p=self.inputs/'qualification/gate.json';m=json.loads(p.read_text());m['engine']['source']='b'*40;p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'upstream-sync'):self.assemble()
    def test_compile_cache_case_and_digest_binding(self):
        report=self.inputs/'qualification/sync/module-junit.xml';original=report.read_bytes()
        cases=[('missing',lambda r,s:s.remove(r)),
               ('skipped',lambda r,s:ET.SubElement(r,'skipped')),
               ('failure',lambda r,s:ET.SubElement(r,'failure')),
               ('error',lambda r,s:ET.SubElement(r,'error')),
               ('duplicate',lambda r,s:s.append(ET.fromstring(ET.tostring(r)))),
               ('wrong-file',lambda r,s:r.set('file','other.test.js')),
               ('wrong-class',lambda r,s:r.set('classname','other')),
               ('other-failure',lambda r,s:ET.SubElement(ET.SubElement(s,'testcase',name='other'),'failure')),
               ('digest',lambda r,s:r.set('assertions','1'))]
        for name,change in cases:
            with self.subTest(name=name):
                try:
                    root=ET.fromstring(original);suite=root.find('testsuite');row=suite.find('testcase');change(row,suite)
                    ET.ElementTree(root).write(report,encoding='utf-8',xml_declaration=True)
                    with self.assertRaises(ValueError):release.assemble(self.inputs,self.root/('cache-'+name),SOURCE)
                finally:report.write_bytes(original)
        report.unlink()
        with self.assertRaises(FileNotFoundError):release.assemble(self.inputs,self.root/'cache-no-report',SOURCE)

    def test_compile_cache_receipt_required(self):
        p=self.inputs/'qualification/gate.json';gate=json.loads(p.read_text())
        del gate['upstream_sync']['compile_cache'];p.write_text(json.dumps(gate))
        with self.assertRaisesRegex(ValueError,'compile-cache'):self.assemble()

    def test_compile_cache_collection_requires_this_runs_native_report(self):
        temp=self.root/'native-junit';temp.mkdir();prefix='openclaw-sync-junit-'+'1'*32+'-'
        output=self.root/'module-junit.xml';gate=release.compile_cache
        fixture=(self.inputs/'qualification/sync/module-junit.xml').read_bytes()
        hashed=base64.urlsafe_b64encode(hashlib.sha1(gate.MODULE.encode()).digest()).decode().rstrip('=')
        filename='test-'+hashed+'.xml'
        stale=temp/('openclaw-sync-junit-'+'0'*32+'-old');stale.mkdir();(stale/filename).write_bytes(fixture)
        with self.assertRaisesRegex(ValueError,'current-run'):gate.collect(temp,prefix,output)
        current=temp/(prefix+'native');current.mkdir()
        with self.assertRaisesRegex(ValueError,'report missing'):gate.collect(temp,prefix,output)
        report=current/filename;report.symlink_to(stale/filename)
        with self.assertRaisesRegex(ValueError,'report missing'):gate.collect(temp,prefix,output)
        report.unlink();report.write_bytes(fixture)
        duplicate=temp/(prefix+'duplicate');duplicate.mkdir()
        with self.assertRaisesRegex(ValueError,'current-run'):gate.collect(temp,prefix,output)
        duplicate.rmdir();gate.collect(temp,prefix,output)
        self.assertEqual(output.read_bytes(),fixture)
        self.assertEqual(gate.evidence(output),gate.evidence(report))
        with self.assertRaises(FileExistsError):gate.collect(temp,prefix,output)
        with self.assertRaisesRegex(ValueError,'prefix'):gate.collect(temp,'../',self.root/'invalid.xml')

    def test_authorization_accepts_rebased_release_branch(self):
        run={'head_sha':SOURCE,'head_branch':'openclaw/release-5718a6ec','event':'workflow_dispatch','path':'.github/workflows/openclaw-artifacts.yml','run_attempt':1}
        config=json.loads((release.ROOT/'.github/openclaw/variants.json').read_text())
        names=['preflight','test','windows-arm64','assemble']+['build ('+l['label']+')' for l in config['lanes']]
        jobs={'jobs':[{'name':n,'conclusion':'success','run_attempt':1} for n in names]}
        pending=[{'environment':{'name':'openclaw-artifacts','id':99},'current_user_can_approve':True}]
        with patch.object(release,'api',side_effect=[{'enabled':True},run,jobs,pending,{}]),patch.object(release,'execute') as execute:
            release.authorize(SOURCE,42)
            self.assertEqual(execute.call_count,1)
    def test_authorization_rejects_other_branch(self):
        run={'head_sha':SOURCE,'head_branch':'feature/unreviewed','event':'workflow_dispatch','path':'.github/workflows/openclaw-artifacts.yml','run_attempt':1}
        with patch.object(release,'api',side_effect=[{'enabled':True},run]),patch.object(release,'execute') as execute:
            with self.assertRaisesRegex(ValueError,'reviewed source'):release.authorize(SOURCE,42)
            execute.assert_not_called()

if __name__=='__main__':unittest.main()
