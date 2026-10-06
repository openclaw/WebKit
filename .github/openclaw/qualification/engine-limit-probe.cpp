#include <cmakeconfig.h>
#include <JavaScriptCore/JavaScript.h>
#include <JavaScriptCore/APICast.h>
#include <JavaScriptCore/Heap.h>
#include <JavaScriptCore/JSGlobalObject.h>
#include <JavaScriptCore/JSLock.h>
#include <JavaScriptCore/VM.h>
#include <JavaScriptCore/HeapObserver.h>
#include <JavaScriptCore/VMTraps.h>
#include <wtf/threads/BinarySemaphore.h>
#include <wtf/MonotonicTime.h>
#include <wtf/WorkQueue.h>
#include <cstdio>
#include <cstdlib>

static void evaluate(JSGlobalContextRef context, const char* text)
{
    auto source = JSStringCreateWithUTF8CString(text);
    JSValueRef exception = nullptr;
    JSEvaluateScript(context, source, nullptr, nullptr, 1, &exception);
    JSStringRelease(source);
    if (exception) {
        std::fprintf(stderr, "probe evaluation failed\n");
        std::exit(2);
    }
}

static bool probe(const char* name, const char* source, size_t heapLimit, size_t nursery, bool expected)
{
    auto group = JSContextGroupCreate();
    auto context = JSGlobalContextCreateInGroup(group, nullptr);
    auto& vm = toJS(context)->vm();
    bool exceeded;
    {
        JSC::JSLockHolder lock(vm);
        vm.heap.collectNow(JSC::Sync, JSC::CollectionScope::Full);
        vm.heap.setWorkerHeapLimits(heapLimit, nursery);
        evaluate(context, source);
        vm.heap.collectNow(JSC::Sync, JSC::CollectionScope::Full);
        exceeded = vm.heap.heapLimitExceeded();
        std::printf("%s managed=%zu exceeded=%d expected=%d\n", name,
            vm.heap.sizeAfterLastFullCollectionExcludingArrayBuffers(), exceeded, expected);
    }
    JSGlobalContextRelease(context);
    JSContextGroupRelease(group);
    return exceeded == expected;
}

class TerminationObserver final : public JSC::HeapObserver {
public:
    explicit TerminationObserver(JSC::VM& vm)
        : m_vm(vm) { }
    void willGarbageCollect() final { }
    void didGarbageCollect(JSC::CollectionScope scope) final
    {
        if (scope != JSC::CollectionScope::Full || !m_vm.heap.heapLimitExceeded())
            return;
        if (++m_breaches != 1) {
            std::fprintf(stderr, "worker termination was not delivered before another full GC\n");
            std::fflush(stderr);
            std::_Exit(1);
        }
        m_firstBreach = WTF::MonotonicTime::now();
        m_vm.notifyNeedTermination();
    }
    JSC::VM& m_vm;
    unsigned m_breaches { 0 };
    WTF::MonotonicTime m_firstBreach;
};

static bool promptTerminationProbe()
{
    auto group = JSContextGroupCreate();
    auto context = JSGlobalContextCreateInGroup(group, nullptr);
    auto& vm = toJS(context)->vm();
    WTF::BinarySemaphore ready, release, done;
    // Keep the signal sender unavailable: GC must deliver the pending trap itself.
    JSC::VMTraps::queue().dispatch([&] {
        ready.signal();
        release.wait();
        done.signal();
    });
    ready.wait();
    bool passed;
    {
        JSC::JSLockHolder lock(vm);
        // Embedders prepare this exception before requesting termination from a GC observer.
        vm.ensureTerminationException();
        vm.heap.collectNow(JSC::Sync, JSC::CollectionScope::Full);
        vm.heap.setWorkerHeapLimits(32 * 1024 * 1024, 4 * 1024 * 1024);
        TerminationObserver observer(vm);
        vm.heap.addObserver(&observer);
        auto source = JSStringCreateWithUTF8CString("let held=[];for(let i=0;i<2000000;i++)held.push({i,a:i+1,b:i+2,c:i+3});");
        JSValueRef exception = nullptr;
        JSEvaluateScript(context, source, nullptr, nullptr, 1, &exception);
        auto end = WTF::MonotonicTime::now();
        JSStringRelease(source);
        vm.heap.removeObserver(&observer);
        release.signal();
        done.wait();
        passed = exception && observer.m_breaches == 1;
        std::printf("termination exception=%d fullGCsAtOrAboveCap=%u latencyMs=%.3f passed=%d\n", !!exception,
            observer.m_breaches, (end - observer.m_firstBreach).milliseconds(), passed);
    }
    JSGlobalContextRelease(context);
    JSContextGroupRelease(group);
    return passed;
}

int main()
{
    constexpr size_t MB = 1024 * 1024;
    bool passed = true;
    passed &= probe("managed", "globalThis.held = new Array(8*1024*1024).fill(7)", 32*MB, 4*MB, true);
    passed &= probe("oversize", "globalThis.held = new Uint8Array(128*1024*1024).fill(7)", 32*MB, 4*MB, false);
    passed &= probe("fast", "globalThis.held=[];for(let i=0;i<65536;i++)held.push(new Uint8Array(2048).fill(7))", 32*MB, 4*MB, false);
    passed &= probe("arraybuffer", "globalThis.held = new Uint8Array(new ArrayBuffer(128*1024*1024)).fill(7)", 32*MB, 4*MB, false);
    passed &= probe("mixed", "globalThis.held=[new Uint8Array(128*1024*1024).fill(7),new Array(8*1024*1024).fill(7)]", 32*MB, 4*MB, true);
    passed &= probe("unlimited-other-vm", "globalThis.held = new Array(8*1024*1024).fill(7)", 0, 0, false);
    passed &= probe("young-only", "globalThis.held = new Array(8*1024*1024).fill(7)", 0, 4*MB, false);
    passed &= probe("near-limit-churn", "globalThis.held = new Array(30*1024*1024/8).fill(7); for(let i=0;i<128;i++){let temporary=new Array(64*1024).fill(i); if(temporary[i]!==i)throw Error('corrupt');}", 32*MB, 4*MB, false);
    passed &= promptTerminationProbe();
    return passed ? 0 : 1;
}
