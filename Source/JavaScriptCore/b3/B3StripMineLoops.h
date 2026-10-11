/*
 * Copyright (C) 2026 Oven, Inc. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause
 */

#pragma once

#if ENABLE(B3_JIT) && USE(BUN_JSC_ADDITIONS)

namespace JSC { namespace B3 {

class Procedure;

// Takes the poll (Procedure::loopPollGenerator()) out of a counted loop. The test compares the induction variable with the end of a
// strip of at most 2^16 iterations, which is never beyond the bound. Where that fails, blocks beside the loop make the real test, poll, and set the end of the next strip.
// The body is not copied. Keeps SSA.
// A variable that may wrap around keeps the original per-iteration poll.
bool stripMineLoops(Procedure&);

} } // namespace JSC::B3

#endif // ENABLE(B3_JIT) && USE(BUN_JSC_ADDITIONS)
