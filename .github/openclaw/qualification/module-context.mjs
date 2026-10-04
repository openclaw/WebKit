import { AsyncLocalStorage } from 'node:async_hooks';
import { mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire, registerHooks } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';

const cases = ['static', 'dynamic', 'nested', 'tla', 'tla-dependency', 'cjs', 'cjs-direct', 'concurrent-distinct', 'concurrent-shared', 'concurrent-shared-reverse', 'concurrent-overlap', 'cached', 'unscoped', 'throw'];
const variant = process.argv[2] === 'matrix' ? undefined : process.argv[2];
const nativeHooks = process.argv.includes('--native-hooks');
if (!variant) {
  const results = cases.map(name => {
    const child = spawnSync(process.execPath, [fileURLToPath(import.meta.url), name, ...process.argv.slice(3)], { encoding: 'utf8', timeout: 30000 });
    let result;
    try { result = JSON.parse(child.stdout); }
    catch { result = { error: 'Child did not emit JSON', stdout: child.stdout, spawnError: child.error?.message }; }
    return { variant: name, exitCode: child.status, signal: child.signal, stderr: child.stderr, ...result };
  });
  await new Promise(resolve => process.stdout.write(JSON.stringify({ runtime: process.version, bun: process.versions.bun, results }, null, 2) + '\n', resolve));
  process.exit(results.every(row => row.exitCode === 0) ? 0 : 1);
}
if (!cases.includes(variant)) throw new Error('Unknown variant: ' + variant);

