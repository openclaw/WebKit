#include <cmakeconfig.h>
#include <JavaScriptCore/JavaScript.h>
#include <JavaScriptCore/APICast.h>
#include <JavaScriptCore/Heap.h>
#include <JavaScriptCore/JSGlobalObject.h>
#include <JavaScriptCore/JSLock.h>
#include <JavaScriptCore/VM.h>
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
    return passed ? 0 : 1;
}
