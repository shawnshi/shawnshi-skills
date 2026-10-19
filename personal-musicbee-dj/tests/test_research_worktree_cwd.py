"""Verify native workflow parameters without model, audio or network access."""
from pathlib import Path
import subprocess


def test_parallel_cwd_uses_tracked_task_root_not_ignored_batch_folder():
    workflow = Path(__file__).resolve().parents[1] / "src/research_wave.js"
    script = r"""
const fs = require('fs');
(async () => {
  const {runWorkflowScript} = await import('file:///C:/Users/shich/.pi/agent/npm/node_modules/pi-subagents/src/workflows/scripted-workflow.js');
  const source = fs.readFileSync(process.argv[1], 'utf8');
  const launches = [];
  const jobs = [1, 2, 3].map(n => ({
    key: `batch-${n}`, count: 5, cwd: `C:/fixture/task/batches/batch-${n}`,
    input: `C:/fixture/task/batches/batch-${n}/input.csv`, schema: 'C:\\fixture\\task\\tag-schema.json'
  }));
  const execute = args => runWorkflowScript({script: source, args,
    timeoutMs: 10000, globalConcurrencyLimit: 3,
    launch: async (key, params) => { launches.push({key, params}); return {key, ok: true, output: 'synthetic'}; },
    status: async () => { throw Error('Unexpected status'); }
  });
  const result = await execute({parallel: true, jobs});
  if (launches.length !== 3 || result.value.jobs.length !== 3) throw Error('Wrong launch count');
  for (const entry of launches) {
    if (entry.params.cwd !== 'C:/fixture/task' || entry.params.worktree !== true) throw Error('Ignored batch cwd remapped into worktree');
    const job = jobs.find(j => j.key === entry.key);
    if (!entry.params.task.includes(job.input) || !entry.params.task.includes(job.schema)) throw Error('Absolute read input lost');
    if (!entry.params.task.includes('copied byte-for-byte') || !entry.params.task.includes('quote the returned BPM')) throw Error('Source URL fidelity instruction missing');
  }
  const serial = await execute({jobs: [jobs[0]]});
  if (launches[3].params.cwd !== jobs[0].cwd || launches[3].params.worktree !== false) throw Error('Serial contract changed');
  const count = launches.length;
  for (const malformed of [
    jobs.map(job => ({...job, schema: 'relative/tag-schema.json'})),
    [jobs[0], {...jobs[1], schema: 'C:/other/task/tag-schema.json'}]
  ]) {
    let rejected = false;
    try { await execute({parallel: true, jobs: malformed}); }
    catch (error) { rejected = error.message.includes('same task repository'); }
    if (!rejected) throw Error('Unsafe schema root accepted');
  }
  if (launches.length !== count) throw Error('Invalid root reached launch');
  console.log('Native sandbox contract passed: parallel root cwd, managed worktrees, original absolute inputs; no real children launched');
})().catch(error => {console.error(error); process.exit(1);});
"""
    result = subprocess.run(["node", "-e", script, str(workflow)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
