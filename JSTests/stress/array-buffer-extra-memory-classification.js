//@ runDefault("--useGC=false", "--useJIT=false")

// Disable GC so reconciliation cannot mask an allocation-category error.
const warmBuffer = new ArrayBuffer(0);
arrayBufferMemoryUsage();
const before = arrayBufferMemoryUsage();
const retainedBuffer = new ArrayBuffer(8192);
const after = arrayBufferMemoryUsage();
const payload = after.arrayBufferPayload - before.arrayBufferPayload;
if (payload !== 8192)
    throw new Error(`raw ArrayBuffer payload allocation: ${payload} !== 8192`);
const actual = after.external - before.external;
const expected = 8192 + (after.arrayBufferObjects - before.arrayBufferObjects);
if (actual !== expected)
    throw new Error(`raw external allocation classification: ${actual} !== ${expected}`);
if (retainedBuffer.byteLength !== 8192)
    throw new Error("retained buffer length changed");
