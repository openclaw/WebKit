/*
 * Copyright (C) 2026 OpenClaw contributors.
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
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 * "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 * LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 * A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 * HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 * SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED
 * TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
 * PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
 * LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
 * NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
 * SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

#pragma once

#include <atomic>
#include <utility>
#include <wtf/RefPtr.h>
#include <wtf/ThreadSafeRefCounted.h>

namespace JSC {

enum class ArrayBufferAllocationMode : uint8_t { External = 0, RuntimeOwned = 1 };

// Backing stores may release an allocating VM's charge after that VM has exited.
class ArrayBufferMemoryAccount final : public ThreadSafeRefCounted<ArrayBufferMemoryAccount> {
public:
    static Ref<ArrayBufferMemoryAccount> create() { return adoptRef(*new ArrayBufferMemoryAccount); }

    // Counts do not publish storage; VM and message lifetimes are synchronized separately.
    size_t allocatedBytes() const { return m_allocatedBytes.load(std::memory_order_relaxed); }
    size_t externalBytes() const { return m_externalBytes.load(std::memory_order_relaxed); }
    size_t objectBytes() const { return m_objectBytes.load(std::memory_order_relaxed); }

    void allocate(size_t bytes) { m_allocatedBytes.fetch_add(bytes, std::memory_order_relaxed); }
    void deallocate(size_t bytes) { m_allocatedBytes.fetch_sub(bytes, std::memory_order_relaxed); }
    void acquire(size_t bytes) { m_externalBytes.fetch_add(bytes, std::memory_order_relaxed); }
    void release(size_t bytes) { m_externalBytes.fetch_sub(bytes, std::memory_order_relaxed); }
    void allocateObject(size_t bytes) { m_objectBytes.fetch_add(bytes, std::memory_order_relaxed); }
    void deallocateObject(size_t bytes) { m_objectBytes.fetch_sub(bytes, std::memory_order_relaxed); }

private:
    std::atomic<size_t> m_allocatedBytes { 0 };
    std::atomic<size_t> m_externalBytes { 0 };
    std::atomic<size_t> m_objectBytes { 0 };
};

class ArrayBufferAllocation final {
public:
    ArrayBufferAllocation() = default;
    ArrayBufferAllocation(const ArrayBufferAllocation&) = delete;
    ArrayBufferAllocation& operator=(const ArrayBufferAllocation&) = delete;

    ArrayBufferAllocation(ArrayBufferAllocation&& other) noexcept
        : m_account(WTF::move(other.m_account))
        , m_bytes(std::exchange(other.m_bytes, 0))
    {
    }

    ArrayBufferAllocation& operator=(ArrayBufferAllocation&& other) noexcept
    {
        if (this != &other) {
            reset();
            m_account = WTF::move(other.m_account);
            m_bytes = std::exchange(other.m_bytes, 0);
        }
        return *this;
    }

    static ArrayBufferAllocation create(ArrayBufferMemoryAccount& account, size_t bytes)
    {
        return ArrayBufferAllocation(account, bytes);
    }

    ~ArrayBufferAllocation() { reset(); }
    explicit operator bool() const { return !!m_account; }

    void reset()
    {
        if (m_account)
            m_account->deallocate(m_bytes);
        m_account = nullptr;
        m_bytes = 0;
    }

private:
    ArrayBufferAllocation(ArrayBufferMemoryAccount& account, size_t bytes)
        : m_account(&account)
        , m_bytes(bytes)
    {
        m_account->allocate(bytes);
    }

    RefPtr<ArrayBufferMemoryAccount> m_account;
    size_t m_bytes { 0 };
};

} // namespace JSC
