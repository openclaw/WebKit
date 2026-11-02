import hashlib,json,os,re,subprocess,time,xml.etree.ElementTree as ET
from pathlib import Path
R=Path("/work");S=R/"source";O=R/"debug-replay-proof";O.mkdir(exist_ok=True)
H=R/"controls/.github/openclaw/qualification/aot-debug-repair";E=R/"retained-bun"
M=json.loads((H/"source-manifest.json").read_text());A=[]
P={"passed":False,"diagnostic_only":True,"source_run":41403914224,"steps":{}}
def sha(f):
 with f.open("rb") as s:return hashlib.file_digest(s,"sha256").hexdigest()
def save():(O/"proof.json").write_text(json.dumps(P,indent=2)+"\n")
def git(*a):return subprocess.check_output(["git","-C",str(S),*a],text=True).strip()
def run(n,args,cwd=S):
 start=time.monotonic()
 with (O/(n+".log")).open("wb") as f:r=subprocess.run(args,cwd=cwd,stdout=f,stderr=subprocess.STDOUT,env={**os.environ,"BUN_DEBUG_QUIET_LOGS":"1"})
 f=O/(n+".log");assert f.stat().st_size<64*1024**2
 P["steps"][n]={"argv":args,"exit_code":r.returncode,"seconds":time.monotonic()-start,"bytes":f.stat().st_size,"sha256":sha(f)};save();return r.returncode
