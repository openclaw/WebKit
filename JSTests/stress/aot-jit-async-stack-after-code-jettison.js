//@ requireOptions("--forceCodeBlockToJettisonDueToOldAge=true", "--useEagerCodeBlockJettisonTiming=true")
//@ runDefault()

async function inner() {
    await 1;
    fullGC();
    const error = new Error("async stack");
    if (!error.stack.includes("outer"))
        throw new Error("missing async parent: " + error.stack);
}
async function outer() { await inner(); }
outer();
drainMicrotasks();
