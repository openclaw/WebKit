//@ runDefault("--compileMainScriptAheadOfTime=1", "--useAOTGuardsAtEveryGuessedPlaceForTesting=1", "--useAOTOperationCounters=1")
//@ runDefault("--compileMainScriptAheadOfTime=1", "--useAOTGuardsAtEveryGuessedPlaceForTesting=1")
//@ runDefault("--compileMainScriptAheadOfTime=1", "--useAOTGuardsAtEveryGuessedPlaceForTesting=1", "--failEveryNthAOTGuardForTesting=1")
//@ runDefault("--compileMainScriptAheadOfTime=1", "--useAOTGuardsAtEveryGuessedPlaceForTesting=1", "--failEveryNthAOTGuardForTesting=2")
//@ runDefault("--compileMainScriptAheadOfTime=1", "--useAOTGuardsAtEveryGuessedPlaceForTesting=1", "--failEveryNthAOTGuardForTesting=3")
//@ runDefault("--compileMainScriptAheadOfTime=1", "--useAOTGuardsAtEveryGuessedPlaceForTesting=1", "--useAOTOperationCounters=1", "--useAOTInlining=0")
//@ runDefault("--compileMainScriptAheadOfTime=1")
//@ runDefault
function check(actual, expected, what) {
    if (!Object.is(actual, expected))
        throw new Error(what + ": " + String(actual) + " instead of " + String(expected));
}
const remarksOf = f => typeof aotRemarks === "function" && aotRemarks(f.name) || null;
const options = typeof jscOptions === "function" ? jscOptions() : { };
const isCompiled = !!remarksOf(check);
const isOn = isCompiled && !!options.useAOTDataStubs && !!options.useAOTGuardsAtEveryGuessedPlaceForTesting;
const isCounting = isOn && !!options.useAOTOperationCounters && !options.failEveryNthAOTGuardForTesting;
const exits = () => isCounting ? ["not-a-cell", "without-number", "with-another-number", "departed"].reduce((sum, why) => sum + (aotOperationCount("exit-into-generic-copy:exits-" + why) || 0), 0) : 0;
const hasTwin = f => remarksOf(f).includes("guards-over-whole-function");
const frames = (stack, count = 9) => { const lines = String(stack).split("\n"); const end = lines.findIndex(line => line.startsWith("run@")); return lines.slice(0, Math.min(count, end < 0 ? count : end)).map(line => line.replace(/@.*?(:\d+:\d+)?$/, "@$1")).join(" "); };
const describe = e => e.constructor.name + " " + e.message + " at " + e.line + ":" + e.column + " " + frames(e.stack);

function Item(tag, key, child) { this.tag = tag; this.key = key; this.child = child; }
const strangeNames = ["other", "tag", "key", "child"];
const member = () => new Item("t", "k", "c");
const stranger = () => { const o = { }; for (const name of strangeNames) o[name] = name[0]; return o; };

