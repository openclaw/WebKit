function equal(actual, expected, label) {
    if (actual !== expected)
        throw new Error(`${label}: ${actual} !== ${expected}`);
}

function memoryUsage() {
    var result = arrayBufferMemoryUsage();
    // JIT and native object allocations are independent of the backing payload contract.
    result.external = result.arrayBufferPayload;
    return result;
}
var emptyBefore = arrayBufferMemoryUsage();
var emptyShared = new SharedArrayBuffer(0);
var emptyAfter = arrayBufferMemoryUsage();
if (emptyAfter.arrayBufferObjects <= emptyBefore.arrayBufferObjects)
    throw new Error("missing native ArrayBuffer object accounting");
equal(emptyAfter.external - emptyBefore.external,
    emptyAfter.arrayBufferObjects - emptyBefore.arrayBufferObjects, "native object external charge");
equal(emptyAfter.arrayBuffers, emptyBefore.arrayBuffers, "empty backing payload");

var retained = [];
function allocate(size) { return new Uint8Array(size); }
noInline(allocate);
for (var i = 0; i < testLoopCount; ++i)
    retained.push(allocate(8));
fullGC();

var before = memoryUsage();
var sizes = [0, 17, 512, 1000, 1001, 4096];
var bytes = 0;
for (var i = 0; i < sizes.length; ++i) {
    retained.push(allocate(sizes[i]));
    bytes += sizes[i];
    equal(memoryUsage().arrayBuffers - before.arrayBuffers, bytes, "allocation");
}
var allocated = memoryUsage();
equal(allocated.external - before.external, bytes, "external allocation");
for (var view of retained)
    view.buffer;
equal(memoryUsage().arrayBuffers, allocated.arrayBuffers, "materialization");
edenGC();
equal(memoryUsage().arrayBuffers, allocated.arrayBuffers, "eden");
fullGC();
equal(memoryUsage().arrayBuffers, allocated.arrayBuffers, "full");

var rabBefore = memoryUsage();
var resizable = new ArrayBuffer(4096, { maxByteLength: 32768 });
equal(memoryUsage().arrayBuffers, rabBefore.arrayBuffers, "resizable allocator");
equal(memoryUsage().external - rabBefore.external, 4096, "resizable external");
resizable.resize(16384);
equal(memoryUsage().external - rabBefore.external, 16384, "grow");
resizable.resize(1024);
equal(memoryUsage().external - rabBefore.external, 1024, "shrink");
var fixed = resizable.transferToFixedLength();
equal(resizable.byteLength, 0, "detach");
equal(memoryUsage().arrayBuffers - rabBefore.arrayBuffers, 1024, "fixed transfer allocator");
equal(memoryUsage().external - rabBefore.external, 1024, "fixed transfer external");
var transferred = fixed.transfer();
equal(memoryUsage().arrayBuffers - rabBefore.arrayBuffers, 1024, "same-size transfer allocator");
equal(memoryUsage().external - rabBefore.external, 1024, "same-size transfer external");

var sharedBefore = memoryUsage();
var shared = new SharedArrayBuffer(8192);
equal(memoryUsage().arrayBuffers - sharedBefore.arrayBuffers, 8192, "shared allocator");
equal(memoryUsage().external, sharedBefore.external, "shared external");
var growable = new SharedArrayBuffer(4096, { maxByteLength: 32768 });
growable.grow(16384);
equal(memoryUsage().arrayBuffers - sharedBefore.arrayBuffers, 8192, "growable allocator");
equal(memoryUsage().external, sharedBefore.external, "growable external");

// Reconcile dead young vectors before their cells are reused, including oversize finalizers.
var liveBytes = memoryUsage().arrayBuffers;
var temporary = [];
function garbage() {
    for (var i = 0; i < 100; ++i) {
        temporary.push(new Uint8Array(512));
        temporary.push(new Uint8Array(2048));
    }
}
noInline(garbage);
garbage();
equal(memoryUsage().arrayBuffers - liveBytes, 256000, "young vector allocation");
var youngAllocations = temporary.map(view => ({ view: new WeakRef(view), bytes: view.byteLength }));
temporary = null;
$262.clearKeptObjects();
edenGC();
// Continuous collection can promote these vectors while temporary still owns them.
var remainingYoungBytes = liveTrackedBytes(youngAllocations);
equal(memoryUsage().arrayBuffers, liveBytes + remainingYoungBytes, "young vector reclamation");
$262.clearKeptObjects();
fullGC();
remainingYoungBytes = liveTrackedBytes(youngAllocations);
equal(memoryUsage().arrayBuffers, liveBytes + remainingYoungBytes, "oversize finalization");

// Keep earlier transient survivors in the oracle instead of freezing their charge in the baseline.
var oldBefore = liveBytes;
var oldViews = [];
for (var i = 0; i < 128; ++i)
    oldViews.push(new Uint8Array(512));
