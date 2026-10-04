"use strict";
const name = "x";
const cases = [
    ['Error', function () {
const error = new Error("test"); return error;
    }, 5, 15],
    ['TypeError', function () {
const error = new TypeError("test"); return error;
    }, 8, 15],
    ['SyntaxError', function () {
const error = new SyntaxError("test"); return error;
    }, 11, 15],
    ['RangeError', function () {
const error = new RangeError("test"); return error;
    }, 14, 15],
    ['ReferenceError', function () {
const error = new ReferenceError("test"); return error;
    }, 17, 15],
    ['EvalError', function () {
const error = new EvalError("test"); return error;
    }, 20, 15],
    ['URIError', function () {
const error = new URIError("test"); return error;
    }, 23, 15],
    ['AggregateError', function () {
const error = new AggregateError([], "test"); return error;
    }, 26, 15],
    ['arrow-new', () => new Error("arrow"), 28, 25],
    ['arrow-type', () => new TypeError("arrow"), 29, 26],
    ['arrow-alias', () => new globalThis.Error("arrow"), 30, 27],
    ['multiline-new', function () {
const error = new
    Error("multiline"); return error;
    }, 32, 15],
    ['constructor-comment', function () {
const error = new /* comment */ Error("comment"); return error;
    }, 36, 15],
    ['null-dot', function () {
try { null.x; } catch (error) { return error; }
    }, 39, 12],
    ['undefined-dot', function () {
try { undefined.x; } catch (error) { return error; }
    }, 42, 17],
    ['null-length', function () {
try { null.length; } catch (error) { return error; }
    }, 45, 12],
    ['null-comment', function () {
try { null . /* comment */ x; } catch (error) { return error; }
    }, 48, 28],
    ['null-escape', function () {
try { null.\u0078; } catch (error) { return error; }
    }, 51, 12],
    ['null-multiline', function () {
try { null
    .x; } catch (error) { return error; }
    }, 55, 6],
    ['null-bracket', function () {
try { null["x"]; } catch (error) { return error; }
    }, 58, 11],
    ['null-number', function () {
try { null[1]; } catch (error) { return error; }
    }, 61, 11],
    ['null-computed', function () {
try { null[name]; } catch (error) { return error; }
    }, 64, 11],
    ['null-call', function () {
try { null.x(); } catch (error) { return error; }
    }, 67, 12],
    ['null-parenthesized-call', function () {
try { (null.x)(); } catch (error) { return error; }
    }, 70, 13],
    ['null-bracket-call', function () {
try { null["x"](); } catch (error) { return error; }
    }, 73, 11],
    ['null-call-method', function () {
try { null.call(); } catch (error) { return error; }
    }, 76, 12],
    ['null-apply-method', function () {
try { null.apply(null, []); } catch (error) { return error; }
    }, 79, 12],
    ['null-has-own', function () {
try { null.hasOwnProperty(name); } catch (error) { return error; }
    }, 82, 12],
 ];
function checkPosition(error, line, column, shape, structured) {
    const frames = structured ? error.stack : error.stack.split("\n").filter(frame => /:(\d+):(\d+)\)?$/.test(frame));
    const actual = structured ? [frames[0].getLineNumber(), frames[0].getColumnNumber()] : /:(\d+):(\d+)\)?$/.exec(frames[0])?.slice(1).map(Number);
    if (!actual || actual[0] !== line || actual[1] !== column)
        throw new Error(JSON.stringify({ shape, structured, expected: [line, column], actual, trace: structured ? frames.map(String) : error.stack }));
}
for (let iteration = 0; iteration < Math.min(typeof testLoopCount === "number" ? testLoopCount : 20, 100); ++iteration) {
    for (const [shape, create, line, column] of cases) {
        checkPosition(create(), line, column, shape, false);
        if (typeof process !== "undefined") {
            const previous = Error.prepareStackTrace;
            try {
                Error.prepareStackTrace = (_, frames) => frames;
                checkPosition(create(), line, column, shape, true);
            } finally {
                Error.prepareStackTrace = previous;
            }
        }
    }
}
