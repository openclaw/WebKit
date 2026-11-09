/*
 * Copyright (C) 2026 Oven, Inc. All rights reserved.
 * SPDX-License-Identifier: BSD-2-Clause
 */

#include "config.h"

#if ENABLE(AOT)

#include "AOTCollectionTestSupport.h"
#include "AOTDriver.h"
#include "AOTLoadedProgramTestSupport.h"
#include "AOTModuleHost.h"
#include "AOTModuleNamespace.h"
#include "AOTModules.h"
#include "AOTObjectModel.h"
#include "AOTPropertyCaches.h"
#include "AOTRegExpRecords.h"
#include "AOTRuntimeType.h"
#include "AOTSchemaRuntimeOperations.h"
#include "AOTShellProcess.h"
#include "AOTShellProgramTestSupport.h"
#include "AOTTemporaryFile.h"
#include "AOTTestHarness.h"
#include "AOTThreads.h"
#include "AOTVector.h"
#include "JSArrayBuffer.h"
#include "JSCInlines.h"
#include <array>
#include <bit>
#include <initializer_list>
#include <stdlib.h>
#include <wtf/DataLog.h>
#include <wtf/StdLibExtras.h>
#include <wtf/text/MakeString.h>

WTF_ALLOW_UNSAFE_BUFFER_USAGE_BEGIN

