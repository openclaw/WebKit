//@ runDefault("--compileMainScriptAheadOfTime=1")
function work(options) {
    return Promise.resolve({ n: 1, label: options.callback() });
}
function load() {
    return Promise.resolve([]);
}
async function test() {
    const report = label => () => label;
    const count = (await Promise.all([1, 2].map(() => work({ callback: report("before") })))).reduce((sum, item) => sum + item.n, 0);
    const result = await work({ items: await load(), callback: report("after") });
    if (count !== 2 || result.label !== "after")
        throw new Error("incorrect resumed call");
    return count;
}
test().then(value => {
    if (value !== 2)
        throw new Error("incorrect result");
});
