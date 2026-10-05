import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('release',Path(__file__).with_name('release.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
SOURCE='a'*40

class ReleaseIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.inputs=self.root/'inputs';self.inputs.mkdir()
        self.out=self.root/'release'
        config=json.loads((release.ROOT/'.github/openclaw/variants.json').read_text())
        q=self.inputs/'qualification';q.mkdir();(q/'gate.json').write_text(json.dumps({'passed':True,'source':SOURCE,'bun_commit':config['bun_commit'],'upstream_sync':{'passed':True,**config['upstream_sync']},'engine':{'passed':True,'source':SOURCE},'compatibility':{'passed':True,'source':SOURCE,**config['upstream_sync'],'only_manifest_changed_after_pairing':True,'memory_tests':3,'startup':True}}))
        for lane in config['lanes']:
            label=lane['label'];d=self.inputs/label;d.mkdir();(d/'provenance').mkdir()
            f=d/(label+'.tar.gz');f.write_bytes(label.encode())
            (d/(label+'.manifest.json')).write_text(json.dumps({'source':SOURCE,'lane':{'label':label},'files':{f.name:{'sha256':release.sha(f),'size':f.stat().st_size}}}))
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
        with self.assertRaisesRegex(ValueError,'namespace-paired'):self.assemble()
    def test_missing_or_failed_startup_rejected(self):
        p=self.inputs/'qualification/gate.json'
        for value in [None,False]:
            with self.subTest(startup=value):
                m=json.loads(p.read_text())
                if value is None:m['compatibility'].pop('startup',None)
                else:m['compatibility']['startup']=value
                p.write_text(json.dumps(m))
                with self.assertRaisesRegex(ValueError,'namespace-paired'):self.assemble()
                if self.out.exists():self.out.rmdir()
    def test_wrong_paired_tree_or_namespace_adapter_rejected(self):
        p=self.inputs/'qualification/gate.json'
        original=json.loads(p.read_text())
        for key in ['paired_tree','required_namespace_adapter_sha256']:
            with self.subTest(field=key):
                m=json.loads(json.dumps(original));m['compatibility'][key]='b'*40;p.write_text(json.dumps(m))
                with self.assertRaisesRegex(ValueError,'namespace-paired'):self.assemble()
                if self.out.exists():self.out.rmdir()
    def test_wrong_prepared_tree_rejected(self):
        p=self.inputs/'qualification/gate.json';m=json.loads(p.read_text());m['compatibility']['prepared_tree']='b'*40;p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'namespace-paired'):self.assemble()
    def test_extra_runtime_changes_rejected(self):
        p=self.inputs/'qualification/gate.json';m=json.loads(p.read_text());m['compatibility']['only_manifest_changed_after_pairing']=False;p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'namespace-paired'):self.assemble()
    def test_wrong_sync_tree_rejected(self):
        p=self.inputs/'qualification/gate.json';m=json.loads(p.read_text());m['upstream_sync']['prepared_tree']='b'*40;p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'upstream-sync'):self.assemble()
    def test_wrong_engine_gate_source_rejected(self):
        p=self.inputs/'qualification/gate.json';m=json.loads(p.read_text());m['engine']['source']='b'*40;p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'upstream-sync'):self.assemble()
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
