/*
 * Copyright (C) 2026 OpenClaw Foundation. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause
 */

#include "config.h"

#if ENABLE(AOT)

#include "aot/AOTTypedIR.h"
#include "aot/AOTTypedPasses.h"
#include <JavaScriptCore/InitializeThreading.h>

namespace TestWebKitAPI {

TEST(JavaScriptCore_AOTTypedArrays, DeclaredArraysDoNotProveNativeStorage)
{
    using namespace JSC::AOT::Typed;
    JSC::initialize();
    Program program;
    Type native = Type::engineClass(Builtins::singleton().arrayClass());
    Type declared = native;
    declared.allowsArrayProxies = true;
    EXPECT_TRUE(native.isSubsetOf(declared, program));
    EXPECT_FALSE(declared.isSubsetOf(native, program));
    EXPECT_NE(native.singleBuiltinClass(), nullptr);
    EXPECT_EQ(declared.singleBuiltinClass(), nullptr);

    JSC::AOT::Typed::Function function;
    Value array;
    array.type = program.types.intern(declared);
    function.values.append(array);
    Value index;
    index.type = program.types.intern(Type::integer(Range::one(0)));
    function.values.append(index);
    Value read;
    read.opcode = Opcode::GetByVal;
    read.children = { ValueID(0u), ValueID(1u), ValueID() };
    EXPECT_EQ(keyedAccessOf(program, function, read), KeyedAccess::Generic);
    Value open;
    open.opcode = Opcode::IteratorOpen;
    open.children[0] = ValueID(0u);
    EXPECT_EQ(keyedAccessOf(program, function, open), KeyedAccess::Generic);

    function.values[0].type = program.types.intern(native);
    EXPECT_EQ(keyedAccessOf(program, function, read), KeyedAccess::Array);
    EXPECT_EQ(keyedAccessOf(program, function, open), KeyedAccess::Array);
}

} // namespace TestWebKitAPI

#endif // ENABLE(AOT)
