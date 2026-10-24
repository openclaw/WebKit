#!/usr/bin/env python3
"""Copy the pinned runner with lossless qualification evidence and no batch retries."""
import argparse
import hashlib
import json
from pathlib import Path


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Runner contract changed: {old!r}')
    return text.replace(old, new, 1)


def stage(repo, results):
    scripts = repo / 'scripts'
    runner_path = scripts / 'runner.node.ts'
    entry_path = scripts / 'openclaw-ci/tests.ts'
    runner = runner_path.read_text()
    entry = entry_path.read_text()
    original = runner
    runner = replace_once(runner, '      const { ok, stdout, crashes } = await startGroup(`${range} ${label}`',
                          '      const { ok, stdout, crashes, exitCode, signalCode } = await startGroup(`${range} ${label}`')
    runner = replace_once(runner, '      let suites = new Map<string, JunitFileSuite>();', '''      // Retain the first attempt before upstream's fallback can overwrite its outcome.
      const evidenceDir = process.env.OPENCLAW_QUALIFICATION_RESULTS!;
      writeFileSync(join(evidenceDir, "batch.json"), JSON.stringify({ ok, exitCode, signalCode, files: bucketFiles }, null, 2));
      writeFileSync(join(evidenceDir, "batch.log"), stdout);
      if (existsSync(junitPath)) writeFileSync(join(evidenceDir, "batch.xml"), readFileSync(junitPath));
      if (!ok || exitCode !== 0 || signalCode) throw new Error("Qualification batch failed; refusing fallback retries");
      let suites = new Map<string, JunitFileSuite>();''')
    runner = replace_once(runner, '''          status: "pass",
          tests: [],''', '''          status: "pass",
          exitCode,
          signalCode,
          tests: [],''')
    runner = replace_once(runner, '      stdoutPreview: r.stdoutPreview?.slice?.(-4000),',
                          '      stdoutPreview: r.stdoutPreview?.slice?.(-4000),\n      tests: r.tests,')
    runner = replace_once(runner, '    junitFilePath = `${junitTempDir}/test-${testHash}.xml`;',
                          '    junitFilePath = join(process.env.OPENCLAW_QUALIFICATION_RESULTS!, `test-${testHash}.xml`);')
    entry = replace_once(entry, '"scripts/runner.node.ts",', '"scripts/openclaw-qualification-runner.node.ts",\n        "--junit",')
    (scripts / 'openclaw-qualification-runner.node.ts').write_text(runner)
    (scripts / 'openclaw-ci/qualification-tests.ts').write_text(entry)
    hashes = {name: hashlib.sha256(data.encode()).hexdigest() for name, data in
              [('runner_source', original), ('runner_instrumented', runner),
               ('entry_source', entry_path.read_text()), ('entry_instrumented', entry)]}
    (results / 'runner-instrumentation.json').write_text(json.dumps(hashes, indent=2) + '\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('repo', type=Path)
    p.add_argument('results', type=Path)
    a = p.parse_args()
    stage(a.repo, a.results)