function throwsItself(o, when) {
    const a = o.tag;
    if (when === 1) throw new Error("one");
    const b = o.key;
    if (when === 2) throw new Error("two");
    const c = o.child;
    if (when === 3) throw new Error("three");
    return a + b + c;
}
function fails(when, position) { if (when === position) throw new Error("callee at " + position); return position; }
noInline(fails);
function callsOut(o, when) {
    const a = o.tag; fails(when, 1);
    const b = o.key; fails(when, 2); const c = o.child; fails(when, 3);
    return a + b + c;
}
function small(when, position) { if (when === position) throw new Error("inlined at " + position); return position; }
function inlines(o, when) {
    const a = o.tag; small(when, 1);
    const b = o.key; small(when, 2);
    const c = o.child; small(when, 3);
    return a + b + c;
}
function catchesItself(o, when) {
    let seen = "nothing";
    try {
        const a = o.tag; fails(when, 1);
        const b = o.key; if (when === 2) throw new Error("own two");
        const c = o.child; small(when, 3);
        seen = a + b + c;
    } catch (e) {
        seen = describe(e) + " then " + o.child;
    } finally {
        seen += " finally " + o.key;
    }
    return seen;
}
function quotes(o, when) {
    const a = o.tag;
    if (when === 1) a.nothing.more;
    const b = o.key;
    if (when === 2) b();
    const c = o.child;
    if (when === 3) new c;
    return a + b + c;
}
const withGetter = { get bad() { throw new Error("getter"); } };
function readsGetter(o, when) {
    const a = o.tag;
    const x = when === 1 ? withGetter.bad : 0;
    const b = o.key;
    const y = when === 2 ? withGetter.bad : 0;
    const c = o.child;
    const z = when === 3 ? withGetter.bad : 0;
    return a + b + c + x + y + z;
}
function callsHost(o, when) {
    const a = o.tag;
    const x = [1, 2].map(v => { if (when === 1) throw new Error("callback one"); return v; });
    const b = o.key;
    const y = "ab".replace(/a/, () => { if (when === 2) throw new Error("callback two"); return "z"; });
    const z = JSON.parse("[1]", () => { if (when === 3) throw new Error("reviver"); return 1; });
    return a + b + o.child + x + y + z;
}
let marks = [];
function mark(result) { marks.push(frames(new Error().stack, 4)); return result; }
noInline(mark);
const helpers = {
    plain() { return mark(1); }, get getter() { return mark(2); }, set setter(v) { mark(3); }, Made: function () { mark(4); }, tag() { return mark(5); },
    text: { toString() { return mark("6"); } }, number: { valueOf() { return mark(7); } }, primitive: { [Symbol.toPrimitive]() { return mark(8); } },
    proxy: new Proxy({ }, { has() { return mark(true); }, get() { return mark(9); }, set() { return mark(true); }, deleteProperty() { return mark(true); }, ownKeys() { return mark([]); } }),
    Judge: { [Symbol.hasInstance]() { return mark(true); } },
    iterable: { [Symbol.iterator]() { mark(0); return { next() { return mark({ done: false, value: 1 }); }, return() { return mark({ }); } }; } },
};
function callsInManyWays(o, h) {
    let sum = o.tag;
    sum += h.plain(); sum += h.getter; h.setter = 1; sum += o.key;
    new h.Made; sum += h.plain(...[1, 2]); sum += h.plain?.(); sum += h.tag`x`; sum += o.child;
    sum += `${h.text}`; sum += h.number + 1; sum += h.primitive * 2; sum += o.tag;
    sum += "x" in h.proxy; sum += h.proxy.y; h.proxy.z = 1; delete h.proxy.w; sum += typeof { ...h.proxy }; sum += o.key;
    sum += o instanceof h.Judge; for (const v of h.iterable) { sum += v; break; } const [first] = h.iterable; sum += first + o.child;
    sum += h.plain.call(h); sum += h.plain.apply(h, []); sum += h.plain.bind(h)(); sum += Reflect.apply(h.plain, h, []); sum += [3, 1].sort((x, y) => mark(x - y)).length;
    return sum + o.tag;
}
function looksAtItself(o, extra) {
    const a = o.tag, b = o.key, c = o.child;
    return [a + b + c, arguments.length, arguments[1], arguments[2], arguments.callee === looksAtItself, new.target === undefined, this === undefined || this === globalThis].join();
}
function Made(o) { this.sum = o.tag + o.key + o.child; this.target = new.target === Made ? "Made" : new.target ? new.target.name : "none"; }
class Derived extends Made { }
async function awaits(o, when) { await 0; return throwsItself(o, when); }
async function awaitsTwice(o, when) { const value = await awaits(o, when); return value + "!"; }
const trapped = () => new Proxy(member(), { get(target, name) { if (name === "child") throw new Error("trap " + name); return target[name]; } });
function readsAll(o) { const a = o.tag; const b = o.key; const c = o.child; return a + b + c; }
const dynamicName = ["tag"];
function hasNoTwin(o) { return o[dynamicName[0]]; }
noInline(hasNoTwin);

const twins = [throwsItself, callsOut, inlines, catchesItself, quotes, readsGetter, callsHost, callsInManyWays, looksAtItself, Made, readsAll];
function attempt(f, ...args) { try { return "returned " + f(...args); } catch (e) { return describe(e); } }
noInline(attempt);
function recordsOf(make, leaves) {
    const records = [];
    const run = (what, body, hasSecondCopy = true) => {
        const before = exits();
        records.push(what + ": " + body());
        if (isCounting)
            check(exits() > before, leaves && hasSecondCopy, what + " leaves the first copy");
    };
    for (const f of [throwsItself, callsOut, inlines, catchesItself, quotes, readsGetter, callsHost]) {
        for (const when of [0, 1, 2, 3])
            run(f.name + " " + when, () => attempt(f, make(), when));
    }
    run("callsInManyWays", () => { marks = []; return attempt(callsInManyWays, make(), helpers) + " " + marks.length + " " + marks.join(" ; "); });
    run("looksAtItself", () => looksAtItself(make(), "extra", 3));
    run("Made, constructed", () => JSON.stringify([new Made(make()), new Derived(make()), Reflect.construct(Made, [make()], Item)]), false);
    run("Made, called", () => { const made = { }; Made.call(made, make()); return JSON.stringify(made); });
    for (const when of [2, 3]) {
        run("awaitsTwice " + when, () => { let result; awaitsTwice(make(), when).then(v => result = "returned " + v, e => result = describe(e)); drainMicrotasks(); return result; });
    }
    return records;
}
const ofMembers = recordsOf(member, false);
const ofStrangers = recordsOf(stranger, true);
const ofProxy = attempt(readsAll, trapped());