namespace JSC { namespace AOT {

std::span<const NativeTest> sharingModeAndNamespaceTests();

static constexpr ASCIILiteral programText = R"IR(layout L0 name="Record" fields=[{key="a" declared={type=anything} flags=[IsRequired]}]
variable g0 name="a" module=m1 declared={type=anything} initialization=Undefined
variable g1 name="a" module=m2 declared={type=anything} initialization=Undefined
variable g2 name="chosen" module=m0 declared={type=anything} initialization=Undefined
module m0 path="/main.js" displayPath="main.js" body=f0 requests=[{target=m1 completes=true}, {target=m2 completes=true}, {target=m1 phase=Defer}]
module m1 path="/first.js" displayPath="first.js" requireResult=Namespace body=f1 exports=[{name="a" variable=g0}, {name="default" variable=g0}]
module m2 path="/second.js" displayPath="second.js" body=f2 exports=[{name="a" variable=g1}]
entry module=m0
entry module=m1
function f0 name="main" kind=Module results=[{type=anything}] {
    v0 = Builtin builtin=GlobalThis
    v1 = PropGet v0 key="registry" [isFreeName]
    v2 = NewClosure function=f3
    PropSet v1, v2 key="isUnshared"
    v4 = NewClosure function=f4
    PropSet v1, v4 key="isShared"
    v6 = NewClosure function=f5
    PropSet v1, v6 key="isEither"
    v8 = NewClosure function=f6
    PropSet v1, v8 key="choose"
    v10 = NewClosure function=f7
    PropSet v1, v10 key="read"
    v12 = ModuleNamespace module=m1 phase=Defer
    PropSet v1, v12 key="deferred"
    Return
}
function f1 name="first" module=m1 kind=Module results=[{type=anything}] {
    v0 = String string="export of first"
    PutModuleVariable v0 variable=g0
    Return
}
function f2 name="second" module=m2 kind=Module results=[{type=anything}] {
    v0 = String string="export of second"
    PutModuleVariable v0 variable=g1
    Return
}
function f3 name="isUnshared" parameters=[{type=anything}] results=[{type=anything}] {
    v1 = TypeTest v0 testedType=ArrayBuffer
    Return v1
}
function f4 name="isShared" parameters=[{type=anything}] results=[{type=anything}] {
    v1 = TypeTest v0 testedType=SharedArrayBuffer
    Return v1
}
function f5 name="isEither" parameters=[{type=anything}] results=[{type=anything}] {
    v1 = TypeTest v0 testedType=ArrayBuffer|SharedArrayBuffer
    Return v1
}
function f6 name="choose" parameters=[{type=anything}] results=[{type=anything}] {
    v1 = Integer integer=1
    v2 = StrictEq v0, v1
    Branch v2 -> taken b1(), notTaken b2()
  b1():
    v3 = ModuleNamespace module=m1
    PutModuleVariable v3 variable=g2
    Return
  b2():
    v5 = Integer integer=2
    v6 = StrictEq v0, v5
    Branch v6 -> taken b3(), notTaken b4()
  b3():
    v7 = ModuleNamespace module=m2
    PutModuleVariable v7 variable=g2
    Return
  b4():
    v9 = String string="field of a record"
    v10 = NewObject -, v9 layout=L0 fields=[0]
    PutModuleVariable v10 variable=g2
    Return
}
function f7 name="read" results=[{type=anything}] {
    v0 = GetModuleVariable variable=g2
    v1 = PropGet v0 key="a"
    Return v1
}
)IR"_s;

static constexpr ASCIILiteral programWithCapturedExports = R"IR(layout L0 name="Exports" fields=[{key="a" declared={type=anything} flags=[IsRequired]}]
variable g0 name="exports" module=m1 declared={type=anything} initialization=Undefined
module m0 path="/main.js" displayPath="main.js" body=f0 requests=[{target=m2 completes=true}]
module m1 path="/value.cjs" displayPath="value.cjs" kind=CommonJs exportRule=CommonJs requireResult=ModuleExports body=f1 exportsVariable=g0
module m2 path="#2" displayPath="value.cjs" exportRule=CommonJs requireResult=Namespace body=f2 requests=[{target=m1 kind=Require completes=true}] syntheticExports=[{name="a" isReplaceable=true}, {name="default"}]
entry module=m0
function f0 name="main" kind=Module results=[{type=anything}] {
    v0 = Builtin builtin=GlobalThis
    v1 = ModuleNamespace module=m2
    PropSet v0, v1 key="capturedNamespace"
    v3 = PropGet v0 key="registry" [isFreeName]
    v4 = NewClosure function=f3
    PropSet v3, v4 key="readCaptured"
    v6 = Call v4, -, v1 [isNeverInlined]
    Return
}
function f1 name="value" module=m1 kind=CommonJsModule flags=[IsSloppy] results=[{type=anything}] {
    v0 = Integer integer=1
    v1 = NewObject -, v0 layout=L0 fields=[0]
    v2 = FinishObject v1
    PutModuleVariable v2 variable=g0
    Return
}
function f2 name="face" module=m1 kind=Module results=[{type=anything}] {
    EvaluateModule module=m1 referrer=m2 [isBare]
    Return
}
function f3 name="readCaptured" parameters=[{type=anything}] results=[{type=anything}] {
    v1 = PropGet v0 key="a"
    Return v1
}
)IR"_s;

static constexpr ModuleID firstModule(1u);
static constexpr ModuleID secondModule(2u);
static constexpr auto unshared = ArrayBufferSharingMode::Default;
static constexpr auto shared = ArrayBufferSharingMode::Shared;

namespace {

class TypeRecord {
public:
    TypeRecord(std::initializer_list<RuntimeCellTest> tests)
    {
        Vector<RuntimeCellTest> ordered(tests);
        std::ranges::stable_sort(ordered, { }, [](const RuntimeCellTest& test) -> int64_t {
            return test.kind == CellTestKind::IsClosureOf ? static_cast<int64_t>(test.operand) : -1;
        });
        size_t numberInFront = std::ranges::count_if(ordered, [](const RuntimeCellTest& test) { return test.kind != CellTestKind::IsClosureOf; });
        m_words.append(static_cast<uint32_t>(std::min<size_t>(numberInFront, RuntimeType::hasManyTestsOfMoreThanOneFunction)) << 24);
        m_words.append(static_cast<uint32_t>(tests.size()));
        for (const RuntimeCellTest& test : ordered) {
            auto words = std::bit_cast<std::array<uint32_t, 2>>(test);
            m_words.append(words[0]);
            m_words.append(words[1]);
        }
        AOT_TEST_CHECK(m_words.size() * sizeof(uint32_t) == RuntimeType::sizeInBytes(tests.size(), 0, 0));
    }

