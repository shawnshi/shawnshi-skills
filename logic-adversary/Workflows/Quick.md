# Quick Workflow (速查流程)

Fast single-round perspective check. Use for sanity checks and quick feedback.
快速单轮视角检查。用于直觉验证与快速反馈。

## Voice Notification

```bash
curl -s -X POST http://localhost:8888/notify \
  -H "Content-Type: application/json" \
  -d '{"message": "Running the Quick workflow in the Council skill to get fast perspectives"}' \
  > /dev/null 2>&1 &
```

Running the **Quick** workflow in the **Council** skill to get fast perspectives...

## Prerequisites

- Topic or question to evaluate
- Optional: Custom council members

## Execution

### Step 1: Announce Quick Council (宣布快速会议)

```markdown
## Quick Council: [Topic]

**Council Members:** [List agents]
**Mode:** Single round (fast perspectives)
```

### Step 2: Parallel Perspective Gathering (并行收集视角)

Launch all council members in parallel (single Task call batch).

**Each agent prompt:**
```
You are [Agent Name], [brief role description].

QUICK COUNCIL CHECK

Topic: [The topic]

Give your immediate take from your specialized perspective:
- Key concern, insight, or recommendation
- 30-50 words max
- Be direct and specific

This is a quick sanity check, not a full debate.
```

### Step 3: Output Perspectives (输出各方视角)

```markdown
### Perspectives

**🏛️ Architect (Serena):**
[Brief take]

**🎨 Designer (Aditi):**
[Brief take]

**⚙️ Engineer (Marcus):**
[Brief take]

**🔍 Researcher (Ava):**
[Brief take]

### Quick Summary

**Consensus:** [Do they generally agree? On what?]
**Concerns:** [Any red flags raised?]
**Recommendation:** [Proceed / Reconsider / Need full debate]
```

## When to Escalate (何时升级)

If the quick check reveals significant disagreement or complex trade-offs, recommend:

```
⚠️ This topic has enough complexity for a full council debate.
Run: "Council: [topic]" for 3-round structured discussion.
```

## Timing

- Total: 10-20 seconds

## Done

Quick perspectives gathered. Use for fast validation; escalate to DEBATE for complex decisions.
