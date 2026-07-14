# Collaboration Audit Workflow

## 1. Establish scope

Confirm the period, repositories or conversations in scope, available evidence, and whether the request is audit-only. Default to read-only.

## 2. Collect evidence

Use only user-provided data, connected sources the user authorized, and files within the stated workspace. Record the source, time range, missing periods, and collection method. Do not assume a global memory directory exists.

## 3. Normalize

Map raw events to the fields in [SCHEMA.md](SCHEMA.md). Separate observed facts, calculated metrics, user statements, and analyst inference.

## 4. Analyze

Identify recurring friction, rework, waiting, failed handoffs, tool failures, and preventable context loss. Quantify frequency and impact where the evidence supports it. Preserve counterexamples.

## 5. Validate

Check every finding against its evidence. Remove unsupported causal claims. Mark incomplete data and alternative explanations.

## 6. Deliver

Return the requested report in the conversation. Write JSON, Markdown, dashboards, or long-term records only when the user explicitly requests a file or persistence location. Configuration changes and remediation are separate tasks requiring explicit authorization.