    operator const RuntimeType&() const { return *reinterpret_cast<const RuntimeType*>(m_words.span().data()); }

private:
    Vector<uint32_t, 8> m_words;
};

} // anonymous namespace

static JSValue evaluate(LoadedProgram& program, ASCIILiteral source)
{
    return program.realms().evaluate(program.realms().plain(), source);
}

static bool hasType(LoadedProgram& program, const RuntimeType& type, JSValue value)
{
    return program.state().objects->layouts.valueHasType(type, value);
}

static JSArrayBuffer* createBuffer(LoadedProgram& program, ArrayBufferSharingMode sharingMode, ArrayBufferSharingMode sharingModeOfStructure)
{
    RefPtr<ArrayBuffer> buffer = ArrayBuffer::tryCreate(8, 1);
    AOT_TEST_CHECK(buffer);
    buffer->setSharingMode(sharingMode);
    return JSArrayBuffer::create(program.vm(), program.realm()->arrayBufferStructure(sharingModeOfStructure), WTF::move(buffer));
}

static void testSharingModeOfValues(LoadedProgram& program)
{
    TypeRecord unsharedBuffers { RuntimeCellTest::sharingModeIs(unshared) };
    TypeRecord sharedBuffers { RuntimeCellTest::sharingModeIs(shared) };

    for (JSValue buffer : { JSValue(createBuffer(program, shared, shared)), JSValue(createBuffer(program, shared, unshared)) })
        AOT_TEST_CHECK(hasType(program, sharedBuffers, buffer) && !hasType(program, unsharedBuffers, buffer));

    JSArrayBuffer* detached = createBuffer(program, unshared, unshared);
    detached->impl()->detach(program.vm());
    AOT_TEST_CHECK(detached->impl()->isDetached());
    for (JSValue buffer : { JSValue(createBuffer(program, unshared, unshared)), JSValue(createBuffer(program, unshared, shared)), JSValue(detached), evaluate(program, "new ArrayBuffer(8)"_s), evaluate(program, "new (class extends ArrayBuffer { })(8)"_s) })
        AOT_TEST_CHECK(hasType(program, unsharedBuffers, buffer) && !hasType(program, sharedBuffers, buffer));

    for (JSValue other : { evaluate(program, "new Uint8Array(8)"_s), evaluate(program, "new DataView(new ArrayBuffer(8))"_s), evaluate(program, "Object.create(ArrayBuffer.prototype)"_s), evaluate(program, "ArrayBuffer"_s), evaluate(program, "'ArrayBuffer'"_s) })
        AOT_TEST_CHECK(!hasType(program, unsharedBuffers, other) && !hasType(program, sharedBuffers, other));
}

static void testModuleOfNamespaceObjects(LoadedProgram& program)
{
    using ModulePhase = AbstractModuleRecord::ModulePhase;
    Modules& modules = modulesOf(program.instance());
    JSObject* first = modules.moduleNamespace(firstModule, ModulePhase::Evaluation);
    JSObject* second = modules.moduleNamespace(secondModule, ModulePhase::Evaluation);
    JSObject* deferredFirst = modules.moduleNamespace(firstModule, ModulePhase::Defer);
    AOT_TEST_CHECK(first && second && deferredFirst && first != deferredFirst);

    TypeRecord namespacesOfFirst { RuntimeCellTest::isNamespaceOf(firstModule) };
    TypeRecord namespacesOfSecond { RuntimeCellTest::isNamespaceOf(secondModule) };
    AOT_TEST_CHECK(hasType(program, namespacesOfFirst, first) && !hasType(program, namespacesOfFirst, second));
    AOT_TEST_CHECK(hasType(program, namespacesOfSecond, second) && !hasType(program, namespacesOfSecond, first));
    AOT_TEST_CHECK(!hasType(program, namespacesOfFirst, deferredFirst));
    for (JSValue other : { evaluate(program, "({ a: 1 })"_s), evaluate(program, "Object.create(null)"_s), evaluate(program, "[]"_s), evaluate(program, "'first.js'"_s) })
        AOT_TEST_CHECK(!hasType(program, namespacesOfFirst, other));

    AOT_TEST_CHECK(operationAOTIsNamespaceOfModule(first, firstModule.index()) && !operationAOTIsNamespaceOfModule(first, secondModule.index()));
    AOT_TEST_CHECK(!operationAOTIsNamespaceOfModule(deferredFirst, firstModule.index()));
    AOT_TEST_CHECK(!operationAOTIsNamespaceOfModule(evaluate(program, "({ a: 1 })"_s).asCell(), firstModule.index()));
}

