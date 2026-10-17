#!/usr/bin/env python3
"""Assemble checked lane outputs, then create one immutable release without replacement."""
import argparse
import artifacts as artifact_source
from qualification import consumer_identity, compile_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import subprocess

ROOT=Path(__file__).resolve().parents[2]
REPO='openclaw/WebKit'

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def api(*args):return json.loads(subprocess.check_output(['gh','api',*args],text=True) or '{}')
def execute(*args):subprocess.run(args,check=True)
def save(p,x):p.write_text(json.dumps(x,indent=2)+'\n')

def lane_patch_records(manifest,source):
    patches=manifest.get('patches')
    if (manifest.get('base')!=artifact_source.BASE or manifest.get('history_floor')!=artifact_source.HISTORY_FLOOR
        or not isinstance(patches,list)):
        raise ValueError('invalid lane history provenance')
    seen=set()
    for row in patches:
        if (not isinstance(row,dict) or set(row)!={'commit','subject','patch_sha256'}
            or not all(isinstance(row[key],str) for key in ('commit','subject','patch_sha256'))
            or not re.fullmatch('[0-9a-f]{40}',row['commit']) or not re.fullmatch('[0-9a-f]{64}',row['patch_sha256'])
            or row['commit'] in seen):
            raise ValueError('invalid lane history provenance')
        seen.add(row['commit'])
    if (patches and patches[-1]['commit']!=source) or (not patches and source!=artifact_source.BASE):
        raise ValueError('invalid lane history provenance')
    return patches

def assemble(inputs,out,source):
    out.mkdir(parents=True,exist_ok=False)
    config=json.loads((ROOT/'.github/openclaw/variants.json').read_text())
    tag='autobuild-'+source
    gate_path=inputs/'qualification/gate.json'
    gate=json.loads(gate_path.read_text())
    proof=inputs/'qualification';binaries=inputs/'linux-bun-executables'
    identity_path=proof/'candidate-identity.json';baseline_path=proof/'baseline-identity.json'
    identity=json.loads(identity_path.read_text());baseline=json.loads(baseline_path.read_text())
    consumer_identity.validate(identity,source)
    consumer_identity.validate_baseline_evidence(baseline,binaries,proof)
    identity_sha=sha(identity_path)
    if (gate.get('passed') is not True or gate['source']!=source
        or gate.get('comparison')!='bun-plus-engine-upgrade'
        or gate.get('candidate_identity_sha256')!=identity_sha
        or gate.get('baseline_identity_sha256')!=sha(baseline_path)
        or gate.get('selected_files')!=44 or gate.get('result_files')!=46):
        raise ValueError('missing or mismatched qualification gate')
    sync=gate.get('upstream_sync',{});engine=gate.get('engine',{})
    if (sync.get('passed') is not True or sync.get('source')!=source
        or sync.get('candidate_identity_sha256')!=identity_sha
        or sync.get('historical_selected_files')!=82 or sync.get('selected_files')!=85
        or sync.get('regressions')!=0 or engine.get('passed') is not True or engine.get('source')!=source):
        raise ValueError('missing or mismatched upstream-sync/engine qualification')
    if sync.get('compile_cache')!=compile_cache.evidence(proof/'sync/module-junit.xml'):
        raise ValueError('missing or mismatched compile-cache qualification')
    compatibility=gate.get('compatibility',{})
    if (compatibility.get('passed') is not True or compatibility.get('source')!=source
        or compatibility.get('candidate_identity_sha256')!=identity_sha
        or compatibility.get('memory_tests')!=3 or compatibility.get('startup') is not True):
        raise ValueError('missing or mismatched candidate compatibility gate')
    artifacts={}; lanes=[]
    expected_patches=None
    for lane in config['lanes']:
        label=lane['label']; name=label+'.tar.gz'; directory=inputs/label
        manifest=json.loads((directory/(label+'.manifest.json')).read_text())
        if manifest['source']!=source or manifest['lane']['label']!=label:
            raise ValueError('mixed source or lane')
        patches=lane_patch_records(manifest,source)
        if expected_patches is None:expected_patches=patches
        elif patches!=expected_patches:raise ValueError('lane patch provenance mismatch')
        f=directory/name
        if sha(f)!=manifest['files'][name]['sha256'] or f.stat().st_size!=manifest['files'][name]['size']:
            raise ValueError('lane digest mismatch')
        if label==consumer_identity.LANE:
            measured=consumer_identity.engine_input(f,directory/(label+'.manifest.json'),source)
            consumer_identity.validate_evidence(identity,source,measured,binaries,proof)
        shutil.copyfile(f,out/name)
        artifacts[name]={'url':f'https://github.com/{REPO}/releases/download/{tag}/{name}','sha256':sha(f),'size':f.stat().st_size}
        lanes.append(manifest)
    windows=json.loads((inputs/'windows-arm64-qualification/gate.json').read_text())
    if (windows.get('passed') is not True or windows.get('source')!=source
        or windows.get('lane')!='bun-webkit-windows-arm64' or windows.get('architecture')!='arm64'
        or windows.get('sha256')!=artifacts['bun-webkit-windows-arm64.tar.gz']['sha256']
        or any(windows.get(k) is not True for k in ('startup','dfg','ffi','arraybuffer_accounting'))
        or windows.get('arraybuffer_modes')!=5):
        raise ValueError('missing or mismatched native Windows ARM64 qualification')
    gate['windows_arm64']=windows
    # Retain low-level provenance and test logs as a separate archive.
    execute('tar','-czf',str(out/'provenance.tar.gz'),'-C',str(inputs),*[
        item for lane in config['lanes'] for item in [lane['label']+'/provenance',lane['label']+'/'+lane['label']+'.manifest.json']], 'qualification', 'windows-arm64-qualification')
    license_text='OpenClaw WebKit source and licenses\n\n'+f'Source: https://github.com/{REPO}/tree/{source}\nSource archive: https://github.com/{REPO}/archive/{source}.tar.gz\n\n'
    for p in ['Source/JavaScriptCore/COPYING.LIB','Source/WTF/wtf/COPYING.LIB']:
        file=ROOT/p
        if file.is_file():license_text+='\n'+p+'\n'+file.read_text()+'\n'
    license_text+='\nIndividual files retain their copyright and license notices. ICU source and license: https://github.com/unicode-org/icu/tree/release-78-3\nToolchains and SDKs are downloaded from their upstream distributors; no toolchain image or SDK is published.\n'
    (out/'LICENSE-SOURCES.txt').write_text(license_text)
    save(out/'manifest.json',{'schema_version':1,'version':source,'repository':REPO,'tag':tag,
        'artifacts':artifacts,'variants':config,'qualification':gate,'lanes':lanes,
        'supporting_files':{p.name:{'sha256':sha(p),'size':p.stat().st_size} for p in out.iterdir() if p.name not in artifacts}})
    (out/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in sorted(out.iterdir()) if p.is_file()))