if (isCompiled) {
    for (const f of twins)
        check(hasTwin(f) || !isOn, true, f.name + " has a second copy");
    check(hasTwin(hasNoTwin), false, "hasNoTwin has a second copy");
    const before = exits();
    check(hasNoTwin(stranger()), "t", "hasNoTwin");
    check(exits(), before, "exits counted for a function without a second copy");
}
for (const f of twins) {
    check(f.toString().includes("[native code]"), hasNoTwin.toString().includes("[native code]"), "the text of " + f.name + " is hidden");
    check(Object.getOwnPropertyNames(f).join(), Object.getOwnPropertyNames(hasNoTwin).join(), "the properties of " + f.name);
}
check([throwsItself, callsInManyWays, looksAtItself, Made].map(f => f.name + f.length).join(), "throwsItself2,callsInManyWays2,looksAtItself2,Made1", "names and lengths");

function passes(value) { return value; }
noInline(passes);
function spins(o, n) {
    let sum = 0;
    for (let i = 0; i < n; ++i) {
        sum += passes(o.tag.length) + o.key.length;
        sum += Math.sqrt(o.child.length + i) | 0;
    }
    return sum;
}
noInline(spins);
if (typeof startSamplingProfiler === "function") {
    const first = Number(/@:(\d+)/.exec(frames((() => { try { spins(null, 1); } catch (e) { return e.stack; } })(), 1))[1]) - 3;
    startSamplingProfiler();
    for (const make of [member, stranger]) {
        let seen = 0;
        const before = exits();
        for (let round = 0; round < 200 && !seen; ++round) {
            spins(make(), 2e6);
            for (const trace of samplingProfilerStackTraces().traces) {
                for (const frame of trace.frames) {
                    if (frame.name !== "spins")
                        continue;
                    ++seen;
                    check((frame.line >= first && frame.line <= first + 7) || (!isCompiled && frame.line === 0xffffffff), true, "a sample of spins is at line " + frame.line + ", within the function");
                }
            }
        }
        check(seen > 0, true, "samples of spins were seen");
        if (isCounting)
            check(exits() > before, make === stranger, "spins leaves the first copy");
    }
    if (isCompiled)
        check(hasTwin(spins), !!options.useAOTDataStubs, "spins has a second copy");
}