var oldViewAllocations = oldViews.map(view => ({ view: new WeakRef(view), bytes: view.byteLength }));
var trackedAllocations = youngAllocations.concat(oldViewAllocations);
function liveTrackedBytes(allocations) {
    var bytes = 0;
    for (var entry of allocations) {
        if (entry.view.deref() || (entry.buffer && entry.buffer.deref()))
            bytes += entry.bytes;
    }
    return bytes;
}
fullGC();
for (var round = 0; round < 8; ++round) {
    oldViewAllocations[round].buffer = new WeakRef(oldViews[round].buffer);
    temporary = [];
    garbage();
    for (var index = 0; index < temporary.length; ++index)
        trackedAllocations.push({ view: new WeakRef(temporary[index]), bytes: temporary[index].byteLength });
    var trackedBytes = liveTrackedBytes(trackedAllocations);
    equal(memoryUsage().arrayBuffers, oldBefore + trackedBytes, "old and young vectors");
    temporary = null;
    $262.clearKeptObjects();
    edenGC();
    // Compare with the collector's live targets, including any promoted temporaries.
    trackedBytes = liveTrackedBytes(trackedAllocations);
    equal(memoryUsage().arrayBuffers, oldBefore + trackedBytes, "eden matches live old and young storage");
}
oldViews = null;
$262.clearKeptObjects();
fullGC();
trackedBytes = liveTrackedBytes(trackedAllocations);
equal(memoryUsage().arrayBuffers, oldBefore + trackedBytes, "full collection prunes dead old views");
equal(testArrayBufferInspectionWhileWaiting(), true, "inspection of a confirmed parked waiter");

function near(actual, expected, label) {
    if (Math.abs(actual - expected) > 65536)
        throw new Error(`${label}: ${actual} is not near ${expected}`);
}
var warmMemory = new WebAssembly.Memory({ initial: 1, maximum: 256 });
warmMemory.buffer;
fullGC();
var wasmBefore = memoryUsage();
var memory = new WebAssembly.Memory({ initial: 64, maximum: 256 });
near(memoryUsage().external - wasmBefore.external, 4 * 1024 * 1024, "wasm allocation");
equal(memoryUsage().arrayBuffers, wasmBefore.arrayBuffers, "wasm allocation origin");
var memoryBuffer = memory.buffer;
near(memoryUsage().external - wasmBefore.external, 4 * 1024 * 1024, "wasm exposure");
memory.grow(64);
near(memoryUsage().external - wasmBefore.external, 8 * 1024 * 1024, "wasm grow");
memoryBuffer = memory.buffer;
memory = null;
fullGC();
near(memoryUsage().external - wasmBefore.external, 8 * 1024 * 1024, "retained wasm backing store");
if (memoryUsage().heapUsed - wasmBefore.heapUsed > 1024 * 1024)
    throw new Error("wasm payload entered JavaScript heap");
var sharedMemory = new WebAssembly.Memory({ initial: 64, maximum: 256, shared: true });
sharedMemory.buffer;
sharedMemory.grow(64);
fullGC();
near(memoryUsage().external - wasmBefore.external, 8 * 1024 * 1024, "shared wasm excluded");
equal(memoryUsage().arrayBuffers, wasmBefore.arrayBuffers, "shared wasm allocation origin");

// Mode loads in the interpreter and JITs must still guard resizable view bounds.
var modeBuffer = new ArrayBuffer(32, { maxByteLength: 128 });
var modeAuto = new Uint8Array(modeBuffer);
var modeFixed = new Uint8Array(modeBuffer, 0, 32);
var modeData = new DataView(modeBuffer);
modeAuto[16] = 73;
function readModeView(view) { return view[16]; }
noInline(readModeView);
for (var i = 0; i < testLoopCount; ++i) {
    equal(readModeView(modeAuto), 73, "resizable auto view");
    equal(readModeView(modeFixed), 73, "resizable fixed view");
}
modeBuffer.resize(8);
equal(modeAuto.length, 8, "resized auto length");
equal(modeFixed.length, 0, "resized fixed bounds");
equal(readModeView(modeAuto), undefined, "resized auto indexed bounds");
equal(readModeView(modeFixed), undefined, "resized fixed indexed bounds");
var modeRangeError = false;
try { modeData.getUint8(16); } catch (error) { modeRangeError = error instanceof RangeError; }
equal(modeRangeError, true, "resized DataView bounds");
var modeShared = new SharedArrayBuffer(16, { maxByteLength: 128 });
var modeSharedView = new Uint8Array(modeShared);
modeShared.grow(32);
equal(modeSharedView.length, 32, "grown shared auto length");
equal(modeSharedView[24], 0, "grown shared indexed bounds");
