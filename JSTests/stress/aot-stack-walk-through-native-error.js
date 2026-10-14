//@ runDefault("--compileMainScriptAheadOfTime=1")
//@ runDefault("--compileMainScriptAheadOfTime=1", "--useAOTInlining=0")
//@ runDefault

function errorName()
{
    let callback;
    try {
        callback();
    } catch (error) {
        return error.constructor.name;
    }
    return "nothing";
}
noInline(errorName);

for (let i = 0; i < 10; ++i) {
    if (errorName() !== "TypeError")
        throw new Error("The native call error did not survive its AOT stack walk");
}
