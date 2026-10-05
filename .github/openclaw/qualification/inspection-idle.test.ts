import { expect, test } from "bun:test";
import { Worker } from "node:worker_threads";

test("worker inspection preserves idle purge and atomic notifications", async () => {
  const shared = new SharedArrayBuffer(16);
  const flag = new Int32Array(shared);
  const messages: any[] = [];
  let failure: Error | undefined;
  const worker = new Worker(`
    const { parentPort, workerData } = require("node:worker_threads");
    const { heapStats } = require("bun:jsc");
    const flag = new Int32Array(workerData);
    const held = new Uint8Array(16 * 1024 * 1024).fill(7);
    const purges = () => heapStats().mimalloc.purge_calls;
    function allocate() {
      let strings = [];
      for (let i = 0; i < 100000; i++) strings.push(Buffer.alloc(900 + (i % 5) * 8, 97).toString("latin1"));
      strings = strings.filter((_, i) => i % 64 === 0);
      Bun.gc(true);
      return strings;
    }
    let strings = allocate();
    let before = purges();
    for (let stable = 0, tries = 0; stable < 3 && tries < 50; tries++) {
      const start = performance.now();
      while (performance.now() - start < 60);
      const now = purges();
      stable = now === before ? stable + 1 : 0;
      before = now;
    }
    Atomics.store(flag, 1, 1);
    let released = 0;
    for (let i = 0; i < 10 && released < 500; i++) {
      if (Atomics.wait(flag, 0, 0, 250) !== "timed-out") throw new Error("unexpected purge wait result");
      released = purges() - before;
    }
    parentPort.postMessage({ kind: "purge", released, retained: strings.length });
    Atomics.wait(flag, 3, 0, 10000);
    const waits = [];
    for (let i = 0; i < 8; i++) {
      strings = allocate();
      Atomics.store(flag, 0, 0);
      Atomics.store(flag, 1, i + 2);
      const start = performance.now();
      const result = Atomics.wait(flag, 0, 0, 10000);
      waits.push({ result, elapsed: performance.now() - start });
    }
    parentPort.postMessage({ kind: "done", waits, bytes: held.byteLength, retained: strings.length });
    // Keep the VM alive until every requested inspection has settled.
    Atomics.wait(flag, 2, 0, 10000);
  `, { eval: true, workerData: shared });
  worker.on("message", message => messages.push(message));
  worker.on("error", error => { failure = error; });
  const deadline = performance.now() + 25_000;
  async function waitFor<T>(read: () => T): Promise<NonNullable<T>> {
    for (;;) {
      if (failure) throw failure;
      const result = read();
      if (result) return result as NonNullable<T>;
      if (performance.now() >= deadline) throw new Error("worker inspection/notification stalled");
      await Bun.sleep(1);
    }
  }
  function checkStatistics(stats: { external_memory: number; used_heap_size: number; total_heap_size: number }) {
    expect(stats.external_memory).toBeGreaterThanOrEqual(16 * 1024 * 1024);
    expect(stats.total_heap_size).toBeGreaterThanOrEqual(stats.used_heap_size);
  }
  async function inspect() {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([
        worker.getHeapStatistics(),
        new Promise<never>((_, reject) => {
          timer = setTimeout(() => reject(new Error("worker inspection did not settle")), 5000);
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  }
  let inspections = 0;
  try {
    await waitFor(() => Atomics.load(flag, 1) === 1);
    for (let round = 0; round < 4; round++) {
      await Bun.sleep(round === 0 ? 80 : 60);
      const rows = await Promise.all(Array.from({ length: 8 }, () => inspect()));
      rows.forEach(checkStatistics);
      inspections += rows.length;
    }
    const purge = await waitFor(() => messages.find(message => message.kind === "purge"));
    expect(purge.released).toBeGreaterThanOrEqual(500);
    expect(purge.retained).toBe(1563);
    Atomics.store(flag, 3, 1);
    Atomics.notify(flag, 3);
    for (let i = 0; i < 8; i++) {
      await waitFor(() => Atomics.load(flag, 1) === i + 2);
      await Bun.sleep(100 + i);
      const pending = inspect();
      Atomics.store(flag, 0, 1);
      Atomics.notify(flag, 0);
      checkStatistics(await pending);
      inspections++;
    }
    const done = await waitFor(() => messages.find(message => message.kind === "done"));
    expect(done.waits).toHaveLength(8);
    for (const wait of done.waits) {
      expect(["ok", "not-equal"]).toContain(wait.result);
      expect(wait.elapsed).toBeLessThan(5000);
    }
    expect(done.bytes).toBe(16 * 1024 * 1024);
    console.log(JSON.stringify({ purges: purge.released, inspections, notificationRaces: done.waits.length }));
  } finally {
    Atomics.store(flag, 3, 1);
    Atomics.notify(flag, 3);
    Atomics.store(flag, 2, 1);
    Atomics.notify(flag, 2);
    await worker.terminate();
  }
}, 30_000);
