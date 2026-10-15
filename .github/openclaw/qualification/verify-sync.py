#!/usr/bin/env python3
"""Require complete upstream-sync and patch evidence before release assembly."""
import json,re,sys
from consumer_identity import engine_input,verify,sha
from pathlib import Path
root=Path(sys.argv[1]);out=root/'sync'
selected=json.loads((out/'selected.json').read_text())
rows=json.loads((out/'results.json').read_text())
historical=set(json.loads((Path(__file__).parent/'selected.json').read_text()))|set(json.loads((Path(__file__).parent/'sync/selected.json').read_text()))
assert len(historical)==82 and len(selected)==len(set(selected))==85 and historical<=set(selected)
assert set(selected)<={r['testPath'] for r in rows}
assert rows and all(r['ok'] for r in rows),'sync CI failures'
assert {'test/js/web/atomics.test.ts','test/js/bun/wasm/compile-rss.test.ts'}<=set(selected)
counts={}
for name,minimum in [('memory-release',3),('proxy',4),('resource-limits',16),('namespace',41),('inspector',78),('als-suites',223),('stack-positions',343),('stack-minifier',68),('arraybuffer',19),('worker-statistics',7),('arraybuffer-native',1),('arraybuffer-serializer',60),('inspection-idle',1)]:
    text=(out/(name+'.log')).read_text()
    passes=re.findall(r'(\d+) pass',text)
    assert passes and int(passes[-1])>=minimum,name+' incomplete'
    assert re.search(r'\b0 fail\b',text),name+' failed'
    if name=='memory-release':assert not re.search(r'\b[1-9]\d* skip\b',text),'memory tests skipped'
    counts[name]=int(passes[-1])
for name in ['als-plugin','als-native','als-gc']:
    matrix=json.loads((out/(name+'.json')).read_text())['results']
    assert len(matrix)==14 and all(r['exitCode']==0 for r in matrix),name
assert json.loads((out/'als-retention.json').read_text())['passed'] is True
cache=json.loads((out/'stack-cache.json').read_text())
assert len(cache)==4 and all(r['matches']==r['total']==56 for r in cache if r['arm']=='candidate')
assert cache[-1]['arm']=='candidate' and cache[-1]['repeat']=='warm' and cache[-1]['cache_hit_proven'] is True
assert len((out/'engine-limits.log').read_text().splitlines())==9
gc_progress=json.loads((out/'engine-gc-progress.json').read_text())
assert all(gc_progress[key] is True for key in ['passed','passiveCollectorObserved','completedBeforeHelperRelease','rootsSurvived']),'passive collector did not progress'
assert all(gc_progress[key] is False for key in ['lateWaitStallObserved','timedOut']),'passive collector stalled'
assert type(gc_progress['helperCount']) is int and gc_progress['helperCount']>0,'GC helper precondition missing'
engine=json.loads((root/'engine-gate.json').read_text())
assert engine['passed'] and engine['source']==sys.argv[2]
receipt=Path(sys.argv[4]);artifacts=Path(sys.argv[3])
measured=engine_input(artifacts/'bun-webkit-linux-amd64.tar.gz',artifacts/'bun-webkit-linux-amd64.manifest.json',sys.argv[2])
verify(root,measured,receipt,Path(sys.argv[5]))
identity_sha=sha(receipt)
compatibility=json.loads((root/'compatibility-gate.json').read_text())
assert compatibility['passed'] and compatibility['source']==sys.argv[2]
assert compatibility['candidate_identity_sha256']==identity_sha
assert compatibility['memory_tests']==3 and compatibility['startup'] is True
record={'passed':True,'source':sys.argv[2],'candidate_identity_sha256':identity_sha,
        'historical_selected_files':82,'selected_files':len(selected),'result_rows':len(rows),'regressions':0,'tests':counts,
        'gc_progress':gc_progress}
(root/'sync-gate.json').write_text(json.dumps(record,indent=2)+'\n')
gate=json.loads((root/'gate.json').read_text())
assert gate['candidate_identity_sha256']==identity_sha
gate['upstream_sync']=record;gate['engine']=engine;gate['compatibility']=compatibility
(root/'gate.json').write_text(json.dumps(gate,indent=2)+'\n')
