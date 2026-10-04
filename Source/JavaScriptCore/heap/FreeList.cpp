/*
 * Copyright (C) 2016-2017 Apple Inc. All rights reserved.
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
 * THIS SOFTWARE IS PROVIDED BY APPLE INC. ``AS IS'' AND ANY
 * EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL APPLE INC. OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 * EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 * PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY
 * OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 * (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 * OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE. 
 */

#include "config.h"
#include "FreeList.h"

namespace JSC {

FreeList::FreeList(unsigned cellSize)
    : m_cellSize(cellSize)
{
}

FreeList::~FreeList() = default;

void FreeList::clear()
{
    clearAllocationSampleLimit();
    m_intervalStart = nullptr;
    m_intervalEnd = nullptr;
    m_nextInterval = std::bit_cast<FreeCell*>(static_cast<uintptr_t>(1));
    m_secret = 0;
    m_originalSize = 0;
}

void FreeList::setAllocationSampleLimit(uint64_t cells)
{
    ASSERT(!m_sampleStart);
    if (!m_intervalStart)
        return;
    m_sampleStart = m_intervalStart;
    m_sampleEnd = m_intervalEnd;
    m_sampleNext = m_nextInterval;
    auto available = static_cast<uint64_t>((m_intervalEnd - m_intervalStart) / m_cellSize);
    m_intervalEnd = m_intervalStart + std::min(cells, available) * m_cellSize;
    // Both generated and C++ allocators already enter the slow path at this sentinel.
    m_nextInterval = std::bit_cast<FreeCell*>(static_cast<uintptr_t>(1));
}

uint64_t FreeList::clearAllocationSampleLimit()
{
    if (!m_sampleStart)
        return 0;
    auto consumed = static_cast<uint64_t>((m_intervalStart - m_sampleStart) / m_cellSize);
    m_intervalEnd = m_sampleEnd;
    m_nextInterval = m_sampleNext;
    m_sampleStart = nullptr;
    return consumed;
}

void FreeList::initialize(FreeCell* start, uint64_t secret, unsigned bytes)
{
    if (!start) [[unlikely]] {
        clear();
        return;
    }
    m_secret = secret;
    m_nextInterval = start;
    FreeCell::advance(m_secret, m_nextInterval, m_intervalStart, m_intervalEnd);
    m_originalSize = bytes;
}

void FreeList::dump(PrintStream& out) const
{
    out.print("{nextInterval = ", RawPointer(nextInterval()), ", secret = ", m_secret, ", intervalStart = ", RawPointer(m_intervalStart), ", intervalEnd = ", RawPointer(m_intervalEnd), ", originalSize = ", m_originalSize, "}");
}

} // namespace JSC