const root = realpathSync(mkdtempSync(path.join(tmpdir(), 'w136-als-')));
const als = new AsyncLocalStorage();
const trace = [];
const record = (stage, file, parent) => trace.push({ stage, file, store: als.getStore() ?? null, ...(parent ? { parent } : {}) });
globalThis.w136Record = record;
globalThis.w136Store = () => als.getStore() ?? null;
const write = (file, source) => {
  const name = path.join(root, file);
  mkdirSync(path.dirname(name), { recursive: true });
  writeFileSync(name, source);
};
const body = file => `globalThis.w136Record('body', ${JSON.stringify(file)}); export const store = globalThis.w136Store();`;
const normalize = file => file.replace(pathToFileURL(root).href + '/', '').replace(root + '/', '');
const interesting = file => file.startsWith(root) || file.startsWith(pathToFileURL(root).href) || file.startsWith('./');
const importFile = file => import(pathToFileURL(path.join(root, file)).href);
let hook;
let values;
let error;
const failures = [];
try {
  write('package.json', '{"type":"module"}');
  als.run('REGISTRATION', () => {
    if (process.versions.bun && !nativeHooks) {
      Bun.plugin({ name: 'w136-observe-module-context', setup(build) {
        build.onResolve({ filter: /.*/, namespace: 'file' }, ({ path: file, importer }) => {
          if (interesting(file)) record('resolve', normalize(file), importer && normalize(importer));
        });
        build.onLoad({ filter: /\.mjs$/, namespace: 'file' }, ({ path: file }) => {
          if (interesting(file)) record('load', normalize(file));
          return { contents: readFileSync(file, 'utf8'), loader: 'js' };
        });
      } });
    } else {
      hook = registerHooks({
        resolve(file, context, next) {
          if (interesting(file)) record('resolve', normalize(file), context.parentURL && normalize(context.parentURL));
          return next(file, context);
        },
        load(file, context, next) {
          if (interesting(file)) record('load', normalize(file));
          return next(file, context);
        },
      });
    }
  });
  write('leaf.mjs', body('leaf'));
  write('nested.mjs', body('nested'));
  let entry = body('entry');
  if (variant === 'static' || variant === 'unscoped' || variant === 'cached')
    entry = `import './leaf.mjs'; ${entry}`;
  if (variant === 'dynamic' || variant === 'nested') {
    if (variant === 'nested') write('leaf.mjs', `${body('leaf')} await import('./nested.mjs'); globalThis.w136Record('after-nested', 'leaf');`);
    entry = `${entry} await import('./leaf.mjs'); globalThis.w136Record('after-dynamic', 'entry');`;
  }
  if (variant === 'tla') entry = `${entry} await Promise.resolve(); globalThis.w136Record('after-await', 'entry'); await new Promise(r => setImmediate(r)); globalThis.w136Record('after-immediate', 'entry');`;
  if (variant === 'tla-dependency') {
    write('leaf.mjs', `${body('leaf')} await new Promise(r => setImmediate(r)); globalThis.w136Record('after-await', 'leaf');`);
    entry = `import './leaf.mjs'; ${entry}`;
  }
  if (variant === 'cjs' || variant === 'cjs-direct') {
    write('leaf.cjs', `globalThis.w136Record('body', 'cjs'); module.exports = globalThis.w136Store();`);
    entry = `import {createRequire} from 'node:module'; ${entry} export const cjsStore = createRequire(import.meta.url)('./leaf.cjs');`;
  }
  if (variant === 'throw') entry = `${entry} throw new Error('expected-w136');`;
  write('entry.mjs', entry);
  const run = (store, file = 'entry.mjs') => als.run(store, async () => {
    record('caller-before', file);
    try {
      const module = await importFile(file);
      record('caller-after', file);
      return { store: module.store, cjsStore: module.cjsStore };
    } catch (e) {
      record('caller-catch', file);
      if (variant !== 'throw' || e.message !== 'expected-w136') throw e;
      return { error: e.message };
    }
  });
  if (variant === 'cjs-direct') {
    values = [als.run('A', () => createRequire(import.meta.url)(path.join(root, 'leaf.cjs')))];
  } else if (variant === 'concurrent-distinct') {
    for (const name of ['a', 'b']) {
      write(`${name}/leaf.mjs`, `${body(name + '/leaf')} await new Promise(r => setImmediate(r)); globalThis.w136Record('after-await', '${name}/leaf');`);
      write(`${name}/entry.mjs`, `import './leaf.mjs'; ${body(name + '/entry')} await import('./nested.mjs');`);
      write(`${name}/nested.mjs`, body(name + '/nested'));
    }
    values = await Promise.all([run('A', 'a/entry.mjs'), run('B', 'b/entry.mjs')]);
  } else if (variant.startsWith('concurrent-shared') || variant === 'concurrent-overlap') {
    let release;
    let started;
    globalThis.w136Gate = new Promise(r => { release = r; });
    const ready = new Promise(r => { started = r; });
    globalThis.w136Started = started;
    write('leaf.mjs', `${body('leaf')} globalThis.w136Started(); await globalThis.w136Gate; globalThis.w136Record('after-await', 'leaf');`);
    write('entry.mjs', `import './leaf.mjs'; ${body('entry')}`);
    let otherStarted;
    const otherReady = new Promise(r => { otherStarted = r; });
    globalThis.w136OtherStarted = otherStarted;
    write('ready.mjs', `${body('ready')} globalThis.w136OtherStarted();`);
    write('other.mjs', `import './leaf.mjs'; import './ready.mjs'; ${body('other')}`);
    const stores = variant.endsWith('reverse') ? ['B', 'A'] : ['A', 'B'];
    const first = run(stores[0]);
    await Promise.race([ready, first]);
    const second = run(stores[1], variant === 'concurrent-overlap' ? 'other.mjs' : 'entry.mjs');
    if (variant === 'concurrent-overlap') await Promise.race([otherReady, second]);
    release();
    values = await Promise.all([first, second]);
  } else if (variant === 'cached') {
    values = [await run('A'), await run('B')];
  } else {
    values = [await run(variant === 'unscoped' ? undefined : 'A')];
  }
  record('outside', 'runner');
  const first = variant === 'unscoped' ? null : variant.endsWith('reverse') ? 'B' : 'A';
  let rootResolves = 0;
  let callerBefore = 0;
  let callerAfter = 0;
  const repeated = variant.startsWith('concurrent-shared') || variant === 'cached';
  for (const event of trace) {
    let expected = first;
    if (event.stage === 'outside') expected = null;
    else if (variant === 'concurrent-distinct') expected = (event.file.startsWith('b/') || event.parent?.startsWith('b/')) ? 'B' : 'A';
    else if (variant === 'concurrent-overlap' && (['other.mjs', 'ready', 'ready.mjs'].includes(event.file) || event.parent === 'other.mjs')) expected = 'B';
    else if (repeated) {
      if (event.stage === 'resolve' && event.file === 'entry.mjs' && rootResolves++ > 0) expected = first === 'A' ? 'B' : 'A';
      if (event.stage === 'caller-before' && callerBefore++ > 0) expected = first === 'A' ? 'B' : 'A';
      if (event.stage === 'caller-after' && callerAfter++ > 0) expected = first === 'A' ? 'B' : 'A';
    }
    if (event.store !== expected) failures.push({ ...event, expected });
  }
  const bodyFiles = variant === 'concurrent-distinct' ? ['a/leaf', 'a/entry', 'a/nested', 'b/leaf', 'b/entry', 'b/nested']
    : variant === 'cjs-direct' ? ['cjs']
    : variant === 'cjs' ? ['entry', 'cjs']
    : variant === 'concurrent-overlap' ? ['leaf', 'entry', 'ready', 'other']
    : variant === 'nested' ? ['entry', 'leaf', 'nested']
    : ['tla', 'throw'].includes(variant) ? ['entry'] : ['leaf', 'entry'];
  for (const file of bodyFiles) {
    const count = trace.filter(e => e.stage === 'body' && e.file === file).length;
    if (count !== 1) failures.push({ stage: 'body-count', file, count, expected: 1 });
  }
  for (const stage of ['resolve', 'load']) {
    for (const file of bodyFiles.map(file => file === 'cjs' ? 'leaf.cjs' : file + '.mjs')) {
      // Keep require(CJS) native; the plugin's JS source loader changes its format.
      if (stage === 'load' && file.endsWith('.cjs') && process.versions.bun && !nativeHooks) continue;
      const seen = trace.some(event => {
        if (event.stage !== stage) return false;
        const resolved = event.file.startsWith('./')
          ? path.posix.normalize(path.posix.join(path.posix.dirname(event.parent ?? ''), event.file))
          : event.file;
        return resolved === file;
      });
      if (!seen) failures.push({ stage: 'missing-hook', hook: stage, file });
    }
  }
  if (failures.length) process.exitCode = 1;
} catch (e) {
  error = { name: e.name, message: e.message, stack: e.stack };
  process.exitCode = 1;
} finally {
  hook?.deregister();
  rmSync(root, { recursive: true, force: true });
  console.log(JSON.stringify({ variant, values, error, failures, trace }));
}
