---
name: skill-creator
version: 3.4.0
description: |
  技能工厂与自愈中心 (Native Agent Edition)。当用户想“创建新技能”、“优化既有指令”、“运行技能评测”或技能出现“重复性失败”需要 .amendify() 时，务必激活。
  本技能管理系统的进化闭环，确保新技能遵循“四层壳模型”：物理硬锁、语义主权、负熵交互与持续进化。
  Native tools integration: ask_user, write_file, glob, grep_search, google_web_search, save_memory.
---

# Skill Creator (Native Agent Edition)

“工具的本质是意志的延伸。在这里，我们不生产简单的功能，我们构建确定性。”

---

## 1. 核心架构原则 (Architectural Principles)
遵循“四层壳模型”支撑下的技能范式，实现**代码液态化**与**业务语义固态化**的动态平衡：

### A. 物理层：算力主权与环境隔离 (Physics)
- **物理硬锁**：所有技能必须在本地物理目录内闭环执行，严禁依赖外部云端黑盒。
- **路径归一化**：强制统一路径风格，确保 Windows/Unix 环境下的逻辑同态。

### B. 逻辑层：语义主权与 MSL 约束 (Logic)
- **MSL 原子化**：业务逻辑必须封装为原子化 Skill。代码是液态消费品，语义协议是固态资产。
- **Schema 绝对防御**：[Template] 标记的输出必须 100% 同态映射，严禁执行摘要式逻辑脱水。
- **语义守恒**：允许实现路径突变，但核心业务语义必须在重构前后保持恒定。

### C. 执行层：负熵交互与 OODA 闭环 (Execution)
- **脑暴倾倒 + 查漏补缺**：废除串行审讯，采用高带宽初始输入 + 静默映射 + 聚合追问模式。
- **聚合批处理**：在评审任务中整合决策节点，最大化保护用户心流，实现极致的交互负熵。
- **Markdown 原生可视化**：强制使用 Mermaid 进行架构描述，弃用不稳定的 UI 截图。

### D. 进化层：自愈能力与证据网 (Evolution)
- **失效先验 (Gotchas)**：将重复性失败硬编码为 SKILL.md 顶部的禁令，实现系统的对抗性进化。
- **证据网 (Evidence-Mesh)**：分析类资产必须强制执行物理归档至 `MEMORY/skill_audit/`，严禁仅保留在瞬时对话历史中。
- **量化反思**：通过 `mentat-system-retro` 审计遥测数据，以数据驱动系统拓扑的持续优化。

---
A skill for creating new skills and iteratively improving them.

At a high level, the process of creating a skill goes like this:

Decide what you want the skill to do and roughly how it should do it
Write a draft of the skill
Create a few test prompts and run claude-with-access-to-the-skill on them
Help the user evaluate the results both qualitatively and quantitatively
While the runs happen in the background, draft some quantitative evals if there aren't any (if there are some, you can either use as is or modify if you feel something needs to change about them). Then explain them to the user (or if they already existed, explain the ones that already exist)
Use the eval-viewer/generate_review.py script to show the user the results for them to look at, and also let them look at the quantitative metrics
Rewrite the skill based on feedback from the user's evaluation of the results (and also if there are any glaring flaws that become apparent from the quantitative benchmarks)
Repeat until you're satisfied
Expand the test set and try again at larger scale
Your job when using this skill is to figure out where the user is in this process and then jump in and help them progress through these stages. So for instance, maybe they're like "I want to make a skill for X". You can help narrow down what they mean, write a draft, write the test cases, figure out how they want to evaluate, run all the prompts, and repeat.

On the other hand, maybe they already have a draft of the skill. In this case you can go straight to the eval/iterate part of the loop.

Of course, you should always be flexible and if the user is like "I don't need to run a bunch of evaluations, just vibe with me", you can do that instead.

Then after the skill is done (but again, the order is flexible), you can also run the skill description improver, which we have a whole separate script for, to optimize the triggering of the skill.