def verify(directory,source):
    m=json.loads((directory/'manifest.json').read_text())
    if m['version']!=source or m['tag']!='autobuild-'+source:raise ValueError('wrong release source')
    files={**m['artifacts'],**m['supporting_files']}
    for name,entry in files.items():
        if Path(name).name!=name or sha(directory/name)!=entry['sha256'] or (directory/name).stat().st_size!=entry['size']:
            raise ValueError('manifest digest mismatch')
    sums={}
    for line in (directory/'SHA256SUMS').read_text().splitlines():
        digest,name=line.split('  ',1)
        if name in sums or Path(name).name!=name or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('invalid checksum entry')
        sums[name]=digest
        if sha(directory/name)!=digest:raise ValueError('SHA256SUMS mismatch')
    if set(sums)!=set(files)|{'manifest.json'}:raise ValueError('incomplete checksum coverage')
    if {p.name for p in directory.iterdir()}!=set(sums)|{'SHA256SUMS'}:raise ValueError('unexpected release files')
    return m

def authorize(source,run_id):
    # This maintainer-side check uses the existing administrator login, never a new CI secret.
    if not api('-H','Cache-Control: max-age=0',f'repos/{REPO}/immutable-releases')['enabled']:
        raise ValueError('immutable releases must be enabled')
    run=api('-H','Cache-Control: max-age=0',f'repos/{REPO}/actions/runs/{run_id}')
    if (run['head_sha']!=source or run['head_branch'] not in ('openclaw/main','openclaw/batch-1','openclaw/release-5718a6ec')
        or run['event']!='workflow_dispatch' or run['path'].split('@',1)[0]!='.github/workflows/openclaw-artifacts.yml'):
        raise ValueError('publication run does not match the reviewed source/workflow')
    jobs=api('-H','Cache-Control: max-age=0',f'repos/{REPO}/actions/runs/{run_id}/jobs?filter=latest&per_page=100')
    required=[j for j in jobs['jobs'] if j['name']!='publish']
    expected_builds={'build ('+l['label']+')' for l in json.loads((ROOT/'.github/openclaw/variants.json').read_text())['lanes']}
    if ({j['name'] for j in required}!=expected_builds|{'preflight','test','windows-arm64','assemble'}
        or any(j['conclusion']!='success' or j['run_attempt']!=run['run_attempt'] for j in required)):
        raise ValueError('all exact build, test and assembly jobs must pass')
    pending=api('-H','Cache-Control: max-age=0',f'repos/{REPO}/actions/runs/{run_id}/pending_deployments')
    deployment=next(d for d in pending if d['environment']['name']=='openclaw-artifacts')
    if not deployment['current_user_can_approve']:raise ValueError('current identity cannot approve publication')
    receipt=json.dumps({'source':source,'run_id':str(run_id),'run_attempt':str(run['run_attempt']),
        'verified_at':time.time(),'immutable_enabled':True},separators=(',',':'))
    execute('gh','variable','set','OPENCLAW_IMMUTABILITY_RECEIPT','-R',REPO,'--env','openclaw-artifacts','--body',receipt)
    api('-X','POST',f'repos/{REPO}/actions/runs/{run_id}/pending_deployments',
        '-F','environment_ids[]='+str(deployment['environment']['id']),'-f','state=approved',
        '-f','comment=Verified exact build/test jobs and immutable-release setting for this publication.')

