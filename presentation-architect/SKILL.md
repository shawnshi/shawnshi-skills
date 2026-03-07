---
name: presentation-architect
description: 顶级战略演示文稿全栈架构师 (V9.1 - Narrative-Driven Edition)。专门针对 CTO 汇报、战略布道、方案咨询、范式转移等高价值场景。遵循 Mentat 语义主权协议，交付 100% 可编辑的原生逻辑资产。支持 Win32 编码自动防御。
triggers: ["制作战略级PPT", "生成演示文稿蓝图", "构建决策型汇报", "设计高级咨询级幻灯片", "CTO技术布道", "架构转型汇报"]
---

# SKILL.md: Presentation Architect V9.1 (Narrative-Driven Edition)

## 0. 核心调度约束 (Global State Machine)
> **[全局熔断协议]**：系统必须严格执行 Phase 1 (校准) -> Phase 2 (骨架与风格) -> Phase 3 (叙事蓝图) -> Phase 4 (原生组装)。在跨越任何 Phase 之前，必须在对话输出的最开头以 `[System State: Moving to Phase X]` 进行显式声明。如果检测到跨级跳跃，视为严重违规。


## 1. 核心哲学 (Core Philosophy)
*   **Narrative is Asset (叙事即资产)**：每一页幻灯片都是逻辑链条上的物理节点。
*   **Action Title is King (判词先行)**：标题必须是具备观点的主题句，而非名词。
*   **High Visual SNR (极高信噪比)**：字不如表，表不如图。强迫听众在 3 秒内理解核心。
*   **Semantic Invariance (语义守恒)**：生成的 PPT 原生对象必须与获批的蓝图逻辑 100% 同态。

## 2. 核心工作流 (The Golden Path)

### [⏳] Phase 1: Strategic Calibration (战略校准) **[Mode: PLANNING]**
1. **初始化**：创建 `task.md` 并启动 `task_boundary`。
2. **战略对齐 (First ask_user)**：无论用户初始输入多么详尽，你都【必须强制】调用 `ask_user` 工具，获取并确认以下参数：
   - **场景模型**：(如：咨询项目汇报 - 决策型 / 内部产品发布 - 愿景型)。
   - **核心受众**：(明确具体职能，如：卫宁健康 CEO、某三甲医院院长)。
   - **核心影响力目标**：(定义一句话的终局，如：消除对短期投入的顾虑，达成二期合同签署)。
   - **汇报时长**：(定义汇报的时间及需要的ppt页面数量)。

### [🧠] Phase 2: Style & Ghost Deck (风格指令与骨架) **[Mode: PLANNING]**
1. **生成视觉风格指令**：基于主题定制 `<STYLE_INSTRUCTIONS>` 标签，参照blueprint-template.md中的全局视觉风格蓝图。
2. **构建 Ghost Deck**：设计叙事性标题链条和故事线可视化。
3. **红队审计**：强制激活 `logic-adversary` 对标题链条进行鲁棒性检查。
4. **强制审批 (Approval Gate)**：【必须强制】调用 `ask_user` 提交风格块与标题大纲。未获批前禁止写单页蓝图。

### [💡] Phase 3: Slide-by-Slide Blueprinting (逐页叙事蓝图) **[Mode: EXECUTION]**
**Initialize Workspace (🟢 扫描收集)**: 物理创建项目目录 `{root}\slide-deck\{Topic}_{Date}`，并基于Phase 2确定的大纲，更新`task.md` 。使用 `task_boundary` 工具更新 UI 状态为“🟢 扫描收集”。
**【单步阻塞执行】：** 每次对话轮次仅允许起草 3-5 页蓝图，每完成一个任务后更新任务计划（`plan.md`）。

**审计强制标记位 (Mandatory Markers)**：
#### 封面 (Title Slide)
*   **风格**: 海报式布局 (Poster-style)。
*   **视觉**: 满版出血大图 (Full-bleed) 或 极端简约的几何构图。
*   **文字**: 只有主标题、副标题和品牌标识，严禁任何细碎文字。

#### 封底 (Closing Slide)
*   **风格**: 行动锚点式 (Call to Action)。
*   **视觉**: 与封面遥相呼应，强调核心愿景。
*   **文字**: 一个强有力的金句或一个清晰的下一步行动建议。

#### 内容页 (Content Slide)
每一页蓝图必须【物理包含】以下五个标签，缺失将导致 Phase 4 审计失败：
- **Page [X]: [叙事性主题句]**
- **// NARRATIVE GOAL (叙事目标)**：解释本页如何承上启下。
- **// KEY CONTENT (关键内容)**：
    - Headline: [有观点的主标题]
    - Sub-headline: [补充说明]
    - Body/Data: [关键论据、真实数据点、必须保留的细节]。
- **// VISUAL (视觉画面)**：描述具体图像内容，强调信息图表化。
- **// LAYOUT (布局结构)**：描述物理区域比例（如：左侧 30% 结论 / 右侧 70% 瀑布图）。
- **// Script**：演讲逐字稿与注意事项。

**文件集成**：将Phase 2生成的视觉风格指令、标题大纲与Phase 3生成单页蓝图进行集成，生成MD文件，严禁组装时摘要化。最终生成 `{Topic}_{Date}_final.md`。更新状态至 `🔴 归档冻结`。

**Win32 编码防御**：在 Windows 环境下合并分段文件时，严禁使用 PowerShell 重定向 `>`，必须通过 `.NET` 或 Python 脚本强制指定 UTF-8 (No BOM) 编码写入。

### [📦] Phase 4: Red Team Audit & Native Asset Forging (红队终审与原生锻造) **[Mode: EXECUTION & VERIFICATION]**
1. **语义对抗门 (The Adversary Gate)**：强制调用 `logic-adversary` (Quick 速查模式) 吞吐全体 `{Topic}_{Date}_final.md` 资产。搜寻致命论点单点故障 (SPOF)、I 谄媚、自动化偏见与逻辑滑坡事件。
2. **逻辑微创手术 (Micro-Patching)**：若发现致命缺陷，允许在当前阶段仅针对 `_final.md` 文件执行局部文字与论据的“打补丁”，严禁更改 Phase 2 已定的大纲骨架。保障跨阶段协议不破损。并将修改后的文件以 `{Topic}_{Date}_final_v2.md` 的形式保存在工作目录中。
3. **风险减缓**：生成《风险减缓矩阵》与面对尖锐提问的回击策略（补齐防御装甲），以md格式保存在工作目录中。
4. **物理隔离门 (The Physical Gate)**：调用 `scripts/validator.py` 检查标题长度、文本密度、数据溯源性。
5. **原生渲染 (Native Rendering)**：利用 `python-pptx` 构建原生资产并写入本地。

## 3. 核心约束 (Iron Rules)
*   ❌ **禁止“谢谢聆听”**：末页必须是 Call to Action。
*   ❌ **禁止模糊占位符**：严禁“这里放置图表”，必须写明 X/Y 轴与趋势结论。
*   **细节穿透**：所有细节需完整提及，确保设计师（或渲染引擎）无需访问源素材即可闭环。

---
*SYS_CHECK: V9.1 Narrative Engine Ready. Encoding Guard Enabled.*