Cool? Cool.

## Communicating with the user
The skill creator is liable to be used by people across a wide range of familiarity with coding jargon. If you haven't heard (and how could you, it's only very recently that it started), there's a trend now where the power of Claude is inspiring plumbers to open up their terminals, parents and grandparents to google "how to install npm". On the other hand, the bulk of users are probably fairly computer-literate.

So please pay attention to context cues to understand how to phrase your communication! In the default case, just to give you some idea:

"evaluation" and "benchmark" are borderline, but OK
for "JSON" and "assertion" you want to see serious cues from the user that they know what those things are before using them without explaining them
It's OK to briefly explain terms if you're in doubt, and feel free to clarify terms with a short definition if you're unsure if the user will get it.

## Creating a skill
Capture Intent & ADK Pattern Diagnosis
Start by understanding the user's intent. The current conversation might already contain a workflow the user wants to capture (e.g., they say "turn this into a skill"). If so, extract answers from the conversation history first — the tools used, the sequence of steps, corrections the user made, input/output formats observed. The user may need to fill the gaps, and should confirm before proceeding to the next step.

What should this skill enable the AI to do?
When should this skill trigger? (what user phrases/contexts)
[MANDATORY] ADK Pattern Diagnosis: Ask the user or deduce from context which of the following 5 Google ADK patterns apply. A single skill may use multiple patterns:
[Tool Wrapper]: Does it need to load specific API knowledge, external tools, or non-public framework docs on demand? (Compensates for knowledge latency).
[Generator]: Does it have a strict, non-negotiable output format or MSL Schema? (Compensates for creative drift/hallucinations).
[Pipeline]: Must the steps be executed in a strict, unskippable order with diamond gates? (Compensates for the AI's tendency to skip steps).
[Inversion]: Must the AI collect all necessary parameters/context before taking any action? (Compensates for acting on incomplete info).
[Reviewer]: Is this a high-stakes task requiring the AI to switch to a 'critic' persona and verify its own output before finalizing? (Compensates for confirmation bias).
What's the expected output format?
Should we set up test cases to verify the skill works? Skills with objectively verifiable outputs (file transforms, data extraction, code generation, fixed workflow steps) benefit from test cases. Skills with subjective outputs (writing style, art) often don't need them. Suggest the appropriate default based on the skill type, but let the user decide.
Interview and Research
Proactively ask questions about edge cases, input/output formats, example files, success criteria, and dependencies. Wait to write test prompts until you've got this part ironed out.

Check available MCPs - if useful for research (searching docs, finding similar skills, looking up best practices), research in parallel via subagents if available, otherwise inline. Come prepared with context to reduce burden on the user.

## Write the SKILL.md
Based on the user interview, fill in these components:

name: Skill identifier
description: When to trigger, what it does. This is the primary triggering mechanism - include both what the skill does AND specific contexts for when to use it. All "when to use" info goes here, not in the body. Note: currently Claude has a tendency to "undertrigger" skills -- to not use them when they'd be useful. To combat this, please make the skill descriptions a little bit "pushy". So for instance, instead of "How to build a simple fast dashboard to display internal Anthropic data.", you might write "How to build a simple fast dashboard to display internal Anthropic data. Make sure to use this skill whenever the user mentions dashboards, data visualization, internal metrics, or wants to display any kind of company data, even if they don't explicitly ask for a 'dashboard.'"
compatibility: Required tools, dependencies (optional, rarely needed)
the rest of the skill :)
Skill Writing Guide
Anatomy of a Skill
skill-name/
├── SKILL.md (required)
│   ├── YAML frontmatter (name, description required)
│   └── Markdown instructions
└── Bundled Resources (optional)
    ├── scripts/    - Executable code for deterministic/repetitive tasks
    ├── references/ - Docs loaded into context as needed
    └── assets/     - Files used in output (templates, icons, fonts)
Progressive Disclosure
Skills use a three-level loading system:

