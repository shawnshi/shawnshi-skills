import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { mergeApprovedPR } from "../scripts/fleet-merge.ts";

const sha = "a".repeat(40);
const approval = {
  FLEET_REPO: "example/repo", FLEET_BASE_BRANCH: "main", FLEET_PR_NUMBER: "7",
  FLEET_HEAD_SHA: sha, FLEET_TASK_ID: "task-1", FLEET_DATE: "2026_09_13",
  FLEET_APPROVED: "true", FLEET_DRY_RUN: "false",
};
const goodPR = {
  number: 7, url: "https://github.com/example/repo/pull/7", state: "OPEN", isDraft: false,
  isCrossRepository: false, baseRefName: "main", headRefOid: sha, headRefName: "jules/123456",
  body: "Session: https://jules.google.com/session/123456", mergeable: "MERGEABLE", mergeStateStatus: "CLEAN",
};

function fixture(t, options = {}) {
  const root = mkdtempSync(path.join(tmpdir(), "fleet-merge-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const dir = path.join(root, ".fleet", approval.FLEET_DATE);
  mkdirSync(dir, { recursive: true });
  writeFileSync(path.join(dir, "issue_tasks.json"), JSON.stringify(options.tasks ?? { tasks: [{ id: "task-1" }] }));
  if (!options.missingMapping) writeFileSync(path.join(dir, "sessions.json"), JSON.stringify(options.sessions ?? [{ taskId: "task-1", sessionId: "123456", repo: "example/repo", prNumber: 7 }]));
  const approvedNumber = options.approvedNumber ?? approval.FLEET_PR_NUMBER;
  const calls = [];
  let views = 0;
  const gh = args => {
    calls.push(args);
    if (options.errorAt === calls.length) throw options.error;
    if (args[0] === "pr") {
      assert.deepEqual(args.slice(2, 5), [approvedNumber, "--repo", "https://github.com/example/repo"]);
      if (args[1] === "view") return JSON.stringify({ ...goodPR, ...options.pr, ...(views++ > 0 ? options.secondPR : {}) });
      if (args[1] === "checks") {
        assert.ok(args.includes("--required"));
        return options.rawChecks ?? JSON.stringify(options.checks ?? [{ name: "required-test", state: "SUCCESS" }]);
      }
    }
    assert.deepEqual(args, ["api", "--hostname", "github.com", `repos/example/repo/pulls/${approvedNumber}/merge`,
      "--method", "PUT", "-f", "merge_method=squash", "-f", `sha=${sha}`]);
    return JSON.stringify(options.mergeResult ?? { merged: true });
  };
  return { root, calls, run: env => mergeApprovedPR({ ...approval, FLEET_PR_NUMBER: approvedNumber, ...env }, root, gh) };
}
const mutations = f => f.calls.filter(args => args.includes("PUT") || args.includes("PATCH") || args.includes("close") || args.includes("update-branch"));

for (const name of Object.keys(approval).filter(k => k !== "FLEET_DRY_RUN")) {
  test(`missing approval input ${name} stops before gh`, t => {
    const f = fixture(t);
    assert.throws(() => f.run({ [name]: undefined }), /approval|required/i);
    assert.equal(f.calls.length, 0);
  });
}
for (const [name, value] of [["FLEET_APPROVED", "false"], ["FLEET_DATE", "../../outside"],
  ["FLEET_PR_NUMBER", "7;echo injected"], ["FLEET_HEAD_SHA", "main"], ["FLEET_DRY_RUN", "yes"]]) {
  test(`invalid input ${name} is rejected`, t => {
    const f = fixture(t); assert.throws(() => f.run({ [name]: value })); assert.equal(f.calls.length, 0);
  });
}
for (const [name, options] of [
  ["missing trusted mapping", { missingMapping: true }],
  ["unknown task", { tasks: { tasks: [{ id: "different" }] } }],
  ["duplicate task", { tasks: { tasks: [{ id: "task-1" }, { id: "task-1" }] } }],
  ["duplicate session", { sessions: [{ taskId: "task-1", sessionId: "123456" }, { taskId: "task-2", sessionId: "123456" }] }],
  ["invalid session token", { sessions: [{ taskId: "task-1", sessionId: ".*" }] }],
]) {
  test(name, t => { const f = fixture(t, options); assert.throws(() => f.run()); assert.equal(f.calls.length, 0); });
}
for (const [name, pr] of [
  ["other bot without fleet membership", { headRefName: "renovate/deps", body: "bot PR", author: { login: "other[bot]" } }],
  ["substring session spoof", { headRefName: "jules/1234567", body: "x123456x" }],
  ["hyphen session suffix spoof", { headRefName: "jules/123456-extra", body: "123456_other" }],
  ["wrong PR", { number: 8 }], ["wrong repo", { url: "https://github.com/other/repo/pull/7" }],
  ["wrong base", { baseRefName: "release" }], ["wrong SHA", { headRefOid: "b".repeat(40) }],
  ["fork", { isCrossRepository: true }], ["draft", { isDraft: true }], ["closed", { state: "CLOSED" }],
  ["conflict", { mergeable: "CONFLICTING", mergeStateStatus: "DIRTY" }],
  ["unknown mergeability", { mergeable: "UNKNOWN" }], ["behind", { mergeStateStatus: "BEHIND" }],
  ["blocked", { mergeStateStatus: "BLOCKED" }],
]) {
  test(name + " has no mutation", t => {
    const f = fixture(t, { pr }); assert.throws(() => f.run()); assert.deepEqual(mutations(f), []);
  });
}
for (const checks of [[], [{ name: "ci", state: "SKIPPED" }], [{ name: "ci", state: "PENDING" }],
  [{ name: "ci", state: "FAILURE" }], [{ name: "ci", state: "SUCCESS" }, { name: "ci2", state: "FAILURE" }],
  [{ name: "", state: "SUCCESS" }], null, {}]) {
  test(`required CI rejects ${JSON.stringify(checks)}`, t => {
    const f = fixture(t, { rawChecks: JSON.stringify(checks) }); assert.throws(() => f.run()); assert.deepEqual(mutations(f), []);
  });
}
test("head changes during CI: stop before merge", t => {
  const f = fixture(t, { secondPR: { headRefOid: "b".repeat(40) } });
  assert.throws(() => f.run(), /approved/); assert.deepEqual(mutations(f), []);
});
for (const errorAt of [1, 2, 3, 4]) {
  test(`native gh failure at call ${errorAt} is preserved`, t => {
    const error = Object.assign(new Error("HTTP 403: Resource not accessible"), { status: 1, stderr: "native diagnostic" });
    const f = fixture(t, { errorAt, error });
    assert.throws(() => f.run(), actual => actual === error);
    assert.equal(mutations(f).length, errorAt === 4 ? 1 : 0);
  });
}
test("malformed CI JSON fails instead of no-data", t => {
  const f = fixture(t, { rawChecks: "not-json" }); assert.throws(() => f.run(), SyntaxError); assert.deepEqual(mutations(f), []);
});
test("legal approval reaches exactly one SHA-bound merge", t => {
  const f = fixture(t); f.run(); assert.equal(f.calls.length, 4); assert.equal(mutations(f).length, 1);
});
test("dry run preserves legal path without mutation", t => {
  const f = fixture(t); f.run({ FLEET_DRY_RUN: "true" }); assert.equal(f.calls.length, 3); assert.deepEqual(mutations(f), []);
});
test("HTTP success with merged=false is still failure", t => {
  const f = fixture(t, { mergeResult: { merged: false, message: "Head branch was modified", code: "sha_mismatch" } });
  assert.throws(() => f.run(), /sha_mismatch/); assert.equal(mutations(f).length, 1);
});
test("CLI error exits nonzero with original diagnostic; git and gh are mocked", () => {
  const preload = `import cp from 'node:child_process'; import {syncBuiltinESMExports} from 'node:module'; cp.execFileSync=()=>{throw Object.assign(new Error('synthetic native failure'),{status:23})}; syncBuiltinESMExports();`;
  const result = spawnSync(process.execPath, ["--import", "data:text/javascript," + encodeURIComponent(preload),
    fileURLToPath(new URL("../scripts/fleet-merge.ts", import.meta.url))], { env: {}, encoding: "utf8", timeout: 10000 });
  assert.equal(result.status, 1); assert.match(result.stderr, /synthetic native failure/); assert.match(result.stderr, /23/);
  assert.doesNotMatch(result.stdout, /Merged approved/);
});

test("omitted dry-run flag defaults to no mutation", t => {
  const f = fixture(t); f.run({ FLEET_DRY_RUN: undefined }); assert.deepEqual(mutations(f), []);
});

for (const confirmed of [true, false]) {
  test(`CLI end-to-end with synthetic fleet records: merged=${confirmed}`, t => {
    const f = fixture(t);
    const preload = `import cp from 'node:child_process'; import {syncBuiltinESMExports} from 'node:module';
      cp.execFileSync=(command,args)=>{
        if(command==='git')return ${JSON.stringify(f.root)};
        if(command!=='gh')throw new Error('Unexpected real command');
        if(args[0]==='pr'&&args[1]==='view')return ${JSON.stringify(JSON.stringify(goodPR))};
        if(args[0]==='pr'&&args[1]==='checks'&&args.includes('--required'))return '[{"name":"ci","state":"SUCCESS"}]';
        if(args[0]==='api'&&args.includes('sha=${sha}')&&args.includes('PUT')){
          console.log('MOCK_SHA_BOUND_MERGE');return ${JSON.stringify(JSON.stringify({merged: confirmed, message: "synthetic merge response"}))};
        }
        throw new Error('Unexpected gh operation: '+JSON.stringify(args));
      }; syncBuiltinESMExports();`;
    const result = spawnSync(process.execPath, ["--import", "data:text/javascript," + encodeURIComponent(preload),
      fileURLToPath(new URL("../scripts/fleet-merge.ts", import.meta.url))], { env: approval, encoding: "utf8", timeout: 10000 });
    assert.equal(result.status, confirmed ? 0 : 1, result.stderr);
    assert.equal(result.stdout.split('MOCK_SHA_BOUND_MERGE').length - 1, 1);
    if (confirmed) assert.match(result.stdout, /Merged approved fleet PR #7/);
    else { assert.doesNotMatch(result.stdout, /Merged approved/); assert.match(result.stderr, /synthetic merge response/); }
  });
}

// A-FLEET-PROVENANCE-01: approval and candidate text cannot establish provenance.
for (const [name, binding] of [
  ["missing", {}], ["missing PR", { repo: "example/repo" }],
  ["missing repo", { prNumber: 7 }],
  ["different PR", { repo: "example/repo", prNumber: 8 }],
  ["different repo", { repo: "other/repo", prNumber: 7 }],
  ["string PR", { repo: "example/repo", prNumber: "7" }],
  ["fractional PR", { repo: "example/repo", prNumber: 7.5 }],
]) {
  test(`trusted PR binding ${name} stops before gh`, t => {
    const f = fixture(t, { sessions: [{ taskId: "task-1", sessionId: "123456", ...binding }] });
    assert.throws(() => f.run(), /trusted fleet PR binding/i);
    assert.equal(f.calls.length, 0);
    assert.deepEqual(mutations(f), []);
  });
}
for (const dryRun of ["true", "false"]) {
  test(`complete session token copied to other approved PR cannot pass (dryRun=${dryRun})`, t => {
    // All approval fields, CI and PR state fit PR 8; trusted session belongs to PR 7.
    // PR 8 copied both the complete branch token and session URL from goodPR.
    const f = fixture(t, { approvedNumber: "8", pr: { ...goodPR, number: 8, url: "https://github.com/example/repo/pull/8" } });
    assert.throws(() => f.run({ FLEET_DRY_RUN: dryRun }), /trusted fleet PR binding/i);
    assert.equal(f.calls.length, 0);
    assert.deepEqual(mutations(f), []);
  });
}
