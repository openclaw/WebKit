//@ requireOptions("--useDollarVM=true", "--useGenerationalGC=true", "--forceMiniVMMode=false")

function assert(value, message) {
    if (!value)
        throw new Error(message);
}
function profile() { return JSON.parse(getHeapAllocationProfile()); }
function sites(head, name) {
    let total = head.callFrame.functionName === name ? head.selfSize : 0;
    for (const child of head.children)
        total += sites(child, name);
    return total;
}
function validate(p) {
    const nodes = new Map();
    let bytes = 0;
    function walk(node) {
        assert(!nodes.has(node.id), "duplicate node id");
        nodes.set(node.id, node);
        assert(node.selfSize >= 0, "negative self size");
        assert(typeof node.callFrame.scriptId === "string", "script id");
        assert(typeof node.callFrame.url === "string", "url");
        assert(Number.isInteger(node.callFrame.lineNumber), "line number");
        bytes += node.selfSize;
        node.children.forEach(walk);
    }
    walk(p.head);
    let previous = 0, sampled = 0;
    for (const sample of p.samples) {
        assert(nodes.has(sample.nodeId), "dangling sample");
        assert(sample.size > 0, "sample size");
        assert(sample.ordinal > previous, "sample ordinal");
        previous = sample.ordinal;
        sampled += sample.size;
    }
    assert(Math.abs(bytes - sampled) < Math.max(1, bytes * 1e-12), "tree/sample totals differ");
}
let keep;
function allocateLeft(n) {
    const values = [];
    for (let i = 0; i < n; ++i)
        values.push({ index: i, a: i + 1, b: i + 2 });
    keep = values;
}
function allocateRight(n) {
    const values = [];
    for (let i = 0; i < n; ++i)
        values.push([i, i + 1, i + 2, i + 3]);
    keep = values;
}
noInline(allocateLeft);
noInline(allocateRight);
// Compile and populate free lists before enabling the sampler.
for (let i = 0; i < 100; ++i) {
    allocateLeft(200);
    allocateRight(200);
}
keep = null;
fullGC();
for (let repeat = 0; repeat < 3; ++repeat) {
    startHeapAllocationSampling(512, true, true);
    allocateLeft(10000);
    allocateRight(10000);
    keep = null;
    fullGC();
    const p = profile();
    validate(p);
    assert(sites(p.head, "allocateLeft") > 100000, "missing optimized object allocations");
    assert(sites(p.head, "allocateRight") > 100000, "missing array allocations");
    const oldOrdinals = new Set(p.samples.map(s => s.ordinal));
    allocateLeft(1000);
    const live = profile();
    assert(live.samples.some(s => !oldOrdinals.has(s.ordinal)), "live profile did not advance");
    stopHeapAllocationSampling();
    assert(getHeapAllocationProfile() === null, "stop left sampler running");
}
for (const collect of [fullGC, edenGC]) {
    for (const [major, minor] of [[false, false], [false, true], [true, false], [true, true]]) {
        keep = null;
        fullGC();
        startHeapAllocationSampling(512, major, minor);
        allocateLeft(10000);
        const before = sites(profile().head, "allocateLeft");
        assert(before > 100000, "retained samples missing");
        keep = null;
        collect();
        const after = sites(profile().head, "allocateLeft");
        // Mini VM mode disables generational GC even for an explicit edenGC request.
        const full = collect === fullGC || !$vm.useJIT();
        const included = full ? major : minor;
        assert(included ? after === before : after < before / 10, "collection inclusion flag " + JSON.stringify({ major, minor, full, before, after }));
        validate(profile());
        stopHeapAllocationSampling();
    }
}
// Large auxiliary allocations and growth must remain safe across reallocations and GC.
startHeapAllocationSampling(32768, true, true);
keep = [];
for (let i = 0; i < 100000; ++i)
    keep.push(i);
fullGC();
validate(profile());
keep = new Array(1000000).fill(1);
const large = profile();
validate(large);
assert(large.samples.some(sample => sample.size > 4000000), "large auxiliary allocation missing");
keep = null;
fullGC();
validate(profile());
stopHeapAllocationSampling();

const shortStringInputs = Array.from({ length: 20000 }, (_, i) => '"' + '\\u0061'.repeat(36) + '\\u' + i.toString(16).padStart(4, '0') + '"');
function parseShortStrings() {
    keep = new Array(shortStringInputs.length);
    for (let i = 0; i < shortStringInputs.length; ++i)
        keep[i] = JSON.parse(shortStringInputs[i]);
}
function parseLongStrings() {
    keep = new Array(2048);
    for (let i = 0; i < keep.length; ++i)
        keep[i] = JSON.parse('"' + '\\u0061'.repeat(4096) + '"');
}
noInline(parseShortStrings);
noInline(parseLongStrings);
for (const [allocate, minimum] of [[parseShortStrings, 1000000], [parseLongStrings, 8000000]]) {
    startHeapAllocationSampling(256, true, true);
    allocate();
    keep = null;
    fullGC();
    const strings = profile();
    validate(strings);
    assert(sites(strings.head, allocate.name) > minimum, "string payload allocations missing: " + allocate.name);
    stopHeapAllocationSampling();
}
