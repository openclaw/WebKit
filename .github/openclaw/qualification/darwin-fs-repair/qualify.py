#!/usr/bin/env python3
"""Qualify the measured Darwin fs cutover and its Rust target coverage."""
import hashlib,json,os,pathlib,platform,re,shlex,shutil,subprocess,sys,xml.etree.ElementTree as ET
HERE=pathlib.Path(__file__).resolve().parent
WORK=pathlib.Path(os.environ["PROOF_WORK"])
SOURCE=WORK/"source"
ENGINE=WORK/"engine"
OUT=WORK/"fs-debug-proof"
M=json.loads((HERE/"source-manifest.json").read_text())
MODE=sys.argv[1]
assert MODE in ("rust","darwin")
proof={"passed":False,"mode":MODE,"bun_base":M["bun"],"engine_base":M["engine"],"steps":{}}
applied=False
def sha(p):
 with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()
def git(repo,*args):return subprocess.check_output(["git","-c","gc.auto=0","-c","maintenance.auto=false","-C",str(repo),*args],text=True).strip()
def save():(OUT/"proof.json").write_text(json.dumps(proof,indent=2)+"\n")
def command(name,args,cwd=SOURCE,allow_failure=False):
 print("phase:",name,flush=True)
 log=OUT/(name+".log")
 with log.open("wb") as f:r=subprocess.run(args,cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
 proof["steps"][name]={"argv":args,"exit_code":r.returncode,"log_bytes":log.stat().st_size,"log_sha256":sha(log)}
 if name=="fs-debug":
  binary=SOURCE/"build/fs-debug/bun-debug"
  compile_file=SOURCE/"build/fs-debug/compile_commands.json"
  if binary.is_file():proof["binary"]={"path":"source/build/fs-debug/bun-debug","bytes":binary.stat().st_size,"sha256":sha(binary)}
  if compile_file.is_file():proof["compile_commands_sha256"]=sha(compile_file)
 save()
 assert log.stat().st_size<=64*1024**2,"phase log exceeded bound"
 assert allow_failure or r.returncode==0,(name,r.returncode)
 return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]","",log.read_text(errors="replace"))
def targets(name,selected):
 text=command(name,["bun","run","rust:check-all",*selected])
 expected=selected or M["targets"]
 assert re.findall(r"\[check\] ([\w-]+)",text)==expected
 assert f"{len(expected)} ok, 0 failed, 0 skipped (of {len(expected)})" in text
 proof["steps"][name]["checked_targets"]=expected
 save()
