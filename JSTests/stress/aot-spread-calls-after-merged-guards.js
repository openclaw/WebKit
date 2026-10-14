//@ runDefault("--compileMainScriptAheadOfTime=1")
//@ runDefault("--compileMainScriptAheadOfTime=1", "--useAOTInlining=0")

function loadWithFallback(plan, load, fallback) {
    if (plan.query) {
        try {
            return { rows: load(plan.query, plan.terms) };
        } catch (error) {
            return { rows: load(null, [...fallback(), ...plan.terms]) };
        }
    }
    return { rows: load(null, plan.terms) };
}

function makePlan(options) {
    return { query: "quartz", terms: [], tokens: ["quartz"] };
}

function search(params) {
    if (params.limit <= 0)
        return [];
    const plan = makePlan({
        query: params.query,
        tokenizer: params.tokenizer,
        canonicalVariants: true,
        matchAny: params.matchAny
    });
    if (!plan.query && plan.terms.length === 0)
        return [];
    const load = (query, terms) => {
        const mixed = params.matchAny && query && terms.length > 0;
        return params.target.prepare("").all(
            ...(query ? [query] : []),
            ...(mixed ? [...params.filter.values, params.limit] : []),
            ...terms,
            ...params.filter.values,
            params.limit);
    };
    const { rows } = loadWithFallback(plan, load, () => plan.tokens);
    return rows;
}

const target = {
    prepare(query) {
        return {
            all(...args) { return args.map(value => typeof value).join(","); }
        };
    }
};
const actual = search({ target, filter: { values: ["memory"] }, limit: 10 });
if (actual !== "string,string,number")
    throw new Error("merged spread arguments: " + actual);