static void testRequireNamespaceDoesNotMutateImports(LoadedProgram& program)
{
    using ModulePhase = AbstractModuleRecord::ModulePhase;
    VM& vm = program.vm();
    Modules& modules = modulesOf(program.instance());
    Strong<JSObject> imported(vm, modules.moduleNamespace(firstModule, ModulePhase::Evaluation));
    AOT_TEST_CHECK(imported);
    JSValue answer = modules.require(firstModule);
    AOT_TEST_CHECK(answer && answer.isObject());
    Strong<JSObject> required(vm, asObject(answer));
    AOT_TEST_CHECK(required.get() != imported.get());
    AOT_TEST_CHECK(modules.require(firstModule) == JSValue(required.get()));
    AOT_TEST_CHECK(requireModule(program.realm(), firstModule) == JSValue(required.get()));
    AOT_TEST_CHECK(moduleNamespaceForRequire(program.realm(), imported.get()) == required.get());
    AOT_TEST_CHECK(moduleNamespaceForRequire(program.realm(), required.get()) == required.get());

    JSGlobalObject* plain = program.realms().plain();
    plain->putDirect(vm, Identifier::fromString(vm, "importedNamespace"_s), imported.get());
    plain->putDirect(vm, Identifier::fromString(vm, "requiredNamespace"_s), required.get());
    AOT_TEST_CHECK(program.realms().evaluate(plain, R"js(
        const imported = globalThis.importedNamespace;
        const required = globalThis.requiredNamespace;
        function check(condition, message) { if (!condition) throw new Error(message); }
        check(Object.getPrototypeOf(imported) === null && Object.getPrototypeOf(required) === null, "namespace prototypes");
        check(!Object.isExtensible(imported) && !Object.isExtensible(required), "namespace extensibility");
        check(!("__esModule" in imported) && !Object.hasOwn(imported, "__esModule"), "import marker isolation");
        const descriptor = Object.getOwnPropertyDescriptor(required, "__esModule");
        check(required.__esModule === true && descriptor.value === true && descriptor.writable && descriptor.enumerable && !descriptor.configurable, "require marker descriptor");
        check(JSON.stringify(Object.keys(imported)) === '["a","default"]', "import own keys");
        check(JSON.stringify(Object.keys(required)) === '["__esModule","a","default"]', "require own keys");
        check(imported.a === "export of first" && imported.default === imported.a && required.a === imported.a && required.default === imported.default, "shared exports");
        check(!Reflect.set(imported, "__esModule", true) && !Reflect.set(required, "__esModule", false), "marker writes");
        check(!Reflect.deleteProperty(required, "__esModule"), "marker deletion");
        check(Reflect.defineProperty(required, "__esModule", { value: true }) && !Reflect.defineProperty(required, "__esModule", { value: false }), "marker definition");
        true;
    )js"_s) == jsBoolean(true));
    vm.heap.collectNow(Sync, CollectionScope::Full);
    AOT_TEST_CHECK(modules.require(firstModule) == JSValue(required.get()));
    AOT_TEST_CHECK(imported->get(program.realm(), vm.propertyNames->__esModule).isUndefined());
    AOT_TEST_CHECK(required->get(program.realm(), vm.propertyNames->__esModule) == jsBoolean(true));
    Strong<JSObject> mock(vm, constructEmptyObject(program.realm()));
    mock->putDirect(vm, vm.propertyNames->__esModule, jsBoolean(false));
    uncheckedDowncast<ModuleNamespace>(imported.get())->setMockOfView(vm, mock.get());
    AOT_TEST_CHECK(evaluate(program, R"js(
        !Reflect.set(requiredNamespace, "__esModule", false)
            && !Reflect.deleteProperty(requiredNamespace, "__esModule")
            && Reflect.defineProperty(requiredNamespace, "__esModule", { value: true })
            && !Reflect.defineProperty(requiredNamespace, "__esModule", { value: false })
            && requiredNamespace.__esModule === true
    )js"_s) == jsBoolean(true));
    AOT_TEST_CHECK(mock->get(program.realm(), vm.propertyNames->__esModule) == jsBoolean(false));
}

static void testRequireFacadeInvalidatesCapturedExports(LoadedProgram& program)
{
    using ModulePhase = AbstractModuleRecord::ModulePhase;
    constexpr ModuleID face(2u);
    VM& vm = program.vm();
    Modules& modules = modulesOf(program.instance());
    Strong<JSObject> registry(vm, constructEmptyObject(program.realm()));
    program.realm()->putDirect(vm, Identifier::fromString(vm, "registry"_s), registry.get());
    evaluateModuleSynchronously(program.realm(), ModuleID(0u));
    Strong<JSObject> imported(vm, modules.moduleNamespace(face, ModulePhase::Evaluation));
    AOT_TEST_CHECK(imported);
    JSGlobalObject* plain = program.realms().plain();
    Identifier readerName = Identifier::fromString(vm, "readCaptured"_s);
    JSValue reader = registry->getDirect(vm, readerName);
    AOT_TEST_CHECK(reader && reader.isObject());
    plain->putDirect(vm, readerName, reader);
    plain->putDirect(vm, Identifier::fromString(vm, "importedNamespace"_s), imported.get());
    AOT_TEST_CHECK(evaluate(program, R"js(
        for (let index = 0; index < 64; ++index) {
            if (readCaptured(importedNamespace) !== 1)
                throw new Error("initial captured export");
        }
        true;
    )js"_s) == jsBoolean(true));
    JSValue answer = modules.require(face);
    AOT_TEST_CHECK(answer && answer.isObject());
    Strong<JSObject> required(vm, asObject(answer));
    plain->putDirect(vm, Identifier::fromString(vm, "requiredNamespace"_s), required.get());
    Identifier key = Identifier::fromString(vm, "a"_s);
    AOT_TEST_CHECK(modules.tryReplaceCapturedExport(face, key.impl(), jsNumber(2)));
    AOT_TEST_CHECK(evaluate(program, "readCaptured(requiredNamespace)"_s) == jsNumber(2));
    AOT_TEST_CHECK(evaluate(program, "readCaptured(importedNamespace)"_s) == jsNumber(2));
}

static constexpr ASCIILiteral scriptStart = R"js(
globalThis.registry = { };
function describe(value)
{
    return registry.isUnshared(value) + " " + registry.isShared(value) + " " + registry.isEither(value);
}
)js"_s;

static constexpr ASCIILiteral statements = R"js(
    print("ArrayBuffer: " + describe(new ArrayBuffer(8)));
    print("SharedArrayBuffer: " + describe(new SharedArrayBuffer(8)));
    print("shared with the prototype of ArrayBuffer: " + describe(Reflect.construct(SharedArrayBuffer, [8], ArrayBuffer)));
    print("unshared with the prototype of SharedArrayBuffer: " + describe(Reflect.construct(ArrayBuffer, [8], SharedArrayBuffer)));
    print("subclass of ArrayBuffer: " + describe(new (class extends ArrayBuffer { })(8)));
    print("detached: " + describe((buffer => (buffer.transfer(), buffer))(new ArrayBuffer(8))));
    print("Uint8Array: " + describe(new Uint8Array(8)));
    print("object with the prototype of ArrayBuffer: " + describe(Object.create(ArrayBuffer.prototype)));
    print("number: " + describe(8));
    print("string: " + describe("ArrayBuffer"));
    print("undefined: " + describe(undefined));
    for (let choice of [1, 2, 3, 1]) {
        registry.choose(choice);
        print("choice " + choice + ": " + registry.read());
    }
)js"_s;

static constexpr ASCIILiteral expectedOutput = R"(ArrayBuffer: true false true
SharedArrayBuffer: false true true
shared with the prototype of ArrayBuffer: false true true
unshared with the prototype of SharedArrayBuffer: true false true
subclass of ArrayBuffer: true false true
detached: true false true
Uint8Array: false false false
object with the prototype of ArrayBuffer: false false false
number: false false false
string: false false false
undefined: false false false
choice 1: export of first
choice 2: export of second
choice 3: field of a record
choice 1: export of first
)"_s;

