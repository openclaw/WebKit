//@ runDefault("--compileMainScriptAheadOfTime=1", "--useDollarVM=1")
"use strict";
const replacement = { log() { return 42; } };
const lazy = $vm.createGlobalObject();
lazy.console = replacement;
if (lazy.console !== replacement)
    throw new Error("lazy console replacement was lost");
const reified = $vm.createGlobalObject();
const original = reified.console;
reified.console = replacement;
if (reified.console !== replacement || reified.console.log() !== 42)
    throw new Error("reified console replacement was lost");
reified.console = original;
if (reified.console !== original)
    throw new Error("original console was not restored");