const expected = [
    "throwsItself 0: returned tkc",
    "throwsItself 1: Error one at 30:27 throwsItself@:30:27 attempt@:127:59 @:139:44",
    "throwsItself 2: Error two at 32:27 throwsItself@:32:27 attempt@:127:59 @:139:44",
    "throwsItself 3: Error three at 34:27 throwsItself@:34:27 attempt@:127:59 @:139:44",
    "callsOut 0: returned tkc",
    "callsOut 1: Error callee at 1 at 37:63 fails@:37:63 callsOut@:40:22 attempt@:127:59 @:139:44",
    "callsOut 2: Error callee at 2 at 37:63 fails@:37:63 callsOut@:41:22 attempt@:127:59 @:139:44",
    "callsOut 3: Error callee at 3 at 37:63 fails@:37:63 callsOut@:41:57 attempt@:127:59 @:139:44",
    "inlines 0: returned tkc",
    "inlines 1: Error inlined at 1 at 44:63 small@:44:63 inlines@:46:22 attempt@:127:59 @:139:44",
    "inlines 2: Error inlined at 2 at 44:63 small@:44:63 inlines@:47:22 attempt@:127:59 @:139:44",
    "inlines 3: Error inlined at 3 at 44:63 small@:44:63 inlines@:48:24 attempt@:127:59 @:139:44",
    "catchesItself 0: returned tkc finally k",
    "catchesItself 1: returned Error callee at 1 at 37:63 fails@:37:63 catchesItself@:54:26 attempt@:127:59 @:139:44 then c finally k",
    "catchesItself 2: returned Error own two at 55:48 catchesItself@:55:48 attempt@:127:59 @:139:44 then c finally k",
    "catchesItself 3: returned Error inlined at 3 at 44:63 small@:44:63 catchesItself@:56:28 attempt@:127:59 @:139:44 then c finally k",
    "quotes 0: returned tkc",
    "quotes 1: TypeError undefined is not an object (evaluating 'a.nothing.more') at 67:31 quotes@:67:31 attempt@:127:59 @:139:44",
    "quotes 2: TypeError b is not a function. (In 'b()', 'b' is \"k\") at 69:21 quotes@:69:21 attempt@:127:59 @:139:44",
    "quotes 3: TypeError \"c\" is not a constructor (evaluating 'new c') at 71:21 quotes@:71:21 attempt@:127:59 @:139:44",
    "readsGetter 0: returned tkc000",
    "readsGetter 1: Error getter at 74:40 bad@:74:40 readsGetter@:77:39 attempt@:127:59 @:139:44",
    "readsGetter 2: Error getter at 74:40 bad@:74:40 readsGetter@:79:39 attempt@:127:59 @:139:44",
    "readsGetter 3: Error getter at 74:40 bad@:74:40 readsGetter@:81:39 attempt@:127:59 @:139:44",
    "callsHost 0: returned tkc1,2zb1",
    "callsHost 1: Error callback one at 86:55 @:86:55 map@ callsHost@:86:22 attempt@:127:59 @:139:44",
    "callsHost 2: Error callback two at 88:63 @:88:63 replace@ callsHost@:88:20 attempt@:127:59 @:139:44",
    "callsHost 3: Error reviver at 89:63 @:89:63 parse@ callsHost@:89:20 attempt@:127:59 @:139:44",
    "callsInManyWays: returned t12k115c6816ttrue9objectktrue11c11112t 27 mark@:93:43 plain@:96:22 callsInManyWays@:104:14 attempt@:127:59 ; mark@:93:43 getter@:96:56 callsInManyWays@:104:32 attempt@:127:59 ; mark@:93:43 setter@:96:84 callsInManyWays@:104:41 attempt@:127:59 ; mark@:93:43 Made@:96:116 callsInManyWays@:105:5 attempt@:127:59 ; mark@:93:43 plain@:96:22 callsInManyWays@:105:26 attempt@:127:59 ; mark@:93:43 plain@:96:22 callsInManyWays@:105:60 attempt@:127:59 ; mark@:93:43 tag@:96:143 callsInManyWays@:105:76 attempt@:127:59 ; mark@:93:43 toString@:97:33 callsInManyWays@:106:16 attempt@:127:59 ; mark@:93:43 valueOf@:97:78 callsInManyWays@:106:32 attempt@:127:59 ; mark@:93:43 @:97:137 callsInManyWays@:106:53 attempt@:127:59 ; mark@:93:43 has@:98:44 callsInManyWays@:107:19 attempt@:127:59 ; mark@:93:43 get@:98:74 callsInManyWays@:107:43 attempt@:127:59 ; mark@:93:43 set@:98:101 callsInManyWays@:107:53 attempt@:127:59 ; mark@:93:43 deleteProperty@:98:142 callsInManyWays@:107:77 attempt@:127:59 ; mark@:93:43 ownKeys@:98:176 callsInManyWays@:107:93 attempt@:127:59 ; mark@:93:43 @:99:46 callsInManyWays@:108:25 attempt@:127:59 ; mark@:93:43 @:100:39 callsInManyWays@:108:47 attempt@:127:59 ; mark@:93:43 next@:100:73 callsInManyWays@:108:47 attempt@:127:59 ; mark@:93:43 return@:100:127 callsInManyWays@:108:47 attempt@:127:59 ; mark@:93:43 @:100:39 callsInManyWays@:108:89 attempt@:127:59 ; mark@:93:43 next@:100:73 callsInManyWays@:108:89 attempt@:127:59 ; mark@:93:43 return@:100:127 callsInManyWays@:108:89 attempt@:127:59 ; mark@:93:43 plain@:96:22 callsInManyWays@:109:20 attempt@:127:59 ; mark@:93:43 plain@:96:22 callsInManyWays@:109:44 attempt@:127:59 ; mark@:93:43 plain@:96:22 callsInManyWays@:109:80 attempt@:127:59 ; mark@:93:43 plain@:96:22 callsInManyWays@:109:99 attempt@:127:59 ; mark@:93:43 @:109:151 sort@ callsInManyWays@:109:136",
    "looksAtItself: tkc,3,extra,3,true,true,true",
    "Made, constructed: [{\"sum\":\"tkc\",\"target\":\"Made\"},{\"sum\":\"tkc\",\"target\":\"Derived\"},{\"sum\":\"tkc\",\"target\":\"Item\"}]",
    "Made, called: {\"sum\":\"tkc\",\"target\":\"none\"}",
    "awaitsTwice 2: Error two at 32:27 throwsItself@:32:27 awaits@:118:50 async awaitsTwice@:119:53 drainMicrotasks@ @:146:146",
    "awaitsTwice 3: Error three at 34:27 throwsItself@:34:27 awaits@:118:50 async awaitsTwice@:119:53 drainMicrotasks@ @:146:146",
];
check(ofMembers.length, expected.length, "the number of records");
for (let i = 0; i < expected.length; ++i) {
    check(ofMembers[i], expected[i], "in the first copy");
    check(ofStrangers[i], expected[i], "in the second copy");
}
check(ofProxy, "Error trap child at 120:93 get@:120:93 readsAll@:121:70 attempt@:127:59 global code@:152:17", "a proxy");
