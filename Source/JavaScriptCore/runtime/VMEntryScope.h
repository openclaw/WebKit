/*
 * Copyright (C) 2013, 2014 Apple Inc. All rights reserved.
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

#pragma once

#include "JSExportMacros.h"
#include <wtf/Assertions.h>
#include <wtf/Noncopyable.h>

namespace JSC {

class JSGlobalObject;
class VM;

class VMEntryScope {
    WTF_MAKE_NONCOPYABLE(VMEntryScope);
public:
    VMEntryScope() = default;
    VMEntryScope(VM&, JSGlobalObject*);
    ~VMEntryScope();
    VMEntryScope(VMEntryScope&&) = delete;
    VMEntryScope& operator=(VMEntryScope&&) = delete;

    void enter(VM&, JSGlobalObject*);
    void reset();
    explicit operator bool() const { return m_vm; }

    VM& vm() const
    {
        ASSERT(m_vm);
        return *m_vm;
    }
    JSGlobalObject* globalObject() const { return m_globalObject; }
    void setGlobalObject(JSGlobalObject* globalObject)
    {
        ASSERT(m_vm);
        m_globalObject = globalObject;
    }

private:
    JS_EXPORT_PRIVATE void setUpSlow();
    JS_EXPORT_PRIVATE void tearDownSlow();

    // Pointer-sized state avoids optional's partial-word flag and uninitialized padding on the scanned stack.
    VM* m_vm { nullptr };
    JSGlobalObject* m_globalObject { nullptr };
};

static_assert(sizeof(VMEntryScope) == 2 * sizeof(void*));

} // namespace JSC