Metadata (name + description) - Always in context (~100 words)
SKILL.md body - In context whenever skill triggers (<500 lines ideal)
Bundled resources - As needed (unlimited, scripts can execute without loading)
These word counts are approximate and you can feel free to go longer if needed.

Key patterns:

Keep SKILL.md under 500 lines; if you're approaching this limit, add an additional layer of hierarchy along with clear pointers about where the model using the skill should go next to follow up.
Reference files clearly from SKILL.md with guidance on when to read them
For large reference files (>300 lines), include a table of contents
Domain organization: When a skill supports multiple domains/frameworks, organize by variant:

cloud-deploy/
├── SKILL.md (workflow + selection)
└── references/
    ├── aws.md
    ├── gcp.md
    └── azure.md
Claude reads only the relevant reference file.

Principle of Lack of Surprise
This goes without saying, but skills must not contain malware, exploit code, or any content that could compromise system security. A skill's contents should not surprise the user in their intent if described. Don't go along with requests to create misleading skills or skills designed to facilitate unauthorized access, data exfiltration, or other malicious activities. Things like a "roleplay as an XYZ" are OK though.

Writing Patterns
Prefer using the imperative form in instructions.

ADK Structural Assembly (Google 5-Patterns) If the diagnosis determined specific ADK patterns apply, weave them into the skill's markdown structure explicitly.

Inversion (First): If required, put this at the very top. e.g., Before taking any action or writing code, you MUST ask the user for X, Y, and Z. Wait for their response.
Pipeline (Middle): Use explicit phases. e.g., Phase 1: Do X. -> Phase 2: Show user and wait for approval. -> Phase 3: Do Y.
Generator (Output): Enforce the structure. e.g., You must use the exact MSL Schema provided below. Do not add conversational filler.
Reviewer (Last): Add a self-audit step at the end. e.g., Phase 4 (Review): Before presenting the final result, read your output and verify it against rule X.
Defining output formats - You can do it like this:

## Report structure
ALWAYS use this exact template:
# [Title]
## Executive summary
## Key findings
## Recommendations
Examples pattern - It's useful to include examples. You can format them like this (but if "Input" and "Output" are in the examples you might want to deviate a little):

## Commit message format
**Example 1:**
Input: Added user authentication with JWT tokens
Output: feat(auth): implement JWT-based authentication
Writing Style
Try to explain to the model why things are important in lieu of heavy-handed musty MUSTs. Use theory of mind and try to make the skill general and not super-narrow to specific examples. Start by writing a draft and then look at it with fresh eyes and improve it.

