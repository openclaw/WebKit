// Keep call positions independent of exception-expression divots.
let trace;
function capture() { const stack = new Error().stack; trace = stack; return stack; }
function Capture() { this.stack = new Error().stack; trace = this.stack; }
function factory() { return capture; }
const object = { capture };
const name = "capture";
const cases = [
    [function () {
capture()
    }, 10, 1, "capture()"],
    [function () {
capture /* comment */ ()
    }, 13, 1, "capture /* comment */ ()"],
    [function () {
capture
()
    }, 16, 1, "capture\n()"],
    [function () {
factory()()
    }, 20, 10, "factory()()"],
    [function () {
factory()
()
    }, 24, 1, "factory()\n()"],
    [function () {
factory() /* comment */ ()
    }, 27, 25, "factory() /* comment */ ()"],
    [function () {
object.capture()
    }, 30, 8, "object.capture()"],
    [function () {
object
.capture()
    }, 34, 2, "object\n.capture()"],
    [function () {
object . capture()
    }, 37, 10, "object . capture()"],
    [function () {
object. /* comment */ capture()
    }, 40, 23, "object. /* comment */ capture()"],
    [function () {
object.\u0063apture()
    }, 43, 8, "object.\\u0063apture()"],
    [function () {
object[name]()
    }, 46, 13, "object[name]()"],
    [function () {
object["capture"]()
    }, 49, 18, "object[\"capture\"]()"],
    [function () {
object[
name
]
()
    }, 55, 1, "object[\nname\n]\n()"],
    [function () {
(capture)()
    }, 58, 10, "(capture)()"],
    [function () {
((capture))()
    }, 61, 12, "((capture))()"],
    [function () {
(object.capture)()
    }, 64, 17, "(object.capture)()"],
    [function () {
(object[name])()
    }, 67, 15, "(object[name])()"],
    [function () {
(0, capture)()
    }, 70, 13, "(0, capture)()"],
    [function () {
capture?.()
    }, 73, 10, "capture?.()"],
    [function () {
object?.capture()
    }, 76, 9, "object?.capture()"],
    [function () {
object.capture?.()
    }, 79, 17, "object.capture?.()"],
    [function () {
object?.capture?.()
    }, 82, 18, "object?.capture?.()"],
    [function () {
this()
    }, 85, 5, "this()"],
    [function () {
capture`text`
    }, 88, 8, "capture`text`"],
    [function () {
Reflect.apply(capture, null, [])
    }, 91, 9, "Reflect.apply(capture, null, [])"],
    [function () {
new Capture().stack
    }, 94, 1, "new Capture().stack"],
    [function () {
new
Capture().stack
    }, 97, 1, "new\nCapture().stack"],
    [function () {
new (Capture)().stack
    }, 101, 1, "new (Capture)().stack"],
    [function () {
Reflect.construct(Capture, []).stack
    }, 104, 9, "Reflect.construct(Capture, []).stack"],
    [function () {
(record("base", receiver)?.capture) /* call */ (record("a", 1), record("b", 2));
    }, 107, 48, "parenthesized optional dot call", "base,a,b,call"],
    [function () {
(receiver?.[record("key", name)])
    (record("a", 1), record("b", 2));
    }, 111, 5, "parenthesized optional computed call", "key,a,b,call"],
    [function () {
(receiver?.["tag"]) /* tag */
    `a${record("a", 1)}b${record("b", 2)}c`;
    }, 115, 5, "parenthesized optional bracket tag", "a,b,tag"],
    [function () {
try {
(throwing?.["capture"]) /* call */ (record("arg", 1));
} catch (error) { assertSame(error, getterSentinel); }
    }, 119, 12, "optional static getter throws before arguments", "get"],
    [function () {
try {
(throwing?.[record("key", name)])`a${record("arg", 1)}b`;
} catch (error) { assertSame(error, getterSentinel); }
    }, 124, 12, "optional computed getter throws before substitutions", "key,get"],
    [function () {
null?.[record("key", name)](record("arg", 1));
try {
(null?.[record("key", name)]) /* call */ (record("arg", 1));
} catch (error) {
    assertSame(error instanceof TypeError, true);
    trace = error.stack;
}
    }, 130, 42, "parentheses end optional call short circuit", "arg", 0],
    [function () {
try {
(null?.[record("key", name)]) /* tag */ `a${record("sub", 1)}b`;
} catch (error) {
    assertSame(error instanceof TypeError, true);
    trace = error.stack;
}
    }, 138, 41, "parenthesized optional tag still evaluates substitutions", "sub", 0],
    [function () {
const instance =
Reflect /* gap */ . construct(record("target", Positioned), [record("a", 1), record("b", 2)], record("newTarget", NewTarget), record("extra", 3));
assertSame(Object.getPrototypeOf(instance), NewTarget.prototype);
    }, 146, 21, "Reflect literal arguments and newTarget", "target,a,b,newTarget,extra,construct"],
    [function () {
const instance = Reflect
    .construct(record("target", Positioned), record("array", constructArgs), record("newTarget", NewTarget), record("extra", 3));
assertSame(Object.getPrototypeOf(instance), NewTarget.prototype);
    }, 151, 6, "Reflect varargs and newTarget", "target,array,newTarget,extra,construct"],
    [function () {
const result = (function (Reflect) {
return Reflect /* gap */ . construct(record("target", Positioned), [record("a", 1), record("b", 2)], record("newTarget", NewTarget), record("extra", 3));
})(fallbackReflect);
assertSame(result, fallbackResult);
    }, 156, 28, "shadowed Reflect reconstructs literal arguments", "get,target,a,b,newTarget,extra,fallback"],
];
const events = [];
function assertSame(actual, expected) {
    if (actual !== expected)
        throw new Error(`Expected ${expected}, got ${actual}`);
}
function record(event, value) { events.push(event); return value; }
const receiver = {
    capture(first, second) {
        assertSame(this, receiver);
        assertSame(first, 1);
        assertSame(second, 2);
        events.push("call");
        trace = new Error().stack;
    },
    tag(parts, first, second) {
        assertSame(this, receiver);
        assertSame(parts.join("|"), "a|b|c");
        assertSame(parts.raw.join("|"), "a|b|c");
        assertSame(first, 1);
        assertSame(second, 2);
        events.push("tag");
        trace = new Error().stack;
    },
};
const getterSentinel = {};
const throwing = {
    get capture() {
        assertSame(this, throwing);
        events.push("get");
        trace = new Error().stack;
        throw getterSentinel;
    },
};
function NewTarget() { }
function Positioned(first, second) {
    assertSame(first, 1);
    assertSame(second, 2);
    assertSame(new.target, NewTarget);
    events.push("construct");
    trace = new Error().stack;
}
const constructArgs = [1, 2];
const fallbackResult = {};
const fallbackReflect = {
    get construct() { events.push("get"); return fallbackConstruct; },
};
function fallbackConstruct(target, args, newTarget, extra) {
    assertSame(this, fallbackReflect);
    assertSame(arguments.length, 4);
    assertSame(target, Positioned);
    assertSame(Array.isArray(args), true);
    assertSame(args.length, 2);
    assertSame(args[0], 1);
    assertSame(args[1], 2);
    assertSame(newTarget, NewTarget);
    assertSame(extra, 3);
    events.push("fallback");
    trace = new Error().stack;
    return fallbackResult;
}
for (let iteration = 0; iteration < Math.min(typeof testLoopCount === "number" ? testLoopCount : 20, 100); ++iteration) {
    for (const [fn, line, column, body, expectedEvents, frame = 1] of cases) {
        events.length = 0;
        trace = "";
        fn.call(capture);
        if (expectedEvents !== undefined)
            assertSame(events.join(","), expectedEvents);
        const frames = trace.split("\n").filter(line => /:(\d+):(\d+)\)?$/.test(line));
        const position = /:(\d+):(\d+)\)?$/.exec(frames[frame]);
        if (!position || +position[1] !== line || +position[2] !== column)
            throw new Error(JSON.stringify({ body, expected: [line, column], trace }));
    }
}
