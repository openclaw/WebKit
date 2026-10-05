#!/usr/bin/env python3
"""Bounded synthetic-only replay; retain stacks, never retain or upload raw cores."""
import argparse, concurrent.futures, hashlib, json, os, pathlib, platform, resource, subprocess, sys, time
p=argparse.ArgumentParser()
for key in ['baseline','candidate','fixture','output','cores']:p.add_argument('--'+key,type=pathlib.Path,required=True)
a=p.parse_args();assert sys.platform=='linux' and platform.machine()=='aarch64'
a.output.mkdir(parents=True,exist_ok=True);a.cores.mkdir(parents=True,exist_ok=True)
for name in ['home','tmp','state']:(a.output/name).mkdir(mode=0o700)
env={'PATH':'/usr/bin:/bin','LANG':'C','HOME':str(a.output/'home'),'TMPDIR':str(a.output/'tmp'),'OPENCLAW_STATE_DIR':str(a.output/'state')}
_,hard=resource.getrlimit(resource.RLIMIT_CORE);resource.setrlimit(resource.RLIMIT_CORE,(hard,hard))
flags=['--validateOptions=true','--useFTLJIT=false','--useFunctionDotArguments=true','--validateExceptionChecks=true','--useDollarVM=true','--maxPerThreadStackUsage=1572864','--useConcurrentJIT=false','--thresholdForJITAfterWarmUp=100','--scribbleFreeCells=true','--collectContinuously=true','--useGenerationalGC=false','--verifyGC=true']
binary_digests={r:hashlib.sha256(getattr(a,r).read_bytes()).hexdigest() for r in ["baseline","candidate"]}
rows=[]
for arm in ['baseline','candidate']:
 binary=getattr(a,arm).resolve()
 def run(i):
  log=a.output/f'{arm}-{i:04d}.log';start=time.monotonic()
  with log.open('w') as stream:
   proc=subprocess.Popen([str(binary),*flags,str(a.fixture.resolve())],stdout=stream,stderr=subprocess.STDOUT,env=env)
   try:code=proc.wait(timeout=30)
   except subprocess.TimeoutExpired:proc.kill();proc.wait();code=124
  record={'arm':arm,'index':i,'exit':code,'elapsed_s':time.monotonic()-start,'pid':proc.pid,'log':log.name}
  core=a.cores/f'core.{proc.pid}'
  if core.exists():
   try:
    stack=a.output/f'{arm}-{i:04d}-stack.log'
    with stack.open('w') as stream:
     gdb=subprocess.run(['gdb','-nx','-q','-batch','-ex','set print frame-arguments none','-ex','thread apply all bt',str(binary),str(core)],stdout=stream,stderr=subprocess.STDOUT,timeout=60,env=env)
    record.update(stack=stack.name,gdb_exit=gdb.returncode)
   except subprocess.TimeoutExpired:record['gdb_timeout']=True
   finally:core.unlink(missing_ok=True)
  if code==0 and log.stat().st_size==0:log.unlink();record['log']=None
  return record
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for offset in range(0,1000,4):
   batch=list(pool.map(run,range(offset,offset+4)));rows.extend(batch)
   (a.output/'paired-gc-replay.json').write_text(json.dumps({'diagnostic_only':True,'qualifies_product':False,'baseline_source':'f1e1ca1156c8cb3b468bec0e1989fbfa08899661','candidate_source':'32804d651e88b0667cf9831dc8bbe7eb250bc3c1','args':flags,'fixture_sha256':hashlib.sha256(a.fixture.read_bytes()).hexdigest(),'binary_sha256':binary_digests,'observations':rows},indent=2)+'\n')
   if any(item['exit']!=0 for item in batch):break
 print(json.dumps({'arm':arm,'runs':sum(r['arm']==arm for r in rows),'failures':sum(r['arm']==arm and r['exit']!=0 for r in rows)}),flush=True)
assert not list(a.cores.glob('core.*')), 'unprocessed raw core remains outside artifact path'