Test Cases
After writing the skill draft, come up with 2-3 realistic test prompts — the kind of thing a real user would actually say. Share them with the user: [you don't have to use this exact language] "Here are a few test cases I'd like to try. Do these look right, or do you want to add more?" Then run them.

Save test cases to evals/evals.json. Don't write assertions yet — just the prompts. You'll draft assertions in the next step while the runs are in progress.

{
  "skill_name": "example-skill",
  "evals": [
    {
      "id": 1,
      "prompt": "User's task prompt",
      "expected_output": "Description of expected result",
      "files": []
    }
  ]
}
See references/schemas.md for the full schema (including the assertions field, which you'll add later).

## Running and evaluating test cases
This section is one continuous sequence — don't stop partway through. Do NOT use /skill-test or any other testing skill.

Put results in <skill-name>-workspace/ as a sibling to the skill directory. Within the workspace, organize results by iteration (iteration-1/, iteration-2/, etc.) and within that, each test case gets a directory (eval-0/, eval-1/, etc.). Don't create all of this upfront — just create directories as you go.

Step 1: Spawn all runs (with-skill AND baseline) in the same turn
For each test case, spawn two subagents in the same turn — one with the skill, one without. This is important: don't spawn the with-skill runs first and then come back for baselines later. Launch everything at once so it all finishes around the same time.

With-skill run:

Execute this task:
- Skill path: <path-to-skill>
- Task: <eval prompt>
- Input files: <eval files if any, or "none">
- Save outputs to: <workspace>/iteration-<N>/eval-<ID>/with_skill/outputs/
- Outputs to save: <what the user cares about — e.g., "the .docx file", "the final CSV">
Baseline run (same prompt, but the baseline depends on context):

Creating a new skill: no skill at all. Same prompt, no skill path, save to without_skill/outputs/.
Improving an existing skill: the old version. Before editing, snapshot the skill (cp -r <skill-path> <workspace>/skill-snapshot/), then point the baseline subagent at the snapshot. Save to old_skill/outputs/.
Write an eval_metadata.json for each test case (assertions can be empty for now). Give each eval a descriptive name based on what it's testing — not just "eval-0". Use this name for the directory too. If this iteration uses new or modified eval prompts, create these files for each new eval directory — don't assume they carry over from previous iterations.

{
  "eval_id": 0,
  "eval_name": "descriptive-name-here",
  "prompt": "The user's task prompt",
  "assertions": []
}
Step 2: While runs are in progress, draft assertions
Don't just wait for the runs to finish — you can use this time productively. Draft quantitative assertions for each test case and explain them to the user. If assertions already exist in evals/evals.json, review them and explain what they check.

Good assertions are objectively verifiable and have descriptive names — they should read clearly in the benchmark viewer so someone glancing at the results immediately understands what each one checks. Subjective skills (writing style, design quality) are better evaluated qualitatively — don't force assertions onto things that need human judgment.

Update the eval_metadata.json files and evals/evals.json with the assertions once drafted. Also explain to the user what they'll see in the viewer — both the qualitative outputs and the quantitative benchmark.

Step 3: As runs complete, capture timing data
When each subagent task completes, you receive a notification containing total_tokens and duration_ms. Save this data immediately to timing.json in the run directory:

{
  "total_tokens": 84852,
  "duration_ms": 23332,
  "total_duration_seconds": 23.3
}
This is the only opportunity to capture this data — it comes through the task notification and isn't persisted elsewhere. Process each notification as it arrives rather than trying to batch them.

Step 4: Grade, aggregate, and launch the viewer
Once all runs are done:

Grade each run — spawn a grader subagent (or grade inline) that reads agents/grader.md and evaluates each assertion against the outputs. Save results to grading.json in each run directory. The grading.json expectations array must use the fields text, passed, and evidence (not name/met/details or other variants) — the viewer depends on these exact field names. For assertions that can be checked programmatically, write and run a script rather than eyeballing it — scripts are faster, more reliable, and can be reused across iterations.

Aggregate into benchmark — run the aggregation script from the skill-creator directory:

python -m scripts.aggregate_benchmark <workspace>/iteration-N --skill-name <name>
This produces benchmark.json and benchmark.md with pass_rate, time, and tokens for each configuration, with mean ± stddev and the delta. If generating benchmark.json manually, see references/schemas.md for the exact schema the viewer expects. Put each with_skill version before its baseline counterpart.

Do an analyst pass — read the benchmark data and surface patterns the aggregate stats might hide. See agents/analyzer.md (the "Analyzing Benchmark Results" section) for what to look for — things like assertions that always pass regardless of skill (non-discriminating), high-variance evals (possibly flaky), and time/token tradeoffs.

Launch the viewer with both qualitative outputs and quantitative data:

nohup python <skill-creator-path>/eval-viewer/generate_review.py \
  <workspace>/iteration-N \
  --skill-name "my-skill" \
  --benchmark <workspace>/iteration-N/benchmark.json \
  > /dev/null 2>&1 &
VIEWER_PID=$!
For iteration 2+, also pass --previous-workspace <workspace>/iteration-<N-1>.

Cowork / headless environments: If webbrowser.open() is not available or the environment has no display, use --static <output_path> to write a standalone HTML file instead of starting a server. Feedback will be downloaded as a feedback.json file when the user clicks "Submit All Reviews". After download, copy feedback.json into the workspace directory for the next iteration to pick up.

Note: please use generate_review.py to create the viewer; there's no need to write custom HTML.

Tell the user something like: "I've opened the results in your browser. There are two tabs — 'Outputs' lets you click through each test case and leave feedback, 'Benchmark' shows the quantitative comparison. When you're done, come back here and let me know."
What the user sees in the viewer
The "Outputs" tab shows one test case at a time:

Prompt: the task that was given
Output: the files the skill produced, rendered inline where possible
Previous Output (iteration 2+): collapsed section showing last iteration's output
Formal Grades (if grading was run): collapsed section showing assertion pass/fail
Feedback: a textbox that auto-saves as they type
Previous Feedback (iteration 2+): their comments from last time, shown below the textbox
The "Benchmark" tab shows the stats summary: pass rates, timing, and token usage for each configuration, with per-eval breakdowns and analyst observations.

Navigation is via prev/next buttons or arrow keys. When done, they click "Submit All Reviews" which saves all feedback to feedback.json.

Step 5: Read the feedback
When the user tells you they're done, read feedback.json:

{
  "reviews": [
    {"run_id": "eval-0-with_skill", "feedback": "the chart is missing axis labels", "timestamp": "..."},
    {"run_id": "eval-1-with_skill", "feedback": "", "timestamp": "..."},
    {"run_id": "eval-2-with_skill", "feedback": "perfect, love this", "timestamp": "..."}
  ],
  "status": "complete"
}
Empty feedback means the user thought it was fine. Focus your improvements on the test cases where the user had specific complaints.

Kill the viewer server when you're done with it:

kill $VIEWER_PID 2>/dev/null

## Improving the skill
This is the heart of the loop. You've run the test cases, the user has reviewed the results, and now you need to make the skill better based on their feedback.

How to think about improvements
Generalize from the feedback. The big picture thing that's happening here is that we're trying to create skills that can be used a million times (maybe literally, maybe even more who knows) across many different prompts. Here you and the user are iterating on only a few examples over and over again because it helps move faster. The user knows these examples in and out and it's quick for them to assess new outputs. But if the skill you and the user are codeveloping works only for those examples, it's useless. Rather than put in fiddly overfitty changes, or oppressively constrictive MUSTs, if there's some stubborn issue, you might try branching out and using different metaphors, or recommending different patterns of working. It's relatively cheap to try and maybe you'll land on something great.

Keep the prompt lean. Remove things that aren't pulling their weight. Make sure to read the transcripts, not just the final outputs — if it looks like the skill is making the model waste a bunch of time doing things that are unproductive, you can try getting rid of the parts of the skill that are making it do that and seeing what happens.

Explain the why. Try hard to explain the why behind everything you're asking the model to do. Today's LLMs are smart. They have good theory of mind and when given a good harness can go beyond rote instructions and really make things happen. Even if the feedback from the user is terse or frustrated, try to actually understand the task and why the user is writing what they wrote, and what they actually wrote, and then transmit this understanding into the instructions. If you find yourself writing ALWAYS or NEVER in all caps, or using super rigid structures, that's a yellow flag — if possible, reframe and explain the reasoning so that the model understands why the thing you're asking for is important. That's a more humane, powerful, and effective approach.

Look for repeated work across test cases. Read the transcripts from the test runs and notice if the subagents all independently wrote similar helper scripts or took the same multi-step approach to something. If all 3 test cases resulted in the subagent writing a create_docx.py or a build_chart.py, that's a strong signal the skill should bundle that script. Write it once, put it in scripts/, and tell the skill to use it. This saves every future invocation from reinventing the wheel.

This task is pretty important (we are trying to create billions a year in economic value here!) and your thinking time is not the blocker; take your time and really mull things over. I'd suggest writing a draft revision and then looking at it anew and making improvements. Really do your best to get into the head of the user and understand what they want and need.

The iteration loop
After improving the skill:

Apply your improvements to the skill
Rerun all test cases into a new iteration-<N+1>/ directory, including baseline runs. If you're creating a new skill, the baseline is always without_skill (no skill) — that stays the same across iterations. If you're improving an existing skill, use your judgment on what makes sense as the baseline: the original version the user came in with, or the previous iteration.
Launch the reviewer with --previous-workspace pointing at the previous iteration
Wait for the user to review and tell you they're done
Read the new feedback, improve again, repeat
Keep going until:

The user says they're happy
The feedback is all empty (everything looks good)
You're not making meaningful progress

## Advanced: Blind comparison
For situations where you want a more rigorous comparison between two versions of a skill (e.g., the user asks "is the new version actually better?"), there's a blind comparison system. Read agents/comparator.md and agents/analyzer.md for the details. The basic idea is: give two outputs to an independent agent without telling it which is which, and let it judge quality. Then analyze why the winner won.

This is optional, requires subagents, and most users won't need it. The human review loop is usually sufficient.

## Description Optimization
The description field in SKILL.md frontmatter is the primary mechanism that determines whether Claude invokes a skill. After creating or improving a skill, offer to optimize the description for better triggering accuracy.

Step 1: Generate trigger eval queries
Create 20 eval queries — a mix of should-trigger and should-not-trigger. Save as JSON:

[
  {"query": "the user prompt", "should_trigger": true},
  {"query": "another prompt", "should_trigger": false}
]
The queries must be realistic and something a Claude Code or Claude.ai user would actually type. Not abstract requests, but requests that are concrete and specific and have a good amount of detail. For instance, file paths, personal context about the user's job or situation, column names and values, company names, URLs. A little bit of backstory. Some might be in lowercase or contain abbreviations or typos or casual speech. Use a mix of different lengths, and focus on edge cases rather than making them clear-cut (the user will get a chance to sign off on them).

Bad: "Format this data", "Extract text from PDF", "Create a chart"

Good: "ok so my boss just sent me this xlsx file (its in my downloads, called something like 'Q4 sales final FINAL v2.xlsx') and she wants me to add a column that shows the profit margin as a percentage. The revenue is in column C and costs are in column D i think"

For the should-trigger queries (8-10), think about coverage. You want different phrasings of the same intent — some formal, some casual. Include cases where the user doesn't explicitly name the skill or file type but clearly needs it. Throw in some uncommon use cases and cases where this skill competes with another but should win.

For the should-not-trigger queries (8-10), the most valuable ones are the near-misses — queries that share keywords or concepts with the skill but actually need something different. Think adjacent domains, ambiguous phrasing where a naive keyword match would trigger but shouldn't, and cases where the query touches on something the skill does but in a context where another tool is more appropriate.

The key thing to avoid: don't make should-not-trigger queries obviously irrelevant. "Write a fibonacci function" as a negative test for a PDF skill is too easy — it doesn't test anything. The negative cases should be genuinely tricky.

Step 2: Review with user
Present the eval set to the user for review using the HTML template:

Read the template from assets/eval_review.html
Replace the placeholders:
__EVAL_DATA_PLACEHOLDER__ → the JSON array of eval items (no quotes around it — it's a JS variable assignment)
__SKILL_NAME_PLACEHOLDER__ → the skill's name
__SKILL_DESCRIPTION_PLACEHOLDER__ → the skill's current description
Write to a temp file (e.g., /tmp/eval_review_<skill-name>.html) and open it: open /tmp/eval_review_<skill-name>.html
The user can edit queries, toggle should-trigger, add/remove entries, then click "Export Eval Set"
The file downloads to ~/Downloads/eval_set.json — check the Downloads folder for the most recent version in case there are multiple (e.g., eval_set (1).json)
This step matters — bad eval queries lead to bad descriptions.

Step 3: Run the optimization loop
Tell the user: "This will take some time — I'll run the optimization loop in the background and check on it periodically."

Save the eval set to the workspace, then run in the background:

python -m scripts.run_loop \
  --eval-set <path-to-trigger-eval.json> \
  --skill-path <path-to-skill> \
  --model <model-id-powering-this-session> \
  --max-iterations 5 \
  --verbose
Use the model ID from your system prompt (the one powering the current session) so the triggering test matches what the user actually experiences.

While it runs, periodically tail the output to give the user updates on which iteration it's on and what the scores look like.

This handles the full optimization loop automatically. It splits the eval set into 60% train and 40% held-out test, evaluates the current description (running each query 3 times to get a reliable trigger rate), then calls Claude with extended thinking to propose improvements based on what failed. It re-evaluates each new description on both train and test, iterating up to 5 times. When it's done, it opens an HTML report in the browser showing the results per iteration and returns JSON with best_description — selected by test score rather than train score to avoid overfitting.

How skill triggering works
Understanding the triggering mechanism helps design better eval queries. Skills appear in Claude's available_skills list with their name + description, and Claude decides whether to consult a skill based on that description. The important thing to know is that Claude only consults skills for tasks it can't easily handle on its own — simple, one-step queries like "read this PDF" may not trigger a skill even if the description matches perfectly, because Claude can handle them directly with basic tools. Complex, multi-step, or specialized queries reliably trigger skills when the description matches.

This means your eval queries should be substantive enough that Claude would actually benefit from consulting a skill. Simple queries like "read file X" are poor test cases — they won't trigger skills regardless of description quality.

Step 4: Apply the result
Take best_description from the JSON output and update the skill's SKILL.md frontmatter. Show the user before/after and report the scores.

Package and Present (only if present_files tool is available)
Check whether you have access to the present_files tool. If you don't, skip this step. If you do, package the skill and present the .skill file to the user:

python -m scripts.package_skill <path/to/skill-folder>
After packaging, direct the user to the resulting .skill file path so they can install it.

## Skill Optimization and Self-Healing (The .amendify() Loop)
Skills are not static; they must evolve as the codebase, models, and user tasks shift. Use this section when a skill is underperforming or failing repeatedly.

1. Observe & Inspect
Before optimizing, you must gather evidence from the Skill Audit Storage (MEMORY/skill_audit/).

Read the audit logs for the specific Skill_ID.
Identify recurring patterns: Is the trigger too broad? Are steps being skipped? Is the output format drifting? Are there environment-specific failures (e.g., path issues)?
Trace the connected history: Look at past runs, user feedback, and tool errors.
2. Amend Skill (.amendify)
Once you have enough evidence, propose a targeted "Patch" (Amendment) rather than a complete rewrite.

Tighten the trigger: Update the YAML frontmatter triggers or description.
Add missing conditions: Explicitly handle edge cases discovered in the audit.
Reorder or clarify steps: Use imperative form and explain why steps are necessary.
Update output format: Align strictly with the latest user requirements or Schema.
3. Evaluate & Update
Propose the patch to the user with a clear rationale based on the audit evidence.
After approval, apply the change to the SKILL.md.
Mandatory: After an amendment, you MUST run at least 2-3 test cases from the audit logs (the ones that previously failed) to verify the fix.
## Autoresearch 协议子模块 (Quantitative Iterative Optimization)
当触发“运行技能评测”、“优化既有指令”或系统陷入“同质化微调 (Dead Loop)”时，强制挂载此 Autoresearch 物理硬锁协议。摒弃主观定性评价，执行基于二元评估 (Binary Evals) 的靶向突变引擎。

核心准则 (Core Principles)
Binary Evals (二元评估)：摒弃 1-10 分的模糊打分，强制使用绝对的 Yes/No 物理校验作为评分标尺。
Establish Baseline (确立基线)：在未测算当前成功率前，绝对禁止修改任何代码。
Single Mutation (单点突变)：每次迭代仅允许修改一个变量（如增加一条防呆指令或修改一个例子），并进行多轮测试验证效果。
执行 OODA 闭环 (The Execution Loop)
Observe (提取用例与标准):
提取或要求用户提供 3 个异构的测试输入（覆盖不同场景/Edge Cases）。
定义 3-5 个二元校验条件 (Eval Criteria)（如：“是否包含 TCO 测算章节 [Yes/No]”、“是否使用了违禁词 [Yes/No]”）。必须遵循 **Three-Question Test (三问法)** 护城河：
- **一致性**: 两个独立 Agent 评分是否绝对一致？(消除主观模糊判定，如"好看"、"专业")。
- **抗刷分**: Skill 是否可以“玩游规则”走捷径即可通过？(必须针对用户真实痛点设计防线)。
- **相关性**: 用户是否真正关心该指标？(没有实质影响的格式要求应当丢弃)。
Orient (测算基线):
在不修改当前 Skill 的情况下，运行这 3 个测试输入（每组可运行 1-3 次）。
统计基准得分。若基准得分满分，拒绝优化。
Decide (提出突变假设):
**强制遵循 The "ONE Change" Rule (绝对单点突变)。**
基于失败用例，只允许且仅允许进行一次局部的靶向修改（例如：只增加一条具体防呆、只改动一个指令词、只替换一个上下文例子）。绝对禁止大面积重写或多维度的混合修改，以确保因果关系的唯一确定性。每次突变必须有清晰的动机假设（Reasoning）。
Act (突变、复测与资产化):
修改 SKILL.md 并执行复测。计算新得分。
Discard (强制回滚)：若通过率下降或不变，说明该突变增加了系统熵值，强制全盘撤销修改。
Keep (固化与落盘)：若通过率提升，保留修改。
资产化同步 (The Discard Changelog)：知道什么没用，比知道什么有用更重要。
- 无论 Keep 还是 Discard，必须形成标准化的物理 Changelog（结构: `[Change] -> [Reasoning] -> [Result]`）。
- 失败的实验 (Discard) 必须作为“先验失败资产 (Gotchas)”被物理归档并写入 `MEMORY/skill_audit/mutation_log.md`。这构成系统免疫记忆，防止未来 Agent 重蹈覆辙。最后使用 vector-lake/cli.py sync 同步至逻辑湖，形成跨技能的认知复利。

## Reference files
The agents/ directory contains instructions for specialized subagents. Read them when you need to spawn the relevant subagent.

agents/grader.md — How to evaluate assertions against outputs
agents/comparator.md — How to do blind A/B comparison between two outputs
agents/analyzer.md — How to analyze why one version beat another
The references/ directory has additional documentation:

references/schemas.md — JSON structures for evals.json, grading.json, etc.
Repeating one more time the core loop here for emphasis:

Figure out what the skill is about
Draft or edit the skill
Run claude-with-access-to-the-skill on test prompts
With the user, evaluate the outputs:
Create benchmark.json and run eval-viewer/generate_review.py to help the user review them
Run quantitative evals
Repeat until you and the user are satisfied
Package the final skill and return it to the user.
Please add steps to your TodoList, if you have such a thing, to make sure you don't forget. If you're in Cowork, please specifically put "Create evals JSON and run eval-viewer/generate_review.py so human can review test cases" in your TodoList to make sure it happens.

Good luck!
##  Telemetry & Metadata (Mandatory)
- 使用 `write_file` 将本次执行的元数据以 JSON 格式保存至 `{root}\MEMORY\skill_audit\telemetry\record_[TIMESTAMP].json`（请将 [TIMESTAMP] 替换为当前时间戳或随机数）。
- JSON 结构：`{"skill_name": "logic-adversary", "status": "success", "duration_sec": [ESTIMATE], "input_tokens": [ESTIMATE], "output_tokens": [ESTIMATE]}`

## 历史失效先验 (Gotchas)
- [此处预留用于记录重复性失败的禁令，实现系统的对抗性进化]