// Exercise cached offsets from independent providers, including equal offsets
// with different line tables, UTF-16 columns, and compressed-table boundaries.
// Alternate two offsets per provider so cached positions cannot bleed between calls.
const sources = [];
for (const terminator of ["\n", "\r\n", "\u2028", "\u2029"]) {
    for (const lines of [0, 1, 63, 64, 65, 127]) {
        const prefix = "/* 🦞 */ ";
        const body = prefix + "[(function positionCacheProbe() { return new Error('cache'); }), (function optionalCacheProbe() { try { (null?.x) /* call */ (); } catch (error) { return error; } })]";
        const source = terminator.repeat(lines) + body;
        const [createError, createTypeError] = eval(source);
        sources.push({ create: createError, type: Error, line: lines + 1, column: body.indexOf("new Error") + 1 });
        sources.push({ create: createTypeError, type: TypeError, line: lines + 1, column: body.indexOf("();") + 1 });
    }
}
for (let repeat = 0; repeat < Math.min(testLoopCount, 30); ++repeat) {
    for (const { create, type, line, column } of sources) {
        const error = create();
        // Anonymous eval frames omit their URL from stack strings, but expose
        // the same computed coordinates through JSC's error properties.
        if (!(error instanceof type) || error.line !== line || error.column !== column)
            throw new Error(`Expected ${type.name} at ${line}:${column}, got ${error.constructor.name} at ${error.line}:${error.column}`);
    }
}
