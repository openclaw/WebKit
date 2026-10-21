/*
 * Copyright (C) 2026 OpenClaw Foundation. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause
 */

#include "config.h"

#if ENABLE(AOT)

#include "aot/AOTConvention.h"

namespace TestWebKitAPI {

TEST(JavaScriptCore_AOTConvention, ClosureFunctionIdsAboveHalfRange)
{
    using namespace JSC::AOT;
    constexpr uintptr_t code = 0x100000000ULL;
    constexpr uint64_t offset = 0x1000;
    constexpr uint32_t functions[] = { 2097136, 2097151, 2097152, 3310277, 4194287 };
    for (uint32_t function : functions) {
        for (Signature signature : { Signature::Registers, Signature::List }) {
            auto relative = EntryWord::encode(offset, Convention { signature, 3, true });
            auto word = ClosureWord::encode(relative, function);
            EXPECT_EQ(ClosureWord::functionOf(word), function);
            EXPECT_EQ(ClosureWord::addressOf(word, code), code + offset);
            EXPECT_EQ(!!(word & (1ULL << ClosureWord::isListBit)), signature == Signature::List);
            EXPECT_EQ(word >> ClosureWord::numberOfParametersShift & 15, signature == Signature::List ? 0u : 3u);
            EXPECT_EQ(word >> ClosureWord::hasCompatibleResultsMaskBit & 15, 0u);

            auto request = ClosureRequest::encode(function, 3, 0x12345);
            EXPECT_EQ(ClosureRequest::functionOf(request), function);
            EXPECT_EQ(ClosureRequest::executableOf(request), 3u);
            EXPECT_EQ(ClosureRequest::allocationOf(request), 0x12345u);
        }
    }
}

} // namespace TestWebKitAPI

#endif // ENABLE(AOT)
