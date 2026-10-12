//@ runDefault("--compileMainScriptAheadOfTime=1", "--useAOTFunctionSource=1")
function plain(x) { return x + 1; }
const arrow = x => x * 2;
async function later(x) { return x + 3; }
function* sequence() { yield 4; }
class Item { constructor(x) { this.x = x; } }
function check(actual, expected) {
    if (actual !== expected)
        throw new Error(String(actual) + " !== " + String(expected));
}
check(plain(1), 2);
check(arrow(2), 4);
check(sequence().next().value, 4);
check(new Item(5).x, 5);
check(plain.toString(), "function plain(x) { return x + 1; }");
check(arrow.toString(), "x => x * 2");
check(later.toString(), "async function later(x) { return x + 3; }");
check(sequence.toString(), "function* sequence() { yield 4; }");
check(Item.toString(), "class Item { constructor(x) { this.x = x; } }");
check(eval("(" + plain.toString() + ")")(8), 9);
check(eval("(" + arrow.toString() + ")")(8), 16);
eval("(" + later.toString() + ")")(8).then(value => check(value, 11));
