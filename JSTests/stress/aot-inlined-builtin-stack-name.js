//@ runDefault("-m", "--compileMainScriptAheadOfTime=1")

function capture() {
    try {
        [1].map(() => { throw new Error("marker"); });
    } catch (error) {
        return error.stack.split("\n").map(line => line.split("@")[0]);
    }
}

if (!capture().includes("map"))
    throw new Error("An inlined built-in lost its name in the stack trace");
