#!/usr/bin/env python3
"""Require complete upstream-sync and patch evidence before release assembly."""
import json,re,sys
from consumer_identity import engine_input,verify,sha,aot_evidence
from compile_cache import evidence as compile_cache_evidence
from compare_fork_ci import validate_arm
from pathlib import Path
from xml.etree import ElementTree
root=Path(sys.argv[1]);out=root/'sync'
selected=json.loads((out/'selected.json').read_text())
rows=json.loads((out/'results.json').read_text())
historical=set(json.loads((Path(__file__).parent/'selected.json').read_text()))|set(json.loads((Path(__file__).parent/'sync/selected.json').read_text()))
assert len(historical)==82 and len(selected)==len(set(selected))==85 and historical<=set(selected)
observed=validate_arm(out,selected)
assert observed['all_passed'],'sync CI failures'
assert {'test/js/web/atomics.test.ts','test/js/bun/wasm/compile-rss.test.ts'}<=set(selected)
counts={}
for name,minimum in [('quic-sni',19),('memory-release',3),('webkit-upgrade',11),('proxy',4),('resource-limits',16),('namespace',41),('inspector',78),('als-suites',223),('stack-positions',343),('stack-minifier',68),('arraybuffer',19),('worker-statistics',7),('arraybuffer-native',1),('arraybuffer-serializer',60),('inspection-idle',1),('bake-builtin',1),('bigint-matchers',2),('lazy-process-builtins',3),('bigint-serialization',18),('untrimmed-collator',1)]:
    text=(out/(name+'.log')).read_text()
    passes=re.findall(r'(\d+) pass',text)
    assert passes and int(passes[-1])>=minimum,name+' incomplete'
    assert re.search(r'\b0 fail\b',text),name+' failed'
    if name=='quic-sni':assert int(passes[-1])==19,'QUIC SNI selection drift'
    if name=='webkit-upgrade':assert int(passes[-1])==11,'WebKit upgrade selection drift'
    if name=='untrimmed-collator':assert int(passes[-1])==1,'collator selection drift'
    if name in ('quic-sni','memory-release','webkit-upgrade','bigint-matchers','bigint-serialization','lazy-process-builtins','untrimmed-collator'):assert not re.search(r'\b[1-9]\d* skip\b',text),name+' tests skipped'
    counts[name]=int(passes[-1])
sqlite_cases = {
    'sqlite-bigint.xml': ('test/js/node/sqlite/node-sqlite.test.ts', {
        'rejects oversized BigInt with ERR_INVALID_ARG_VALUE',
        "bind error messages match node's exactly (trailing period)",
        'database-level defaults flow to prepared statements',
    }),
    'sqlite-bigint-node.xml': ('test/js/node/test/parallel/test-sqlite-statement-sync.js', {
        'BigInts support can be toggled',
        'BigInt is required for reading large integers',
        'BigInts are returned when input is true',
    }),
}
sqlite_count = 0
for report, (file, expected) in sqlite_cases.items():
    cases = list(ElementTree.parse(out/report).iter('testcase'))
    assert cases and all(case.find('failure') is None and case.find('error') is None for case in cases),report+' failed'
    selected_cases = [case for case in cases if case.get('name') in expected]
    assert len(selected_cases)==len(expected)==3 and {case.get('name') for case in selected_cases}==expected,report+' selection drift'
    assert all(case.find('skipped') is not None for case in cases if case.get('name') not in expected),report+' unexpected case'
    for case in selected_cases:
        assert case.find('skipped') is None,report+' selected case skipped'
        location = Path(case.attrib['file'])
        assert location == (root/'bun'/file if location.is_absolute() else Path(file)),report+' wrong source file'
    sqlite_count += len(selected_cases)
assert sqlite_count==6,'SQLite BigInt qualification incomplete'
counts['sqlite-bigint']=sqlite_count
mock_files = {
    'test/aot/a-commonjs-file-mocked-again-is-seen-by-who-required-it.test.ts',
    'test/aot/the-default-of-a-mocked-built-in-module-is-the-mocks.test.ts',
    'test/aot/mock-module-of-compiled-modules.test.ts',
}
mock_cases = list(ElementTree.parse(out/'aot-module-mocks.xml').iter('testcase'))
assert mock_cases and all(case.find(tag) is None for case in mock_cases for tag in ('failure','error','skipped')),'AOT module mocks failed or skipped'
mock_sources = set()
for case in mock_cases:
    location = Path(case.attrib['file'])
    mock_sources.add(str(location.relative_to(root/'bun') if location.is_absolute() else location))
assert mock_sources==mock_files,'AOT module mock source selection drift'
counts['aot-module-mocks']=len(mock_cases)
assert (out/'untrimmed-getters.log').read_text().strip()=='native URL getters passed','native URL getter smoke incomplete'
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
measured=engine_input(artifacts/'bun-webkit-linux-amd64-aot.tar.gz',artifacts/'bun-webkit-linux-amd64-aot.manifest.json',sys.argv[2])
identity=verify(root,measured,receipt,Path(sys.argv[5]))
aot=aot_evidence(root,root,identity)
identity_sha=sha(receipt)
compatibility=json.loads((root/'compatibility-gate.json').read_text())
assert compatibility['passed'] and compatibility['source']==sys.argv[2]
assert compatibility['candidate_identity_sha256']==identity_sha
assert compatibility['memory_tests']==3 and compatibility['startup'] is True
record={'passed':True,'source':sys.argv[2],'candidate_identity_sha256':identity_sha,
        'historical_selected_files':82,'selected_files':len(selected),'result_rows':len(rows),'regressions':0,'tests':counts,
        'gc_progress':gc_progress,'aot':aot,'compile_cache':compile_cache_evidence(out/'module-junit.xml'),
        'invocation':observed['invocation']}
(root/'sync-gate.json').write_text(json.dumps(record,indent=2)+'\n')
gate=json.loads((root/'gate.json').read_text())
assert gate['candidate_identity_sha256']==identity_sha
gate['upstream_sync']=record;gate['engine']=engine;gate['compatibility']=compatibility
(root/'gate.json').write_text(json.dumps(gate,indent=2)+'\n')
