// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import path from "node:path";
import { readFileSync, realpathSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";

type Environment = Record<string, string | undefined>;
type Gh = (args: string[]) => string;

const runGh: Gh = args => execFileSync("gh", args, {
  encoding: "utf8", timeout: 30_000, stdio: ["ignore", "pipe", "pipe"],
});

// Both manual workflow and local CLI use this one SHA-bound merge path.
// Inputs express an existing approval; PR text or session mappings cannot grant it.
export function mergeApprovedPR(env: Environment, root: string, gh: Gh = runGh): void {
  function required(name: string, pattern?: RegExp): string {
    const value = env[name];
    if (!value || (pattern && !pattern.test(value))) throw new Error(`Missing or invalid approval input: ${name}`);
    return value;
  }
  const repo = required("FLEET_REPO", /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/);
  const base = required("FLEET_BASE_BRANCH");
  const pr = required("FLEET_PR_NUMBER", /^[1-9][0-9]*$/);
  const sha = required("FLEET_HEAD_SHA", /^[0-9a-f]{40}$/);
  const taskId = required("FLEET_TASK_ID", /^[A-Za-z0-9][A-Za-z0-9._-]*$/);
  const date = required("FLEET_DATE", /^[0-9]{4}_[0-9]{2}_[0-9]{2}$/);
  if (env.FLEET_APPROVED !== "true") throw new Error("Explicit approval is required (FLEET_APPROVED=true).");
  if (env.FLEET_DRY_RUN !== undefined && !["true", "false"].includes(env.FLEET_DRY_RUN)) {
    throw new Error("FLEET_DRY_RUN must be true or false.");
  }

  // Read operator-provided records from the trusted baseline, never a PR checkout.
  const trustedRoot = realpathSync(root);
  function fleetRecord(name: string): any {
    const file = path.join(trustedRoot, ".fleet", date, name);
    try {
      const relative = path.relative(trustedRoot, realpathSync(file));
      if (relative.startsWith(`..${path.sep}`) || relative === ".." || path.isAbsolute(relative)) {
        throw new Error("Fleet record resolves outside the trusted repository.");
      }
      return JSON.parse(readFileSync(file, "utf8"));
    } catch (error) {
      throw new Error(`Trusted fleet record prerequisite not satisfied: ${file}`, { cause: error });
    }
  }
  const analysis = fleetRecord("issue_tasks.json");
  const sessions = fleetRecord("sessions.json");
  if (!Array.isArray(analysis?.tasks) || analysis.tasks.filter((t: any) => t?.id === taskId).length !== 1 ||
      !Array.isArray(sessions) || sessions.filter((s: any) => s?.taskId === taskId).length !== 1) {
    throw new Error("Approved task must have exactly one trusted fleet task and session mapping.");
  }
  const session = sessions.find((s: any) => s?.taskId === taskId);
  const sessionId = session.sessionId;
  if (typeof sessionId !== "string" || !/^[A-Za-z0-9_-]+$/.test(sessionId) ||
      sessions.filter((s: any) => s?.sessionId === sessionId).length !== 1) {
    throw new Error("Invalid or ambiguous trusted fleet session ID.");
  }
  // Provenance is supplied independently in trusted records, not copied from PR text.
  if (session.repo !== repo || !Number.isSafeInteger(session.prNumber) ||
      session.prNumber <= 0 || String(session.prNumber) !== pr) {
    throw new Error("Missing or mismatched trusted fleet PR binding (repo/task/session/PR).");
  }
  const sessionToken = new RegExp(`(^|[^A-Za-z0-9_-])${sessionId}($|[^A-Za-z0-9_-])`);
  const repository = ["--repo", `https://github.com/${repo}`];
  function verifyPR(): void {
    const data = JSON.parse(gh(["pr", "view", pr, ...repository, "--json",
      "number,url,state,isDraft,isCrossRepository,baseRefName,headRefOid,headRefName,body,mergeable,mergeStateStatus"]));
    if (String(data.number) !== pr || data.url !== `https://github.com/${repo}/pull/${pr}` ||
        data.baseRefName !== base || data.headRefOid !== sha || data.isCrossRepository !== false ||
        data.state !== "OPEN" || data.isDraft !== false) {
      throw new Error("PR does not match the approved repository/base/PR/head or is not an open non-draft same-repository PR.");
    }
    if (![data.headRefName, data.body].some(value => typeof value === "string" && sessionToken.test(value))) {
      throw new Error("PR is not associated with the approved trusted fleet session.");
    }
    if (data.mergeable !== "MERGEABLE" || data.mergeStateStatus !== "CLEAN") {
      throw new Error("PR is conflicting, blocked, behind or unknown; stop for human action and fresh approval after any head change.");
    }
  }

  verifyPR();
  // Required checks come from repository rules, not an arbitrary list of CI jobs.
  // Native gh errors (including pending checks) stop here without mutating the head.
  const checks = JSON.parse(gh(["pr", "checks", pr, ...repository, "--required", "--json", "name,state"]));
  if (!Array.isArray(checks) || checks.length === 0 ||
      !checks.every(check => typeof check?.name === "string" && check.name.length > 0 && check.state === "SUCCESS")) {
    throw new Error("Nonempty required CI checks must all report SUCCESS; missing, skipped or pending checks stop the merge.");
  }
  verifyPR();
  if (env.FLEET_DRY_RUN !== "false") {
    console.log(`Dry run: approved fleet PR #${pr} at ${sha} passed checks; no merge requested.`);
    return;
  }
  // GitHub atomically rejects a changed head and still enforces server-side protection.
  const result = JSON.parse(gh(["api", "--hostname", "github.com", `repos/${repo}/pulls/${pr}/merge`,
    "--method", "PUT", "-f", "merge_method=squash", "-f", `sha=${sha}`]));
  if (result?.merged !== true) throw new Error(`Merge not confirmed: ${JSON.stringify(result)}`);
  console.log(`Merged approved fleet PR #${pr} at ${sha}.`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const root = execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8", timeout: 30_000 }).trim();
    mergeApprovedPR(process.env, root);
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  }
}