def validate_authorization(source):
    # Environment variables become available after the protected job is approved.
    receipt=json.loads(os.environ['IMMUTABILITY_RECEIPT'])
    if (receipt.get('immutable_enabled') is not True or receipt.get('source')!=source
        or receipt.get('run_id')!=os.environ['GITHUB_RUN_ID']
        or receipt.get('run_attempt')!=os.environ['GITHUB_RUN_ATTEMPT']
        or not -60 <= time.time()-receipt['verified_at'] <= 900):
        raise ValueError('fresh maintainer immutability verification for this run is required')

def publish(directory,source):
    manifest=verify(directory,source);tag=manifest['tag']
    validate_authorization(source)
    if os.environ.get('GITHUB_REF') not in ('refs/heads/openclaw/main','refs/heads/openclaw/batch-1','refs/heads/openclaw/release-5718a6ec') or os.environ.get('GITHUB_SHA')!=source:
        raise ValueError('publishing requires reviewed source on an explicitly permitted owned branch')
    # Tag creation fails atomically if the name exists. Neither existing drafts nor releases are resumed.
    api('-X','POST',f'repos/{REPO}/git/refs','-f','ref=refs/tags/'+tag,'-f','sha='+source)
    body=f'OpenClaw-built WebKit at `{source}`. All {len(manifest["artifacts"])} lanes, Linux qualification and native Windows ARM64 engine probes passed.\n\n'+(ROOT/'.github/openclaw/release-notes.md').read_text()
    draft=api('-X','POST',f'repos/{REPO}/releases','-f','tag_name='+tag,'-f','name='+tag,'-f','body='+body,'-F','draft=true')
    release_id=draft['id']
    execute('gh','release','upload',tag,'-R',REPO,*[str(p) for p in sorted(directory.iterdir())])
    # Check uploaded draft asset digests before making it public.
    draft=api(f'repos/{REPO}/releases/{release_id}')
    expected={p.name:'sha256:'+sha(p) for p in directory.iterdir()}
    if {a['name']:a.get('digest') for a in draft['assets']}!=expected:raise ValueError('uploaded asset digest mismatch')
    execute('gh','release','edit',tag,'-R',REPO,'--draft=false')
    released=api(f'repos/{REPO}/releases/tags/{tag}')
    if released.get('immutable') is not True or released.get('draft'):raise ValueError('release did not become immutable')
    # Independent network readback of every public asset, after publication.
    downloaded=directory.parent/'downloaded-release'
    downloaded.mkdir(exist_ok=False)
    execute('gh','release','download',tag,'-R',REPO,'--dir',str(downloaded))
    verify(downloaded,source)
    save(directory.parent/'published-release.json',{'tag':tag,'url':released['html_url'],'immutable':True,'assets':expected,'manifest_url':f'https://github.com/{REPO}/releases/download/{tag}/manifest.json'})

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['assemble','verify','authorize','publish']);p.add_argument('--source',required=True);p.add_argument('--directory',type=Path);p.add_argument('--inputs',type=Path);p.add_argument('--run-id',type=int)
    a=p.parse_args()
    if not re.fullmatch('[0-9a-f]{40}',a.source):raise ValueError('full source SHA required')
    if a.command=='authorize':authorize(a.source,a.run_id)
    elif a.command=='assemble':assemble(a.inputs.resolve(),a.directory.resolve(),a.source)
    elif a.command=='verify':verify(a.directory.resolve(),a.source)
    else:publish(a.directory.resolve(),a.source)

if __name__ == "__main__":
    main()
