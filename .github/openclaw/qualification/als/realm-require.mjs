import { AsyncLocalStorage } from 'node:async_hooks';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
const dir = mkdtempSync(join(tmpdir(), 'w137-realm-'));
const als = new AsyncLocalStorage();
const A={name:'A'},B={name:'B'};
globalThis.w137RealmRead=()=>als.getStore();
function eq(a,b,label){if(a!==b)throw Error(label);}
try {
  for (const name of ['a','b','sync']) {
    writeFileSync(join(dir,name+'-leaf.mjs'), 'export const value=globalThis.w137RealmRead();\n');
    writeFileSync(join(dir,name+'.mjs'), `import {value} from './${name}-leaf.mjs'; export const captured=[value,globalThis.w137RealmRead()];\n`);
  }
  const context=vm.createContext({als});
  const run=file=>new vm.Script(`import(${JSON.stringify(pathToFileURL(join(dir,file+'.mjs')).href)})`,{importModuleDynamically:specifier=>import(specifier)}).runInContext(context);
  const [a,b]=await Promise.all([als.run(A,()=>run('a')),als.run(B,()=>run('b'))]);
  for(const x of a.captured)eq(x,A,'realm A');
  for(const x of b.captured)eq(x,B,'realm B');
  const required=als.run(A,()=>createRequire(import.meta.url)(join(dir,'sync.mjs')));
  for(const x of required.captured)eq(x,A,'synchronous require ESM');
  eq(als.getStore(),undefined,'outside realm');
  console.log(JSON.stringify({passed:true,vmGraphs:2,syncRequire:1}));
} finally { delete globalThis.w137RealmRead;rmSync(dir,{recursive:true,force:true}); }
