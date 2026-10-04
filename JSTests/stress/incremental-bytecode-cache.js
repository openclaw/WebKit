//@ requireOptions("--useDollarVM=true")

function assert(value, message) {
    if (!value)
        throw new Error(message);
}

if (typeof evalFromIncrementalBytecodeCache === "function") {
    const source = `
        const captured = 40;
        function Both(value) {
            if (new.target) this.value = value + captured;
            else return value + captured;
        }
        function outer(value) {
            let n = value;
            return () => ++n + captured;
        }
        class C {
            #value = captured;
            get value() { return this.#value; }
        }
        function unused() { return () => "late"; }
        ({ Both, outer, C, unused });
    `;
    
    const [cached, updates, before, after] = evalFromIncrementalBytecodeCache(source, original => {
        assert(original.Both(2) === 42, "original call");
        assert(new original.Both(3).value === 43, "original construct");
        assert(original.outer(1)() === 42, "original closure");
        assert(new original.C().value === 40, "original private fields");
    });
    assert(updates >= 3 && after > before, "generated bodies must be appended");
    gc();
    for (let i = 0; i < 10000; ++i) {
        assert(cached.Both(2) === 42, "cached call");
        assert(new cached.Both(3).value === 43, "cached construct");
        assert(cached.outer(1)() === 42, "cached closure");
        assert(new cached.C().value === 40, "cached private fields");
    }
    assert(cached.unused()() === "late", "body not present in the snapshot remains lazy");
    const [cold, count, coldBefore, coldAfter] = evalFromIncrementalBytecodeCache("(function neverCalled() { return 17; })", () => {});
    assert(count === 0 && coldBefore === coldAfter, "unused function must not be promoted");
    gc();
    assert(cold() === 17, "unpromoted body still compiles");
}
