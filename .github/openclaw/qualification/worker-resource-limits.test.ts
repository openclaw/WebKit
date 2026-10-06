import { describe, expect, test } from "bun:test";
import { bunEnv, bunExe } from "harness";
import { Worker } from "node:worker_threads";

describe("resourceLimits", () => {
  test("reads numeric getters in Node order and converts the second value", async () => {
    const calls: string[] = [];
    const values = { maxOldGenerationSizeMb: 64, maxYoungGenerationSizeMb: 16, codeRangeSizeMb: 32, stackSizeMb: 2 };
    const limits = {};
    for (const key of Object.keys(values)) {
      let count = 0;
      Object.defineProperty(limits, key, { get() { calls.push(key); return ++count === 1 ? values[key] : String(values[key]); } });
    }
    const worker = new Worker("", { eval: true, resourceLimits: limits });
    try {
      expect(calls).toEqual(Object.keys(values).flatMap(key => [key, key]));
      expect(worker.resourceLimits).toEqual(values);
    } finally {
      await worker.terminate();
    }
  });

  test("propagates a second getter exception unchanged", async () => {
    const error = new Error("second resource-limit getter");
    let reads = 0;
    let worker: Worker | undefined;
    let caught: unknown;
    try {
      worker = new Worker("", { eval: true, resourceLimits: { get maxOldGenerationSizeMb() { if (++reads === 2) throw error; return 64; } } });
    } catch (value) {
      caught = value;
    } finally {
      await worker?.terminate();
    }
    expect(caught).toBe(error);
    expect(reads).toBe(2);
  });

  async function runLimitedWorker(limits: object, body: string, env: Record<string, string> = {}) {
    await using child = Bun.spawn({
      cmd: [bunExe(), "-e", `
        const {Worker,resourceLimits}=require('node:worker_threads');
        const w=new Worker(${JSON.stringify("const {parentPort,resourceLimits}=require('node:worker_threads');parentPort.postMessage({limits:resourceLimits});parentPort.once('message',()=>{" + body + "});")},{eval:true,resourceLimits:${JSON.stringify(limits)}});
        const result={main:resourceLimits,before:w.resourceLimits,events:[],messages:[]};
        w.on('online',()=>{result.online=w.resourceLimits;});
        w.on('message',m=>{result.messages.push(m);if(m.limits)w.postMessage('go');});
        w.on('error',e=>{result.events.push('error');result.error={name:e.name,code:e.code,message:e.message,limits:w.resourceLimits};});
        w.on('exit',code=>{result.events.push('exit');result.exit=code;result.after=w.resourceLimits;console.log(JSON.stringify(result));});
      `],
      env: { ...bunEnv, ...env },
      stdout: "pipe",
      stderr: "pipe",
    });
    const [stdout, stderr, exitCode] = await Promise.all([child.stdout.text(), child.stderr.text(), child.exited]);
    expect({ stderr, exitCode }).toEqual({ stderr: "", exitCode: 0 });
    return JSON.parse(stdout);
  }

  test("reports requested values in the parent and worker, then clears on exit", async () => {
    const limits = { maxYoungGenerationSizeMb: 16, maxOldGenerationSizeMb: 64, codeRangeSizeMb: 32, stackSizeMb: 2 };
    expect(await runLimitedWorker(limits, "")).toEqual({
      main: {}, before: limits, online: limits, messages: [{ limits }], events: ["exit"], exit: 0, after: {},
    });
  });

  test.each([{}, { maxOldGenerationSizeMb: "32", maxYoungGenerationSizeMb: true, stackSizeMb: null }])("resolves defaults by online and ignores non-number fields: %j", async requested => {
    const result = await runLimitedWorker(requested, "");
    const limits = { maxYoungGenerationSizeMb: 192, maxOldGenerationSizeMb: 4096, codeRangeSizeMb: 0, stackSizeMb: 4 };
    expect({ online: result.online, inside: result.messages[0].limits, after: result.after, exit: result.exit }).toEqual({ online: limits, inside: limits, after: {}, exit: 0 });
  });

  const withoutIdleGC = {
    BUN_GC_TIMER_DISABLE: "1",
    BUN_IDLE_GC_SECONDS: "0",
    BUN_DISABLE_STOP_IF_NECESSARY_TIMER: "1",
    BUN_GC_RUNS_UNTIL_SKIP_RELEASE_ACCESS: "0",
  };

  test.concurrent("allows natural young collections below the old heap limit", async () => {
    const result = await runLimitedWorker(
      { maxOldGenerationSizeMb: 64, maxYoungGenerationSizeMb: 1 },
      `
        const { GCProfiler } = require('node:v8');
        const profiler = new GCProfiler();
        profiler.start();
        let checksum = 0;
        for (let round = 0; round < 1000; ++round) {
          globalThis.batch = new Array(8192).fill(round);
          checksum += batch[(round * 31) % batch.length];
        }
        const records = profiler.stop().statistics;
        parentPort.postMessage({ checksum, young: records.filter(row => row.gcType === 'Scavenge').length });
      `,
      withoutIdleGC,
    );
    expect(result.messages.at(-1).checksum).toBe(499500);
    expect(result.messages.at(-1).young).toBeGreaterThan(1);
    expect({ events: result.events, exit: result.exit }).toEqual({ events: ["exit"], exit: 0 });
  });

  test.concurrent("verifies an old-limit crossing found by Eden before an idle worker parks", async () => {
    const result = await runLimitedWorker(
      { maxOldGenerationSizeMb: 16, maxYoungGenerationSizeMb: 64 },
      `
        const { edenGC } = require('bun:jsc');
        parentPort.on('message', () => {});
        globalThis.held = new Array(80000);
        Bun.gc(true);
        let checksum = 0;
        for (let i = 0; i < held.length; ++i) {
          const text = String(i).padStart(220, 'x');
          checksum += text.charCodeAt(0) + text.charCodeAt(219);
          held[i] = text;
        }
        parentPort.postMessage(checksum);
        edenGC();
      `,
      withoutIdleGC,
    );
    expect(result.messages.at(-1)).toBe(13800000);
    expect({ events: result.events, code: result.error?.code, exit: result.exit }).toEqual({
      events: ["error", "exit"],
      code: "ERR_WORKER_OUT_OF_MEMORY",
      exit: 1,
    });
  });

  test("terminates only the worker with the Node heap OOM event contract", async () => {
    const result = await runLimitedWorker({ maxOldGenerationSizeMb: 32, maxYoungGenerationSizeMb: 4 },
      "globalThis.held=[];for(let i=0;i<64;i++)held.push(new Array(1024*1024).fill(i));parentPort.postMessage('survived');");
    expect({ events: result.events, error: result.error, exit: result.exit, after: result.after, messages: result.messages.length }).toEqual({
      events: ["error", "exit"],
      error: { name: "Error", code: "ERR_WORKER_OUT_OF_MEMORY", message: "Worker terminated due to reaching memory limit: JS heap out of memory", limits: {} },
      exit: 1, after: {}, messages: 1,
    });
    expect((await runLimitedWorker({ maxOldGenerationSizeMb: 64 }, "parentPort.postMessage('alive');")).messages.at(-1)).toBe("alive");
  });

  test.each(["large", "small", "materialized", "shared"])("excludes %s external backing stores", async kind => {
    const allocation = kind === "small"
      ? "for(let i=0;i<65536;i++)held.push(new Uint8Array(2048).fill(7));"
      : kind === "materialized"
        ? "for(let i=0;i<32;i++)held.push(new Uint8Array(new ArrayBuffer(4*1024*1024)).fill(7));"
        : kind === "shared"
          ? "for(let i=0;i<32;i++)held.push(new Uint8Array(new SharedArrayBuffer(4*1024*1024)).fill(7));"
          : "for(let i=0;i<32;i++)held.push(new Uint8Array(4*1024*1024).fill(7));";
    const result = await runLimitedWorker({ maxOldGenerationSizeMb: 32, maxYoungGenerationSizeMb: 4 },
      "globalThis.held=[];" + allocation + "Bun.gc(true);parentPort.postMessage(held.reduce((n,a)=>n+a.byteLength,0));");
    expect({ events: result.events, exit: result.exit, bytes: result.messages.at(-1) }).toEqual({ events: ["exit"], exit: 0, bytes: 128 * 1024 * 1024 });
  });

  test("external allocations do not hide managed heap growth", async () => {
    const result = await runLimitedWorker({ maxOldGenerationSizeMb: 32, maxYoungGenerationSizeMb: 4 },
      "globalThis.held=[new Uint8Array(128*1024*1024).fill(7)];Bun.gc(true);for(let i=0;i<64;i++)held.push(new Array(1024*1024).fill(i));");
    expect({ code: result.error?.code, exit: result.exit }).toEqual({ code: "ERR_WORKER_OUT_OF_MEMORY", exit: 1 });
  });

  test("near-limit managed churn survives with external backing stores", async () => {
    const result = await runLimitedWorker({ maxOldGenerationSizeMb: 32, maxYoungGenerationSizeMb: 4 },
      "globalThis.held=new Array(22*1024*1024/8).fill(7);globalThis.external=new Uint8Array(64*1024*1024);external[0]=11;let sum=0;for(let i=0;i<128;i++){let temporary=new Array(64*1024).fill(i);sum+=temporary[i];}parentPort.postMessage({sum,length:held.length,value:held[0],external:external.byteLength,byte:external[0]});");
    expect({ events: result.events, exit: result.exit, value: result.messages.at(-1) }).toEqual({
      events: ["exit"], exit: 0, value: { sum: 8128, length: 2883584, value: 7, external: 67108864, byte: 11 },
    });
  });

  test("a young-only limit sizes the nursery without capping retained objects", async () => {
    const result = await runLimitedWorker({ maxYoungGenerationSizeMb: 4 },
      "globalThis.held=[];for(let i=0;i<8;i++)held.push(new Array(1024*1024).fill(i));Bun.gc(true);parentPort.postMessage('retained');");
    expect({ events: result.events, exit: result.exit, value: result.messages.at(-1) }).toEqual({ events: ["exit"], exit: 0, value: "retained" });
  });

  test("stackSizeMb changes the worker stack capacity", async () => {
    const body = "let depth=0;function recur(){depth++;return recur()+1;}try{recur();}catch(e){parentPort.postMessage({depth,name:e.name});}";
    const small = await runLimitedWorker({ stackSizeMb: 1 }, body);
    const large = await runLimitedWorker({ stackSizeMb: 4 }, body);
    expect({ small: small.exit, large: large.exit, smallError: small.messages.at(-1).name, largeError: large.messages.at(-1).name }).toEqual({ small: 0, large: 0, smallError: "RangeError", largeError: "RangeError" });
    expect(large.messages.at(-1).depth).toBeGreaterThan(small.messages.at(-1).depth * 2);
  });

  test("a vm timeout remains usable before a worker heap OOM", async () => {
    const result = await runLimitedWorker({ maxOldGenerationSizeMb: 32, maxYoungGenerationSizeMb: 4 },
      "try{require('node:vm').runInNewContext('while(true){}',{},{timeout:10});}catch(e){parentPort.postMessage(e.code);}globalThis.held=[];for(let i=0;i<64;i++)held.push(new Array(1024*1024).fill(i));");
    expect({ timeout: result.messages[1], code: result.error?.code, exit: result.exit }).toEqual({ timeout: "ERR_SCRIPT_EXECUTION_TIMEOUT", code: "ERR_WORKER_OUT_OF_MEMORY", exit: 1 });
  });
});
