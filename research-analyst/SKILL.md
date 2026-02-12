---
name: research-analyst
description: 执行万字级战略研究的专家 system。支持假设驱动、独立红队审计与实证级逻辑加固。
---

# Research Analyst (V7.4: Empirical Resilience)

工业级深度研究流水线。强调在红队审计后通过联网检索执行“实证加固”，并确保交付产物的“实质守恒”。

## Core Philosophy
*   **Infrastructure First**: 严禁“无头”项目。必须先初始化物理目录与 `working_memory.json`。
*   **Sequential Forging**: 生产序列：[分章初稿] -> [红队审计] -> [实证加固(OSINT)] -> [总结撰写] -> [无损组装]。
*   **Empirical Solidification (实证加固)**: 红队建议后，必须根据需要执行联网搜索，引入真实案例或反向数据来对冲脆弱点。

## Execution Protocol

### Phase 0: Initiation & Architecture (MANDATORY)
1.  **Alignment**: 构建假设矩阵，确认研究深度、目标受众、核心问题。
研究深度：{ label: "标准报告", description: "3000字" }, { label: "深度报告", description: "6000字+" },
报告对象, question: "目标受众？" 
核心问题，question: "核心痛点？" 
2.  **Initialize**: 物理创建项目目录 `research_{Topic}_{Date}` 及其子目录 `chapters/`，生成 `_DIR_META.md` 及 `working_memory.json`。
3.  **Fact Sheet Initialization**: 在 OSINT 结束后，**必须**提炼“核心技术锚点” (Technical Anchors) 存入 `working_memory.json`。

### Phase 1: Distributed Forging (Depth Focus)
1.  **Approval (STOP)**: 展示大纲并获得批准。
2.  **Chapter Drafting**: 每一章存入独立文件（800-1200 字），含技术细节与 So What 洞见。

### Phase 2: Lossless Assembly (Verbatim Integration)
1.  **Verbatim Concatenation**: 逐章完整读取并集成，严禁组装时摘要化。
2.  **De-molding**: 剔除 HTML 锚点与技术噪音，确保 **UTF-8 (无 BOM)** 编码。
3.  **Quantity Check**: 核查文件大小，确保篇幅符合万字级标准。

### Phase 3: Adversarial Audit & Empirical Solidification
1.  **Independent Audit**: 切换至红队模式，输出独立文件 **`adversarial_audit_report.md`**。
2.  **Adversarial OSINT (NEW)**: 
    *   针对红队识别的“脆弱点”或“事实争议”，主动执行 `google_web_search`。
    *   搜寻反向证据、行业最新判例、或缺失的工程参数。
3.  **Physical Revision**: 将搜集到的实证数据物理写入 `chapters/` 原始文件，执行逻辑加固。
4.  **Closing (Chapter 7)**: 在完成实证加固后，撰写结论与路线图。
5  **Final Review (STOP)**: 确认验收。
6.  **Strategic Genome Mutation**: 执行 `scripts/sync_macro.py` 同步记忆。



## Resources
*   **Tools**: `google_web_search` (用于 Phase 2 加固), `scripts/assembler.py` (若可用)。

## Troubleshooting
*   **Vague Defense**: 若逻辑加固阶段仅是文字重组而无新事实引入，触发“强制搜索”命令。
*   **Substance Leak**: 若最终报告篇幅不足，回溯 Phase 3 执行无损组装。