def main():
 global applied
 OUT.mkdir(exist_ok=True);save()
 assert all(not os.environ.get(k) for k in ("CI","BUILDKITE","GITHUB_ACTIONS","GH_TOKEN","GITHUB_TOKEN","ACTIONS_RUNTIME_TOKEN","ACTIONS_ID_TOKEN_REQUEST_TOKEN"))
 assert git(SOURCE,"rev-parse","HEAD")==M["bun"] and git(SOURCE,"rev-parse","HEAD^{tree}")==M["bun_tree"]
 assert git(ENGINE,"rev-parse","HEAD")==M["engine"]
 assert not git(SOURCE,"status","--porcelain") and not git(ENGINE,"status","--porcelain")
 assert git(SOURCE,"diff","--cached","--name-only")==""
 controls=os.environ["QUALIFICATION_CONTROLS"]
 assert re.fullmatch("[0-9a-f]{40}",controls) and git(WORK/"proposal","rev-parse","HEAD")==controls
 proof["controls"]=controls
 assert sha(SOURCE/M["test"]["path"])==M["test"]["sha256"]
 shutil.copyfile(HERE/"source-manifest.json",OUT/"source-manifest.json")
 patch=HERE/"darwin-fs.patch"
 assert sha(patch)==M["patch_sha256"]
 for name,row in M["files"].items():assert sha(SOURCE/name)==row["before"],name
 subprocess.run(["git","-C",str(SOURCE),"apply","--check",str(patch)],check=True)
 subprocess.run(["git","-C",str(SOURCE),"apply",str(patch)],check=True)
 applied=True
 for name,row in M["files"].items():assert sha(SOURCE/name)==row["after"],name
 proof["overlay"]=M["files"];save()
 try:
  command("install-root",["bun","install","--frozen-lockfile"])
  command("rust-toolchain",["rustc","--version"])
  command("rust-components",["rustup","component","add","rust-src","rustfmt"])
  build=["bun","bd","--webkit=local","--webkit-version="+M["engine"],"--aot=on","--ci=off","--buildkite=off","--build-dir=build/fs-debug"]
  if MODE=="rust":
   assert platform.system()=="Linux" and platform.machine()=="x86_64"
   command("rust-target-install",["rustup","target","add",*[t for t in M["targets"] if t!="aarch64-unknown-freebsd"]])
   command("configure-codegen",["bun","scripts/build.ts","--profile=debug",*build[2:],"-j2","--target=codegen","--target=clone-lolhtml","--target=clone-rust-argon2"])
   os.environ["BUN_CODEGEN_DIR"]=str(SOURCE/"build/fs-debug/codegen")
   targets("all-rust-targets",[])
  else:
   assert platform.system()=="Darwin" and platform.machine()=="arm64"
   proof["memory_bytes"]=int(subprocess.check_output(["sysctl","-n","hw.memsize"],text=True))
   proof["disk_free_bytes"]=shutil.disk_usage(WORK).free;save()
   assert proof["memory_bytes"]>=6*1024**3 and proof["disk_free_bytes"]>=20*1024**3,"cold native Debug capacity not admitted"
   command("install-tests",["bun","install","--frozen-lockfile"],SOURCE/"test")
   command("fs-debug",build+["-j1","test","./"+M["test"]["path"],"--max-concurrency=1","--reporter=junit","--reporter-outfile="+str(OUT/"fs.xml")],allow_failure=True)
   xml=OUT/"fs.xml";assert 0<xml.stat().st_size<=8*1024**2
   rows=list(ET.parse(xml).getroot().iter("testcase"));assert rows
   active=[r for r in rows if r.find("skipped") is None]
   assert active
   failed=[{"name":r.get("name"),"classname":r.get("classname"),"time":r.get("time")} for r in rows if r.find("failure") is not None or r.find("error") is not None]
   needed=["realpath reads its path the way Node does","realpath needs no file descriptor","realpath leads from /dev/fd to the open file","realpath resolves what macOS only resolves for open()","realpath preserves a hard-link name when full-path attributes select another link","matches the Node stat and lstat oracle","lstat still throws ENOTDIR"]
   for title in needed:assert any(title in r.get("name","") for r in active),title
   locks=[r.get("name","") for r in active if "preserves process-owned POSIX locks" in r.get("name","")]
   assert len(locks)>=5
   proof["fs"]={"total":len(rows),"executed":len(active),"skipped":len(rows)-len(active),"required":needed,"locks":locks,"junit_sha256":sha(xml),"failed":failed};save()
   compile_file=SOURCE/"build/fs-debug/compile_commands.json"
   assert 0<compile_file.stat().st_size<=64*1024**2
   compiled=json.loads(compile_file.read_text())
   selected=[]
   for row in compiled:
    args=row.get("arguments") or shlex.split(row.get("command",""))
    if "-DASSERT_ENABLED=1" in args and any("-fsanitize=address" in x for x in args):selected.append(row)
   assert selected and any("/engine/" in json.dumps(row) for row in selected)
   (OUT/"debug-compile-inputs.json").write_text(json.dumps(selected[:64],indent=2)+"\n")
   binary=SOURCE/"build/fs-debug/bun-debug"
   assert binary.is_file()
   proof["binary"]={"path":"source/build/fs-debug/bun-debug","bytes":binary.stat().st_size,"sha256":sha(binary)}
   proof["compile_commands_sha256"]=sha(compile_file);save()
   os.environ["BUN_CODEGEN_DIR"]=str(SOURCE/"build/fs-debug/codegen")
   targets("native-rust-target",["aarch64-apple-darwin"])
   command("path-contracts",build+["-j1","test","./"+M["test"]["path"],"-t","realpath needs no file descriptor|realpath reads its path the way Node does","--max-concurrency=1","--reporter=junit","--reporter-outfile="+str(OUT/"path-contracts.xml")])
   cases=list(ET.parse(OUT/"path-contracts.xml").getroot().iter("testcase"))
   active_contracts=[row for row in cases if row.find("skipped") is None]
   assert len(active_contracts)==2 and all(row.find("failure") is None and row.find("error") is None for row in active_contracts)
   proof["path_contracts"]={"passed":True,"names":[row.get("name") for row in active_contracts],"junit_sha256":sha(OUT/"path-contracts.xml")}
   external=list((SOURCE/"build/fs-debug/js").rglob("*.js"))+[SOURCE/"build/fs-debug/codegen/runtime.out.js"]
   assert 0<len(external)<1000 and all(p.is_file() for p in external)
   proof["debug_external_inputs"]={str(p.relative_to(SOURCE)):{"bytes":p.stat().st_size,"sha256":sha(p)} for p in external};save()
  command("rust-format",["rustfmt","--edition","2024","--config","skip_children=true","--check",*M["files"]])
  assert sha(SOURCE/M["test"]["path"])==M["test"]["sha256"]
  if MODE=="darwin":assert proof["steps"]["fs-debug"]["exit_code"]==0 and not proof["fs"]["failed"],"full fs suite remains failed"
  proof["passed"]=True
 finally:
  if applied:
   subprocess.run(["git","-C",str(SOURCE),"apply","--reverse",str(patch)],check=True)
   for name,row in M["files"].items():assert sha(SOURCE/name)==row["before"],name
   assert git(SOURCE,"diff","--name-only")==""
   assert git(SOURCE,"diff","--cached","--name-only")==""
   assert git(SOURCE,"rev-parse","HEAD^{tree}")==M["bun_tree"]
   proof["restored"]=True
  if not proof.get("restored"):proof["passed"]=False
  save()
if __name__=="__main__":
 try:main()
 except BaseException:
  proof["passed"]=False;save();raise