def main():
 assert all(not os.environ.get(k) for k in ("CI","BUILDKITE","GITHUB_ACTIONS","GH_TOKEN","GITHUB_TOKEN","ACTIONS_RUNTIME_TOKEN","ACTIONS_ID_TOKEN_REQUEST_TOKEN"))
 assert git("rev-parse","HEAD")==M["bun"] and git("rev-parse","HEAD^{tree}")==M["bun_tree"] and not git("status","--porcelain")
 assert sha(E)=="a9ebf9297110b64a8a85fdfee07a21be873e14a4af67225f9bdc7899123fe4d1" and E.stat().st_size==1700143416
 P["binary"]={"bytes":E.stat().st_size,"sha256":sha(E)};save()
 try:
  for n,g in M["groups"].items():
   if g["repo"]!="source":continue
   patch=H/n;assert sha(patch)==g["sha256"]
   for path,h in g["files"].items():assert sha(S/path)==h["before"],path
   subprocess.run(["git","-C",str(S),"apply","--check",str(patch)],check=True);subprocess.run(["git","-C",str(S),"apply",str(patch)],check=True);A.append(n)
   for path,h in g["files"].items():assert sha(S/path)==h["after"],path
  P["source_files"]={path:sha(S/path) for n in A for path in M["groups"][n]["files"]};save()
  assert run("install-root",[str(E),"install","--frozen-lockfile"])==0
  assert run("install-tests",[str(E),"install","--frozen-lockfile"],S/"test")==0
  for n,f,title in [
   ("plugin-gc","./test/js/bun/plugin/plugins.test.ts","keeps the object alive across a GC so require"),
   ("cache-natural","./test/js/node/module/node-module-module.test.js","compile cache persists correctly on natural exit with uncached modules"),
   ("cache-deferred","./test/js/node/module/node-module-module.test.js","compile cache wakes an idle loop for deferred modules"),
   ("module-long-path","./test/js/node/module/node-module-module.test.js","module APIs don't crash on paths longer than a path buffer"),
   ("strip-heavy","./test/js/node/module/node-module-module.test.js","strips declaration-heavy generated source"),
   ("vm-pressure","./test/js/node/vm/vm.test.ts","shared source buffers survive compilation-cache eviction"),
   ("aot-json","./test/aot/run-aot.test.ts","a module that the constant parts of a dynamic path match is compiled"),
   ("aot-mock","./test/aot/a-mock-of-a-built-in-module-that-import-alone-reaches-is-what-runs.test.ts","a module written at run time requires a module of native code that compiled code has imported and mocked")]:
   run(n,[str(E),"test",f,"-t",title,"--max-concurrency=1","--reporter=junit","--reporter-outfile="+str(O/(n+".xml"))])
   xml=O/(n+".xml")
   if xml.is_file():
    cases=list(ET.parse(xml).getroot().iter("testcase"));active=[r for r in cases if r.find("skipped") is None]
    P["steps"][n]["junit"]={"sha256":sha(xml),"active":[{"name":r.get("name"),"file":r.get("file"),"failed":r.find("failure") is not None or r.find("error") is not None} for r in active]}
    P["steps"][n]["selected_contract_passed"]=P["steps"][n]["exit_code"]==0 and len(active)==(2 if n=="vm-pressure" else 1) and all(r.find("failure") is None and r.find("error") is None for r in active)
    save()
  text=(S/"test/js/node/module/node-module-module.test.js").read_text();start=text.index('  describe("compile cache exit modes"')
  m=re.search(r'"main\.cjs": `(.*?)`,',text[start:],re.S);assert m
  child=m.group(1).replace("${count}","2000").replace("${((count - 1) * count) / 2 + count * 63}","2125000").replace(chr(92)*2,chr(92));assert "${" not in child
  fixture=R/"cache-phase";fixture.mkdir();functions="\n".join("function f%d(x) { return x + %d; }"%(i,i) for i in range(64))
  for i in range(2000):(fixture/("mod%d.cjs"%i)).write_text(functions+"\nmodule.exports = f63(%d);"%i)
  (fixture/"main.cjs").write_text(child)
  phase=S/".openclaw-cache-phase.ts";assert not phase.exists()
  phase.write_text(r"""
import {bunEnv} from "./test/harness.ts";
import {writeFileSync,readFileSync} from "node:fs";
const root="/work/cache-phase",out="/work/debug-replay-proof",rows=[];
for(const [name,args,disable] of [
 ["cache-enabled-natural",["main.cjs","natural"],false],
 ["cache-enabled-warm",["-e",'for(let i=0;i<2000;i++) require("./mod"+i+".cjs");require("node:module").flushCompileCache();console.log("flushed");'],false],
 ["cache-disabled-natural",["main.cjs","natural"],true],
] as const){
 const start=performance.now();let firstStdoutMs:number|null=null;
 const proc=Bun.spawn([process.execPath,...args],{cwd:root,env:{...bunEnv,NODE_COMPILE_CACHE:root+(disable?"/disabled-cc":"/enabled-cc"),NODE_DISABLE_COMPILE_CACHE:disable?"1":undefined,NODE_DEBUG_NATIVE:name==="cache-enabled-warm"?"COMPILE_CACHE":undefined},stdout:"pipe",stderr:"pipe"});
 const samples:{ms:number,state:string,utime:string,stime:string,threads:string,wchan:string}[]=[];
 const sample=setInterval(()=>{try{const s=readFileSync("/proc/"+proc.pid+"/stat","utf8"),v=s.slice(s.lastIndexOf(")")+2).split(" ");samples.push({ms:performance.now()-start,state:v[0],utime:v[11],stime:v[12],threads:v[17],wchan:readFileSync("/proc/"+proc.pid+"/wchan","utf8")});}catch{}},1000);
 let killed=false;const bound=setTimeout(()=>{killed=true;proc.kill("SIGKILL");},180000);
 const stdoutTask=(async()=>{let s="";for await(const c of proc.stdout){if(firstStdoutMs===null)firstStdoutMs=performance.now()-start;s+=Buffer.from(c).toString();if(s.length>1024*1024)throw Error("stdout bound");}return s;})();
 try{const [stdout,stderr,exitCode]=await Promise.all([stdoutTask,new Response(proc.stderr).text(),proc.exited]);if(stderr.length>64*1024*1024)throw Error("stderr bound");writeFileSync(out+"/"+name+".stdout",stdout);writeFileSync(out+"/"+name+".stderr",stderr);rows.push({name,firstStdoutMs,exitMs:performance.now()-start,exitCode,killed,originalTestBudgetMs:30000,diagnosticOnly:true,samples});writeFileSync(out+"/cache-phases.json",JSON.stringify(rows,null,2)+"\n");}
 finally{clearTimeout(bound);clearInterval(sample);await proc[Symbol.asyncDispose]();}
}
""")
  try:run("cache-phases",[str(E),str(phase)])
  finally:phase.unlink()
  P["completed"]=True
 finally:
  for n in reversed(A):
   subprocess.run(["git","-C",str(S),"apply","--reverse",str(H/n)],check=True)
   for path,h in M["groups"][n]["files"].items():assert sha(S/path)==h["before"],path
  assert not git("diff","--name-only") and not git("diff","--cached","--name-only")
  P["restored"]=True;save()
main()
