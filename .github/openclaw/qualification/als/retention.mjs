import { AsyncLocalStorage } from 'node:async_hooks';
import { heapStats } from 'bun:jsc';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { setImmediate as turn } from 'node:timers/promises';
const dir = mkdtempSync(join(tmpdir(), 'w137-retention-'));
const als = new AsyncLocalStorage();
const refs = [];
const payloadRefs = [];
const metrics = [];
const bytesPerStore = 128 * 1024;
const batchSize = 256;
const batches = 6;
globalThis.w137ReadId = () => als.getStore()?.id;
function schedule(i) {
  const store = { id: i, payload: new Uint8Array(bytesPerStore).fill(i & 255) };
  refs.push(new WeakRef(store));
  payloadRefs.push(new WeakRef(store.payload), new WeakRef(store.payload.buffer));
  const file = join(dir, i + '.mjs');
  const reject = i % 3 === 0;
  writeFileSync(file, `await Promise.resolve(); const id=globalThis.w137ReadId(); if(id!==${i}) throw Error('context:'+id); ${reject ? "throw Error('expected-rejection');" : 'export const value=1;'}\n`);
  return als.run(store, () => import(pathToFileURL(file).href)).then(
    () => { if (reject) throw Error('missing rejection'); },
    error => { if (!reject || error.message !== 'expected-rejection') throw error; }
  );
}
async function collect() {
  await turn(); Bun.gc(true); await turn(); Bun.gc(true); await turn();
}
try {
  await collect();
  metrics.push({ batch: 0, ...heapStats(), memory: process.memoryUsage() });
  for (let batch = 0; batch < batches; batch++) {
    for (let offset = 0; offset < batchSize; offset += 16)
      await Promise.all(Array.from({ length: 16 }, (_, j) => schedule(batch * batchSize + offset + j)));
    await collect();
    const alive = refs.reduce((n, ref) => n + (ref.deref() !== undefined), 0);
    const payloadsAlive = payloadRefs.reduce((n, ref) => n + (ref.deref() !== undefined), 0);
    metrics.push({ batch: batch + 1, stores: refs.length, alive, payloadsAlive, ...heapStats(), memory: process.memoryUsage() });
    if (alive || payloadsAlive) throw Error(`retained ${alive}/${refs.length} contexts or ${payloadsAlive} payload objects`);
    if (als.getStore() !== undefined) throw Error('context leaked outside import');
  }
  const growth = metrics.at(-1).extraMemorySize - metrics[0].extraMemorySize;
  if (growth > 8 * 1024 * 1024) throw Error('excessive external heap growth: ' + growth);
  console.log(JSON.stringify({ passed: true, bytesPerStore, batchSize, batches, allocatedPayloadBytes: bytesPerStore*batchSize*batches, metrics }, null, 2));
} catch (error) {
  console.log(JSON.stringify({ passed: false, error: String(error), bytesPerStore, batchSize, batches, metrics }, null, 2));
  process.exitCode = 1;
} finally { delete globalThis.w137ReadId; rmSync(dir, {recursive:true,force:true}); }
