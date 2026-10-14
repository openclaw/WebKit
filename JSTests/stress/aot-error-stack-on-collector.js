//@ requireOptions("--useDollarVM=true")
//@ runDefault("--compileMainScriptAheadOfTime=1")
//@ runDefault("--compileMainScriptAheadOfTime=1", "-m")

const errors = [];
function captureErrors() {
    async function inner() {
        await 1;
        errors.push(new Error("retained stack"));
    }
    async function outer() { await inner(); }
    outer();
}
captureErrors();
drainMicrotasks();
if ($vm.collectWithAOTStackFormatter() < 1)
    throw new Error("the collector did not format a lazy AOT frame");
if (!errors[0].stack.includes("inner") || !errors[0].stack.includes("outer"))
    throw new Error("collector formatting lost the AOT function names");
