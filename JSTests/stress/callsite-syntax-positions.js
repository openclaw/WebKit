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
];
for (let iteration = 0; iteration < Math.min(typeof testLoopCount === "number" ? testLoopCount : 20, 100); ++iteration) {
    for (const [fn, line, column, body] of cases) {
        trace = "";
        fn.call(capture);
        const frames = trace.split("\n").filter(line => /:(\d+):(\d+)\)?$/.test(line));
        const position = /:(\d+):(\d+)\)?$/.exec(frames[1]);
        if (!position || +position[1] !== line || +position[2] !== column)
            throw new Error(JSON.stringify({ body, expected: [line, column], trace }));
    }
}
