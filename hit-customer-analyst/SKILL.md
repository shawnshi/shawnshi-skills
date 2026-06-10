---
name: hit-customer-analyst
description: 医疗大客户拜访分析专家 (V8.0 Dehydrated)。当提及具体医院、卫健委、疾控局，或要求“拜访准备”、“销售策略”、“尽调客户”时激活。
---

# 医疗大客户拜访分析专家 (V8.0: Antigravity Account Intelligence System)

> **Vision**: 本技能的繁重流程控制流、四维子代理派发与门控审计已被全面下沉至底层的 `BasePipelineOrchestrator`。大模型仅需专注核心战略推演与最终的交付。

## 0. 核心约束 (Core Mandates)
- **强制意图驱动 (Target_Intent)**: 必须要求用户输入拜访的核心功利目的。
- **100% 完整溯源**: 所有事实必须附带完整、可点击的绝对 URL。

## 1. 模式与视角 (Operating Modes)
- **vendor_mode**: `winmed | neutral | custom` (默认 `winmed`)

## 2. Workflow

1. **一键触发核心管线 (Launch Orchestrator)**: 
   你不再需要手动拉起 4 个 Subagent 去并发搜集机构全景、关键人等情报！请获取用户的 `[Target_Intent]` 和 `[vendor_mode]` 后，直接调用工具执行管线调度器：
   ```powershell
   $env:PYTHONIOENCODING="utf-8"; python "C:/Users/shich/.gemini/config/skills/hit-customer-analyst/scripts/run_customer_analyst.py" "目标客户意图" "winmed"
   ```

2. **纯粹的高维推演与修复 (Pure Reasoning & Fix)**: 
   Python 脚本会在后台静默完成：4 维度情报抓取、厂商核心系统双重验证、信息缺口排查，并生成套用好模板的战略草稿存储在 `C:/Users/shich/.gemini/tmp/draft_hit_customer.md`。脚本也会自动调用 `brief_gate.py` 进行质量审计。
   - **如果审计通过**：读取草稿，进行最后的高管视角润色，使用 `write_file` 落盘至最终目录 `MEMORY/raw/medical-solution/briefs/YYYYMMDD_[客户名]_CSO_Brief.md`。
   - **如果审计失败**：仔细阅读 Orchestrator 输出的报错日志，修正草稿。

3. **全自动静默入湖 (Silent Ingestion)**: 
   你不再需要操心知识图谱的同步！若你在润色过程中使用了 `[[ ]]` 提取客户实体，底层的 Watchdog 守护进程会自动扫描并异步向量化。严禁手动调用入湖 MCP 工具！
