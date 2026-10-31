import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";

const { parseJunitFileSuites: parse } = await import(pathToFileURL(process.argv[2]).href);
const file = "test/example.test.ts";
const suite = (tests, body, failures = 0) =>
  `<testsuites><testsuite name="${file}" file="${file}" tests="${tests}" failures="${failures}" time="0">${body}</testsuite></testsuites>`;
const plain = `<testcase name="passes" file="${file}"/>`;
const skipped = `<testcase name="skipped" file="${file}"><skipped/></testcase>`;
const failed = `<testcase name="fails" file="${file}"><failure message="expected failure"/></testcase>`;
const nested = `<testsuite name="${file}" file="${file}">${skipped}${failed}</testsuite>`;

assert.equal(parse(suite(3, plain + nested, 1)).get(file).failures, 1);
assert.deepEqual(parse(suite(0, "")).get(file).cases, []);
assert.equal(parse(`<testsuites><testsuite name="${file}" file="${file}" tests="0" failures="0" time="0"/></testsuites>`).size, 1);
for (const xml of [
  suite(2, ""),
  suite(0, plain),
  suite(1, plain + nested, 1),
  suite(1, `<testcase name="wrong file" file="test/other.test.ts"/>`),
  suite(1, `<testcase name="missing file"/>`),
  suite(1, failed),
  suite(1, plain, 1),
  `<testsuites><testsuite name="${file}" file="${file}" tests="1" failures="0" time="0"/></testsuites>`,
]) {
  assert.throws(() => parse(xml), /invalid native JUnit report/);
}
console.log("native JUnit count and ownership controls passed");
