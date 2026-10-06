//@ runDefault("--useDollarVM=true", "--useConcurrentGC=false")

$vm.setWorkerHeapLimits(64 * 1024 * 1024, 256 * 1024);
const allocatedBefore = $vm.heapTotalBytesAllocated();
let sawEden = false;
let checksum = 0;
const rounds = Math.max(80, Math.min(testLoopCount, 160));
for (let round = 0; round < rounds; ++round) {
    globalThis.lastBatch = new Array(2048).fill(round);
    checksum += globalThis.lastBatch[round % 2048];
    sawEden ||= $vm.lastGCWasFull() === false;
}
if (checksum !== rounds * (rounds - 1) / 2)
    throw new Error("allocation workload result changed");
if ($vm.heapTotalBytesAllocated() - allocatedBefore < 1024 * 1024)
    throw new Error("allocation workload did not exercise collection pressure");
if (!sawEden)
    throw new Error("worker limits forced every allocation collection full");
if ($vm.workerHeapLimitExceeded())
    throw new Error("temporary allocation exceeded a live-heap limit");
globalThis.lastBatch = null;
$vm.setWorkerHeapLimits(0, 0);
gc();