static String runInShell(OptionWords optionWords, ASCIILiteral way)
{
    std::unique_ptr<CompileOutput> output;
    runOnBuildThread([&] {
        output = compileForShellOnThisThread(programText, optionWords, way);
    });
    std::span<const uint32_t> entryModuleIDs = output->records<uint32_t>(Wire::ResultSection::EntryModuleIds);
    AOT_TEST_CHECK(entryModuleIDs.size() == 2);

    TemporaryFile image(".image"_s, output->section(Wire::ResultSection::Image));
    Vector<String> arguments {
        String("--useSharedArrayBuffer=1"_s),
        makeString("--aotImagePath="_s, image.path()),
        String("-e"_s),
        makeString(scriptStart, "runCompiledEntryPoint("_s, entryModuleIDs[0], ").then(() => {"_s, statements, "}).catch(error => print(\"the script threw \" + error));"_s),
    };

    String shell = shellPath();
    ChildProcessResult result = ChildProcessLauncher(String(shell), { }).run(arguments.span());
    if (!result.exitedWith(EXIT_SUCCESS))
        dataLogLn(shell, " ", result.description(), "\n", result.output);
    AOT_TEST_CHECK(result.exitedWith(EXIT_SUCCESS));
    return makeStringByReplacingAll(result.output, "\r\n"_s, "\n"_s);
}

