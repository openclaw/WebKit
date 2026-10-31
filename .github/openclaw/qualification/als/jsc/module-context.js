//@ requireOptions("--useDollarVM=1", "--useImportDefer=1")
function eq(actual, expected, label) {
    if (actual !== expected) throw Error(label + ': expected ' + expected + ', got ' + actual);
}
function scoped(ctx, fn) {
    const previous = $vm.asyncContext();
    $vm.setAsyncContext(ctx);
    try { return fn(); } finally { $vm.setAsyncContext(previous); }
}
let complete = false;
// Exercise a raw import.defer payload before async-context tracking is enabled.
import.defer('./fixtures/unscoped-parent.js').then(ns => {
    eq(ns.value, 137, 'deferred import without ALS');
    complete = true;
}, $vm.abort);
drainMicrotasks();
eq(complete, true, 'unscoped defer completed');
const A = ['A'], B = ['B'];
globalThis.contextLog = [];
let done = 0;
for (const [ctx, file] of [[A, 'a'], [B, 'b']]) {
    scoped(ctx, () => import('./fixtures/' + file + '-parent.js').then(ns => {
        eq($vm.asyncContext(), ctx, 'caller continuation');
        for (const value of ns.contexts) eq(value, ctx, 'graph ' + file);
        done++;
    }, $vm.abort));
}
gc();
drainMicrotasks();
eq(done, 2, 'disjoint graphs completed');
eq($vm.asyncContext(), undefined, 'outside graphs');
let rejected = 0;
scoped(A, () => import('./fixtures/throw.js').then($vm.abort, e => {
    eq(e.message, 'module throw', 'evaluation rejection');
    eq($vm.asyncContext(), A, 'rejection caller');
    rejected++;
}));
scoped(B, () => import('./fixtures/missing.js').then($vm.abort, () => {
    eq($vm.asyncContext(), B, 'load rejection caller');
    rejected++;
}));
drainMicrotasks();
eq(rejected, 2, 'rejections completed');
eq(contextLog[0], A, 'throwing body');
eq($vm.asyncContext(), undefined, 'outside rejection');
let deferred = false;
scoped(A, () => import.defer('./fixtures/deferred-parent.js').then(ns => {
    scoped(B, () => {
        eq(ns.rootContext, B, 'deferred root evaluates at access');
        eq(ns.dependencyContext, A, 'TLA dependency evaluates in importer');
    });
    deferred = true;
}, $vm.abort));
gc();
drainMicrotasks();
eq(deferred, true, 'scoped deferred graph completed');
eq($vm.asyncContext(), undefined, 'outside deferred graph');
