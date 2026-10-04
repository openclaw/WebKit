//@ requireOptions("--useDollarVM=1")

function check(value, message) {
    if (!value)
        throw new Error(message);
}

function checkMarker(namespace, value) {
    check(Object.getPrototypeOf(namespace) === null, "null prototype");
    check(!Object.isExtensible(namespace), "non-extensible namespace");
    check("__esModule" in namespace, "marker in namespace");
    check(Object.prototype.hasOwnProperty.call(namespace, "__esModule"), "own marker");
    const descriptor = Object.getOwnPropertyDescriptor(namespace, "__esModule");
    check(descriptor.value === value && descriptor.writable && descriptor.enumerable && !descriptor.configurable, "marker descriptor");
    check(!Reflect.set(namespace, "__esModule", value), "set fails even for the same value");
    check(!Reflect.deleteProperty(namespace, "__esModule"), "delete fails");
    check(Reflect.defineProperty(namespace, "__esModule", { value }), "same-value define succeeds");
    for (const descriptor of [{ value: {} }, { writable: false }, { enumerable: false }, { configurable: true }, { get() {} }])
        check(!Reflect.defineProperty(namespace, "__esModule", descriptor), "invalid definition fails");
}

async function test() {
    const namespace = await import("./resources/namespace-esmodule-default.js");
    check(!("__esModule" in namespace), "ordinary namespace has no marker");
    check(!Object.prototype.hasOwnProperty.call(namespace, "__esModule"), "no own marker");
    check(Object.getOwnPropertyDescriptor(namespace, "__esModule") === undefined, "no marker descriptor");
    check(!Reflect.set(namespace, "__esModule", true), "cannot create marker with set");
    check(!Reflect.defineProperty(namespace, "__esModule", { value: true }), "cannot create marker with defineProperty");
    // Only Bun embedders request the require(esm) facade.
    if (typeof $vm.moduleNamespaceForRequire !== "function")
        return;
    const required = $vm.moduleNamespaceForRequire(namespace);
    check(required !== namespace, "separate namespace");
    check($vm.moduleNamespaceForRequire(namespace) !== required, "fresh facade for a new require-cache entry");
    check($vm.moduleNamespaceForRequire(required) === required, "already marked facade");
    check(!("__esModule" in namespace), "import remains unmarked");
    checkMarker(required, true);
    check(Reflect.ownKeys(required).map(String).join() === "Alpha,__esModule,_a,bump,default,value,zzz,Symbol(Symbol.toStringTag)", "sorted own keys");
    check(Object.getOwnPropertySymbols(required).length === 1, "marker is not a symbol");
    namespace.bump();
    check(required.value === 2 && namespace.value === 2, "live bindings");
    gc();
    check(required.value === 2, "facade survives collection");
    const explicit = await import("./resources/namespace-esmodule-explicit.js");
    check($vm.moduleNamespaceForRequire(explicit) === explicit, "explicit undefined marker retained");
    checkMarker(explicit, undefined);
    const noDefault = await import("./resources/namespace-esmodule-no-default.js");
    check($vm.moduleNamespaceForRequire(noDefault) === noDefault, "no facade without default");
    check(!("__esModule" in noDefault), "no marker without default");
}

test().catch($vm.abort);
