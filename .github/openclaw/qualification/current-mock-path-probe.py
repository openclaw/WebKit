import hashlib,json,os,subprocess
from pathlib import Path
root=Path("/work")
out=root/"mock-path-proof"
out.mkdir(exist_ok=True)
exe=root/"retained-bun"
probe=root/"probe"
probe.mkdir(exist_ok=True)
source=root/"source"
assert subprocess.check_output(["git","-C",str(source),"rev-parse","HEAD"],text=True).strip()=="c6a7bf9d8dc4d44db9f826e47a5ae7645ea6e8c9"
# Match tempDirWithBunTypes rather than substituting diagnostic ambient types.
subprocess.run([str(exe),"install","--frozen-lockfile","--ignore-scripts"],cwd=source,check=True)
types=probe/"node_modules/@types"
types.mkdir(parents=True,exist_ok=True)
(types/"bun").symlink_to(source/"packages/bun-types",target_is_directory=True)
(probe/"tsconfig.json").write_text(json.dumps({"compilerOptions":{"strict":True,"target":"ESNext","module":"Preserve","moduleResolution":"bundler","allowImportingTsExtensions":True,"noEmit":True,"types":["bun"]}}))
(probe/"subject.ts").write_text('export default {label:"kept"}; export let value=1; export function bump(){value++;}\n')
# Keep the failing boundary; print facts instead of weakening its expected contract.
(probe/"one.test.ts").write_text(r"""
import {mock,test} from "bun:test";
import * as subject from "./subject.ts";
function info(x:any){return {keys:Object.keys(x),ownKeys:Reflect.ownKeys(x).map(String),marker:x.__esModule,hasMarker:Object.hasOwn(x,"__esModule"),hasDefault:Object.hasOwn(x,"default"),defaultType:typeof x.default,prototype:Object.prototype.toString.call(x)};}
test("mock path probe",async()=>{
 const first=await import("bun:jsc");
 console.log("FIRST",JSON.stringify(info(first)));
 const exports={...first,heapSize:()=>73};
 console.log("FACTORY",JSON.stringify(info(exports)));
 mock.module("bun:jsc",()=>exports);
 const hostPath=import.meta.dir+"/written-"+process.pid+".mjs";
 await Bun.write(hostPath,'export const required=require("./subject.ts");export const mocked=require("bun:jsc");export const again=require("bun:jsc");');
 const host=await import(hostPath);
 const current=await import("bun:jsc");
 console.log("CURRENT",JSON.stringify(info(current)));
 console.log("REQUIRED",JSON.stringify(info(host.required)));
 console.log("MOCKED",JSON.stringify(info(host.mocked)));
 console.log("IDENTITIES",JSON.stringify({mockIsImport:host.mocked===current,mockIsFactory:host.mocked===exports,mockIsImportDefault:host.mocked===current.default,mockDefaultIsImportDefault:host.mocked.default===current.default,cached:host.again===host.mocked,heap:host.mocked.heapSize(),currentHeap:current.heapSize()}));
 const path=import.meta.dir+"/forward-"+process.pid+".cjs";
 await Bun.write(path,'module.exports=require("./subject.ts");');
 const forwarded=await import(path);
 console.log("FORWARDED",JSON.stringify({facade:forwarded.default===host.required,moduleExports:forwarded["module.exports"]===host.required,innerDefault:forwarded.default.default===subject.default}));
});
""")
proof={"diagnostic_only":True,"passed":False,"artifact":13120786072,"artifact_run":41396456930,"binary":{"bytes":exe.stat().st_size,"sha256":hashlib.file_digest(exe.open("rb"),"sha256").hexdigest()},"steps":{}}
(out/"proof.json").write_text(json.dumps(proof,indent=2)+"\n")
for name,args in [("ordinary",["test","one.test.ts"]),("aot",["test","--debug-aot","one.test.ts"])]:
 with (out/(name+".log")).open("wb") as log:
  result=subprocess.run([str(exe),*args],cwd=probe,stdout=log,stderr=subprocess.STDOUT)
 data=(out/(name+".log")).read_bytes()
 assert len(data)<=1024**2
 proof["steps"][name]={"exit_code":result.returncode,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
 (out/"proof.json").write_text(json.dumps(proof,indent=2)+"\n")
 assert result.returncode==0
 assert b"FIRST " in data and b"IDENTITIES " in data and b"FORWARDED " in data
proof["passed"]=True
(out/"proof.json").write_text(json.dumps(proof,indent=2)+"\n")
