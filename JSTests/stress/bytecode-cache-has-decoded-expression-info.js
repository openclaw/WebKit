//@ runBytecodeCache
//@ runBytecodeCache("--diskCachePayloadIsPersistentForTesting=1")

// UnlinkedCodeBlock::expressionInfoIfDecoded() lets a caller that cannot take a lock or allocate (a sampling hook that
// runs inside malloc) know whether asking a code block for a source position would decode it from the cache payload.
// It must not decode anything itself, and it is non-null once an expression range is requested.

function quiet(a, b) { return a + b; }
function asked(i) { if (i < 0) return null.missing; return new Error("e" + i); }

quiet(1, 2);
asked(0);

// Only code decoded from a persistent cache payload, with the lazy decode on, starts out undecoded: that is the second
// run of the second configuration above.
let options = jscOptions();
let lazy = !!(options.forceDiskCache && options.diskCachePayloadIsPersistentForTesting);

function expectDecoded(fn, expected, when) {
    let actual = $vm.hasDecodedExpressionInfo(fn);
    if (actual !== expected)
        throw new Error(fn.name + " " + when + ": expected " + expected + ", got " + actual + " (lazy: " + lazy + ")");
}

expectDecoded(quiet, !lazy, "after it ran");
expectDecoded(quiet, !lazy, "asked twice"); // asking does not decode
expectDecoded(asked, !lazy, "before its position was resolved");

// Stack positions have their own owned table, so reading them does not decode expression ranges.
let line = /asked@.*:(\d+):\d+/.exec(asked(1).stack);
if (!line || Number(line[1]) !== 9)
    throw new Error("unexpected stack: " + asked(1).stack);
expectDecoded(asked, !lazy, "after its stack position was resolved");

let message;
try { asked(-1); } catch (error) { message = error.message; }
if (!message || !message.includes("null.missing"))
    throw new Error("missing expression range: " + message);
expectDecoded(asked, true, "after its expression range was resolved");

// Resolving a position in one function does not decode another.
expectDecoded(quiet, !lazy, "after another function's position was resolved");
