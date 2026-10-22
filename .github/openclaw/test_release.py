import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('release',Path(__file__).with_name('release.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
spec=importlib.util.spec_from_file_location('artifacts',Path(__file__).with_name('artifacts.py'))
artifacts=importlib.util.module_from_spec(spec);spec.loader.exec_module(artifacts)
SOURCE='a'*40

class ReleaseIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.inputs=self.root/'inputs';self.inputs.mkdir()
        self.out=self.root/'release'
        config=json.loads((release.ROOT/'.github/openclaw/variants.json').read_text())
        q=self.inputs/'qualification';q.mkdir();(q/'gate.json').write_text(json.dumps({'passed':True,'source':SOURCE,'bun_commit':config['bun_commit']}))
        for lane in config['lanes']:
            label=lane['label'];d=self.inputs/label;d.mkdir();(d/'provenance').mkdir()
            f=d/(label+'.tar.gz');f.write_bytes(label.encode())
            (d/(label+'.manifest.json')).write_text(json.dumps({'source':SOURCE,'lane':{'label':label},'files':{f.name:{'sha256':release.sha(f),'size':f.stat().st_size}}}))
    def assemble(self):release.assemble(self.inputs,self.out,SOURCE)
    def test_complete_set_roundtrip(self):
        self.assemble();self.assertEqual(len(release.verify(self.out,SOURCE)['artifacts']),9)
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
        names=['preflight','test','assemble']+['build ('+l['label']+')' for l in config['lanes']]
        jobs={'jobs':[{'name':n,'conclusion':'success','run_attempt':1} for n in names]}
        pending=[{'environment':{'name':'openclaw-artifacts','id':99},'current_user_can_approve':True}]
        with patch.object(release,'api',side_effect=[{'enabled':True},run,jobs,pending,{}]) as api,patch.object(release,'execute') as execute:
            release.authorize(SOURCE,42)
            self.assertEqual(execute.call_count,1)
            self.assertIn('state=approved',api.call_args.args)

    def test_authorization_accepts_protected_batch_branch(self):
        run={'head_sha':SOURCE,'head_branch':'openclaw/batch-1','event':'workflow_dispatch','path':'.github/workflows/openclaw-artifacts.yml@openclaw/batch-1','run_attempt':1}
        config=json.loads((release.ROOT/'.github/openclaw/variants.json').read_text())
        names=['preflight','test','assemble']+['build ('+l['label']+')' for l in config['lanes']]
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

class ArtifactRecipe(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.addCleanup(os.chdir,Path.cwd());os.chdir(self.root)
        self.git('init','-q')
        self.git('config','user.name','Recipe fixture');self.git('config','user.email','fixture@example.invalid')
        self.git('config','commit.gpgsign','false')
        for name in artifacts.RECIPE:
            p=self.root/name
            if name in ('icu','macos-cross'):p=p/'input.txt'
            p.parent.mkdir(parents=True,exist_ok=True);p.write_text('reviewed input\n')
        (self.root/'Dockerfile').write_text('ARG NODE_VERSION=24.16.0\n')
        (self.root/'source.txt').write_text('engine source\n')
        self.commit('upstream base');self.base=self.git('rev-parse','HEAD')
        (self.root/'Dockerfile').write_text('ARG NODE_VERSION=24.22.1\n')
        self.commit('reviewed Node security update')
        recipe=subprocess.check_output(['git','ls-tree','--full-tree','-z','HEAD','--',*artifacts.RECIPE])
        revision={'reviewed_source':self.git('rev-parse','HEAD'),'tree_sha256':hashlib.sha256(recipe).hexdigest()}
        for name,value in [('BASE',self.base),('RECIPE_REVISION',revision)]:
            p=patch.object(artifacts,name,value,create=True);p.start();self.addCleanup(p.stop)
    def git(self,*args):
        return subprocess.check_output(['git',*args],text=True).strip()
    def commit(self,message):
        self.git('add','.');self.git('commit','-qm',message)
    def test_reviewed_recipe_survives_squash_and_later_engine_commits(self):
        self.git('reset','--hard',self.base)
        (self.root/'Dockerfile').write_text('ARG NODE_VERSION=24.22.1\n')
        self.commit('squashed reviewed update')
        self.assertEqual(artifacts.source(),self.git('rev-parse','HEAD'))
        (self.root/'source.txt').write_text('security-patched engine source\n')
        self.commit('engine change after reviewed recipe')
        self.assertEqual(artifacts.source(),self.git('rev-parse','HEAD'))
    def test_unreviewed_recipe_and_dirty_source_are_rejected(self):
        (self.root/'source.txt').write_text('uncommitted engine change\n')
        with self.assertRaises(subprocess.CalledProcessError):artifacts.source()
        self.git('checkout','--','source.txt')
        for name,mode in [('Dockerfile',False),('icu/input.txt',False),('Dockerfile',True)]:
            with self.subTest(path=name,mode=mode):
                p=self.root/name
                if mode:p.chmod(0o755)
                else:p.write_text('unreviewed recipe input\n')
                self.commit('unreviewed recipe change')
                with self.assertRaisesRegex(ValueError,'recipe differs'):artifacts.source()
                self.git('reset','--hard','HEAD^')

if __name__=='__main__':unittest.main()
