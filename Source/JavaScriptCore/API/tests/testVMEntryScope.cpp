/*
 * Copyright (C) 2026 Peter Steinberger. All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDER AND ITS CONTRIBUTORS
 * ``AS IS'' AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
 * TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR ITS
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 * EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
 * OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
 * WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
 * OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
 * ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

// Exercises conservative-stack storage and the real microtask scope lifecycle.
#include "config.h"

#include "APICast.h"
#include "InitializeThreading.h"
#include "JSGlobalObject.h"
#include "JSMicrotaskDispatcher.h"
#include "JSLock.h"
#include "JavaScript.h"
#include "MicrotaskQueueInlines.h"
#include "VM.h"
#include "VMEntryScopeInlines.h"
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <memory>
#include <new>
#include <optional>
#include <type_traits>
#include <wtf/Function.h>
#include <wtf/MainThread.h>
#include <wtf/TZoneMallocInlines.h>

using namespace JSC;

// The control compiles against the original engine too. It restores the exact
// optional owner used at both checkpoint sites, with the same word assertions.
#if defined(TEST_VM_ENTRY_SCOPE_OPTIONAL_CONTROL) && TEST_VM_ENTRY_SCOPE_OPTIONAL_CONTROL
using ScopeOwner = std::optional<VMEntryScope>;
static constexpr const char* mode = "optional-control";
static void enter(ScopeOwner& scope, VM& vm, JSGlobalObject* globalObject) { scope.emplace(vm, globalObject); }
static VMEntryScope* activeScope(ScopeOwner& scope) { return scope ? &*scope : nullptr; }
#else
using ScopeOwner = VMEntryScope;
static constexpr const char* mode = "deferred-owner";
static void enter(ScopeOwner& scope, VM& vm, JSGlobalObject* globalObject) { scope.enter(vm, globalObject); }
static VMEntryScope* activeScope(ScopeOwner& scope) { return scope ? &scope : nullptr; }
static_assert(!std::is_copy_constructible_v<VMEntryScope> && !std::is_copy_assignable_v<VMEntryScope>);
static_assert(!std::is_move_constructible_v<VMEntryScope> && !std::is_move_assignable_v<VMEntryScope>);
#endif

static unsigned storageChecks;
static unsigned storageFailures;

static NEVER_INLINE uintptr_t readWord(const void* memory)
{
    std::array<unsigned char, sizeof(uintptr_t)> bytes;
    auto* input = static_cast<const volatile unsigned char*>(memory);
    for (size_t index = 0; index < bytes.size(); ++index)
        bytes[index] = input[index];
    uintptr_t value;
    std::memcpy(&value, bytes.data(), sizeof(value));
    return value;
}

static NEVER_INLINE void checkStorage(const char* stage, const ScopeOwner& scope, VM* vm, JSGlobalObject* globalObject)
{
    static_assert(sizeof(ScopeOwner) % sizeof(uintptr_t) == 0);
    auto* bytes = reinterpret_cast<const unsigned char*>(&scope);
    bool clean = true;
    for (size_t index = 0; index < sizeof(ScopeOwner) / sizeof(uintptr_t); ++index) {
        uintptr_t expected = index == 0 ? reinterpret_cast<uintptr_t>(vm)
            : index == 1 ? reinterpret_cast<uintptr_t>(globalObject)
                         : static_cast<uintptr_t>(!!vm);
        clean &= readWord(bytes + index * sizeof(uintptr_t)) == expected;
    }
    ++storageChecks;
    storageFailures += !clean;
    std::printf("storage %s %s\n", stage, clean ? "PASS" : "FAIL");
}

static bool storageAndLifecycle(VM& vm, JSGlobalObject* globalObject)
{
    alignas(ScopeOwner) std::array<unsigned char, sizeof(ScopeOwner)> storage;
    storage.fill(0xa5);
    // Match the production declaration's default-initialization, not T() value-initialization.
    auto* scope = ::new (static_cast<void*>(storage.data())) ScopeOwner;
    VMEntryScope* previous = vm.entryScope;
    bool valid = !*scope && vm.entryScope == previous;
    checkStorage("default", *scope, nullptr, nullptr);

    enter(*scope, vm, nullptr);
    valid &= !!*scope && activeScope(*scope)->globalObject() == nullptr;
    valid &= &activeScope(*scope)->vm() == &vm;
    valid &= vm.entryScope == (previous ? previous : activeScope(*scope));
    checkStorage("entered-null-global", *scope, &vm, nullptr);
    activeScope(*scope)->setGlobalObject(globalObject);
    checkStorage("global-updated", *scope, &vm, globalObject);

    {
        ScopeOwner nested;
        VMEntryScope* owner = vm.entryScope;
        enter(nested, vm, globalObject);
        valid &= vm.entryScope == owner && &activeScope(nested)->vm() == &vm;
        nested.reset();
        valid &= !nested && vm.entryScope == owner;
    }
    scope->reset();
    valid &= !*scope && vm.entryScope == previous;
    checkStorage("reset", *scope, nullptr, nullptr);
    scope->reset();
    valid &= vm.entryScope == previous;

    enter(*scope, vm, globalObject);
    valid &= !!*scope && activeScope(*scope)->globalObject() == globalObject;
    checkStorage("reentered", *scope, &vm, globalObject);
    scope->reset();
    checkStorage("reset-again", *scope, nullptr, nullptr);
    std::destroy_at(scope);
    return valid && vm.entryScope == previous;
}

class ScopeProbeDispatcher final : public MicrotaskDispatcher {
    WTF_MAKE_COMPACT_TZONE_ALLOCATED(ScopeProbeDispatcher);
public:
    static Ref<ScopeProbeDispatcher> create(Function<void()>&& callback)
    {
        return adoptRef(*new ScopeProbeDispatcher(WTF::move(callback)));
    }
    QueuedTask::Result run(QueuedTask&) final
    {
        m_callback();
        return QueuedTask::Result::Executed;
    }
    bool isRunnable() const final { return true; }
private:
    explicit ScopeProbeDispatcher(Function<void()>&& callback)
        : MicrotaskDispatcher(Type::None)
        , m_callback(WTF::move(callback))
    { }
    Function<void()> m_callback;
};

WTF_MAKE_TZONE_ALLOCATED_IMPL(ScopeProbeDispatcher);

static void enqueue(VM& vm, JSGlobalObject* globalObject, Function<void()>&& callback)
{
    auto* dispatcher = JSMicrotaskDispatcher::create(vm, ScopeProbeDispatcher::create(WTF::move(callback)), globalObject);
    vm.defaultMicrotaskQueue().enqueue(QueuedTask { dispatcher });
}

static bool checkpointLifecycle(VM& vm, JSGlobalObject* globalObject, bool viaVM)
{
    if (vm.entryScope || !vm.defaultMicrotaskQueue().isEmpty())
        return false;
    bool valid = true;
    unsigned callbacks = 0;
    unsigned switches = 0;
    VMEntryScope* owningScope = nullptr;

    // A null-global task resets the inner checkpoint scope; a later task must
    // re-enter. The VM-level owner, when present, spans those inner transitions.
    enqueue(vm, globalObject, [&] {
        ++callbacks;
        owningScope = vm.entryScope;
        valid &= owningScope && owningScope->globalObject() == globalObject;
        VMEntryScope nested(vm, globalObject);
        valid &= vm.entryScope == owningScope;
    });
    enqueue(vm, nullptr, [&] {
        ++callbacks;
        valid &= viaVM ? vm.entryScope == owningScope : vm.entryScope == nullptr;
        if (viaVM)
            valid &= vm.entryScope && vm.entryScope->globalObject() == globalObject;
    });
    enqueue(vm, globalObject, [&] {
        ++callbacks;
        valid &= vm.entryScope && vm.entryScope->globalObject() == globalObject;
        if (viaVM)
            valid &= vm.entryScope == owningScope;
    });

    if (viaVM)
        vm.drainMicrotasks();
    else
        vm.defaultMicrotaskQueue().performMicrotaskCheckpoint<false>(vm, [&](JSGlobalObject*, JSGlobalObject*) { ++switches; });
    return valid && callbacks == 3 && (viaVM || switches == 3)
        && !vm.entryScope && vm.defaultMicrotaskQueue().isEmpty();
}

int main()
{
    WTF::initializeMainThread();
    JSC::initialize();
    JSGlobalContextRef context = JSGlobalContextCreate(nullptr);
    if (!context)
        return 2;
    auto* globalObject = toJS(context);
    VM& vm = globalObject->vm();
    bool lifecyclePassed;
    bool emptyQueuePassed;
    bool directCheckpointPassed;
    bool vmCheckpointPassed;
    JSLockHolder lock(vm);
    {
        if (vm.entryScope || !vm.defaultMicrotaskQueue().isEmpty())
            return 2;
        lifecyclePassed = storageAndLifecycle(vm, globalObject);
        unsigned emptySwitches = 0;
        vm.defaultMicrotaskQueue().performMicrotaskCheckpoint<false>(vm, [&](JSGlobalObject*, JSGlobalObject*) { ++emptySwitches; });
        vm.drainMicrotasks();
        emptyQueuePassed = !emptySwitches && !vm.entryScope && vm.defaultMicrotaskQueue().isEmpty();
        directCheckpointPassed = checkpointLifecycle(vm, globalObject, false);
        vmCheckpointPassed = checkpointLifecycle(vm, globalObject, true);
    }
    JSGlobalContextRelease(context);
    bool valid = lifecyclePassed && emptyQueuePassed && directCheckpointPassed && vmCheckpointPassed;
    std::printf("{\"mode\":\"%s\",\"valid\":%s,\"storageChecks\":%u,\"storageFailures\":%u,\"lifecyclePassed\":%s,\"emptyQueuePassed\":%s,\"directCheckpointPassed\":%s,\"vmCheckpointPassed\":%s}\n",
        mode, valid ? "true" : "false", storageChecks, storageFailures,
        lifecyclePassed ? "true" : "false", emptyQueuePassed ? "true" : "false",
        directCheckpointPassed ? "true" : "false", vmCheckpointPassed ? "true" : "false");
    return valid && !storageFailures ? 0 : 1;
}
