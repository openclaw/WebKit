import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { engineBuiltinSources } from "../collect-runtime-functions.ts";
import { leftOut } from "../lib.ts";
import type { SourcedDeclaration } from "../declarations.ts";

test("ShadowRealm's disabled source is excluded without AOT member declarations", () => {
  const root = mkdtempSync(join(tmpdir(), "aot-builtin-sources-"));
  try {
    writeFileSync(join(root, "CMakeLists.txt"), `set(JavaScriptCore_BUILTINS_SOURCES
      \${JAVASCRIPTCORE_DIR}/builtins/ArrayPrototype.js
      \${JAVASCRIPTCORE_DIR}/builtins/ShadowRealmPrototype.js
    )\n`);
    const declarations = (paths: string[]): SourcedDeclaration[] =>
      leftOut({ paths, mayBeNamed: true }).map(declaration => ({
        declaration,
        source: { file: "CMakeLists.txt", line: null, origin: "Host", proof: "Structure" },
      }));
    const all = [join(root, "builtins/ArrayPrototype.js"), join(root, "builtins/ShadowRealmPrototype.js")];
    assert.deepEqual(engineBuiltinSources(root, []), all);
    assert.deepEqual(engineBuiltinSources(root, declarations(["ShadowRealmOther"])), all);
    assert.deepEqual(engineBuiltinSources(root, declarations(["ShadowRealm"])), all.slice(0, 1));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
