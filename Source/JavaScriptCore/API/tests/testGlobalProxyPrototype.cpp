/* Copyright (C) 2026 Peter Steinberger. All rights reserved. */

#include "config.h"
#include "APICast.h"
#include "InitializeThreading.h"
#include "JSGlobalObject.h"
#include "JSLock.h"
#include "JSObjectInlines.h"
#include "JavaScript.h"
#include "VM.h"
#include <cstdio>
#include <wtf/MainThread.h>

using namespace JSC;

static bool checkDeclaration(bool allowProxy)
{
    JSGlobalContextRef context = JSGlobalContextCreate(nullptr);
    if (!context)
        return false;
    bool passed = false;
    {
        auto* globalObject = toJS(context);
        VM& vm = globalObject->vm();
        JSLockHolder lock(vm);
        JSValueRef exception = nullptr;
        JSStringRef proxySource = JSStringCreateWithUTF8CString("new Proxy({}, {})");
        JSValueRef proxy = JSEvaluateScript(context, proxySource, nullptr, nullptr, 1, &exception);
        JSStringRelease(proxySource);
        if (proxy && !exception) {
            // Install the same chain an embedder can provide, without testing a JS prototype setter.
            globalObject->setPrototypeDirect(vm, asObject(toJS(globalObject, proxy)));
            globalObject->setAllowsProxyInPrototypeChain(allowProxy);
            JSStringRef declaration = JSStringCreateWithUTF8CString("var proxyDeclaration = 42; proxyDeclaration");
            JSValueRef result = JSEvaluateScript(context, declaration, nullptr, nullptr, 1, &exception);
            JSStringRelease(declaration);
            passed = allowProxy ? result && !exception && JSValueToNumber(context, result, nullptr) == 42 : exception != nullptr;
        }
        JSGlobalContextRelease(context);
    }
    return passed;
}

int main()
{
    WTF::initializeMainThread();
    JSC::initialize();
    bool rejectedByDefault = checkDeclaration(false);
    bool allowedWhenEnabled = checkDeclaration(true);
    std::printf("proxy-global default-rejected=%d opt-in-allowed=%d\n", rejectedByDefault, allowedWhenEnabled);
    return rejectedByDefault && allowedWhenEnabled ? 0 : 1;
}
