// Exercise cached offsets from independent providers, including equal offsets
// with different line tables, UTF-16 columns, and compressed-table boundaries.
const sources = [];
for (const terminator of ["\n", "\r\n", "\u2028", "\u2029"]) {
    for (const lines of [0, 1, 63, 64, 65, 127]) {
        const prefix = "/* 🦞 */ ";
        const body = prefix + "(function positionCacheProbe() { return new Error('cache'); })";
        const source = terminator.repeat(lines) + body;
        sources.push({ create: eval(source), line: lines + 1, column: body.indexOf("new Error") + 1 });
    }
}
for (let repeat = 0; repeat < Math.min(testLoopCount, 30); ++repeat) {
    for (const { create, line, column } of sources) {
        const error = create();
        // Anonymous eval frames omit their URL from stack strings, but expose
        // the same computed coordinates through JSC's error properties.
        if (error.line !== line || error.column !== column)
            throw new Error(`Expected ${line}:${column}, got ${error.line}:${error.column}`);
    }
}