static void checkCompiledTests(OptionWords optionWords)
{
    for (ASCIILiteral way : waysToCompilePrograms) {
        String output = runInShell(optionWords, way);
        if (output != expectedOutput) {
            dataLog(way, " ");
            for (ASCIILiteral word : optionWords)
                dataLog(word, " ");
            dataLogLn("printed:\n", output);
        }
        AOT_TEST_CHECK(output == expectedOutput);
    }
}

static void testCompiledTests()
{
    checkCompiledTests({ "references=wide"_s });
    checkCompiledTests({ "references=narrow"_s });
}

template<LoadedProgramTest body>
static constexpr void (*withProgram)() = runNativeTestWithLoadedProgram<sharingModeAndNamespaceTests, programText, body>;

std::span<const NativeTest> sharingModeAndNamespaceTests()
{
    static constexpr NativeTest tests[] = {
        { "sharing-mode-and-namespace/sharing-mode-of-values"_s, withProgram<testSharingModeOfValues> },
        { "sharing-mode-and-namespace/module-of-namespace-objects"_s, withProgram<testModuleOfNamespaceObjects> },
        { "sharing-mode-and-namespace/require-namespace-does-not-mutate-imports"_s, withProgram<testRequireNamespaceDoesNotMutateImports> },
        { "sharing-mode-and-namespace/require-facade-invalidates-captured-exports"_s, runNativeTestWithLoadedProgram<sharingModeAndNamespaceTests, programWithCapturedExports, testRequireFacadeInvalidatesCapturedExports> },
        { "sharing-mode-and-namespace/compiled-tests"_s, testCompiledTests },
    };
    return tests;
}

} } // namespace JSC::AOT

WTF_ALLOW_UNSAFE_BUFFER_USAGE_END

#endif // ENABLE(AOT)
