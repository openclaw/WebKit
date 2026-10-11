//@ runDefault("--compileMainScriptAheadOfTime=1")

// The shell supplies JavaScript source, with no externally serialized typed program.
function add(left, right) { return left + right; }
function check(actual, expected) {
    if (actual !== expected)
        throw new Error("Unexpected result: " + actual);
}

check(isAOTCompiled(add), true);
check(isAOTCompiled(check), true);
for (let index = 0; index < 10; ++index)
    check(add(index, 1), index + 1);
