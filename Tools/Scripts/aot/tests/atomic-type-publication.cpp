// SPDX-License-Identifier: BSD-2-Clause
#include "config.h"
#include "AOTType.h"
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <thread>

using namespace JSC::AOT;

static uint64_t checkPublication(Type initial, Type added)
{
    constexpr unsigned rounds = 100000;
    Type published = initial | added;
    AtomicType value;
    value.store(initial);
    std::atomic<unsigned> phase { 0 };
    uint64_t invalid = 0;
    std::thread writer([&] {
        for (unsigned i = 0; i < rounds; ++i) {
            while (phase.load(std::memory_order_acquire) != 1) { }
            value.store(published);
            phase.store(2, std::memory_order_release);
            while (phase.load(std::memory_order_acquire) != 3) { }
            // The reader waits until phase 0 before sampling the next publication.
            value.store(initial);
            phase.store(0, std::memory_order_release);
        }
    });
    for (unsigned i = 0; i < rounds; ++i) {
        while (phase.load(std::memory_order_acquire) != 0) { }
        phase.store(1, std::memory_order_release);
        do {
            Type observed = value.load();
            bool metadataWithoutTag = (!(observed & TFunctionTag) && (observed & TAnyFunctionNumber))
                || (!(observed & TFinalObjectTag) && (observed & TAnyLayoutNumber))
                || (!(observed & TArrayTag) && (observed & TAnyArrayShape));
            invalid += metadataWithoutTag || (observed & ~published) || ((observed & initial) != initial);
        } while (phase.load(std::memory_order_acquire) != 2);
        invalid += value.load() != published;
        phase.store(3, std::memory_order_release);
    }
    writer.join();
    return invalid;
}

int main()
{
    constexpr Type function = TFunctionTag | dualRailEncode(10, firstFunctionNumberBit, functionNumberBits);
    constexpr Type otherFunction = TFunctionTag | dualRailEncode(1u << 18, firstFunctionNumberBit, functionNumberBits);
    constexpr Type object = TFinalObjectTag | dualRailEncode(17, firstLayoutNumberBit, layoutNumberBits);
    constexpr Type array = TArrayTag | (Type(0x1234) << firstArrayShapeBit);
    uint64_t invalid = checkPublication(TNone, function)
        + checkPublication(TUndefined, function)
        + checkPublication(TInt32, object)
        + checkPublication(TNull, array)
        + checkPublication(function, object)
        + checkPublication(object, array)
        + checkPublication(function, otherFunction);
    std::printf("700000 publications, %llu invalid snapshots\n", static_cast<unsigned long long>(invalid));
    return invalid ? 1 : 0;
}
