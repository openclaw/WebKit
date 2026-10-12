//@ runDefault("--compileMainScriptAheadOfTime=1")
function trace(name, work) { return work(); }
function load() { return { snapshot: { config: 7 }, other: { x: 8 } }; }
const exportsModule = { load, apply: x=>x, create:()=>42 };
async function bootstrap(input) {
    try {
        const { opts } = input;
        const captured = await Promise.resolve({x: 2});
        const modulePromise = trace('module', () => Promise.resolve().then(() => exportsModule));
        const loaded = await trace('snapshot', () => load({captured}));
        const overridden = opts.seed ? { config: loaded.snapshot.config } : await trace('seed',()=>({config:loaded.snapshot.config}));
        const { create } = await modulePromise;
    } finally { await Promise.resolve(); }
}
let failure;
bootstrap({opts:{}}).catch(error => { failure = error; });
drainMicrotasks();
if (failure) throw failure;
