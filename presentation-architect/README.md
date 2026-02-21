# 演示文稿架构师 (presentation-architect) V6.0

顶级战略演示文稿全栈架构师。引入麦肯锡级别的 Ghost Deck 机制、幻灯片六段式解剖学 (Slide Anatomy) 与硬核数字化的视觉信噪比 (SNR) 质量控制。

## 核心能力
- **<Thinking_Canvas> 战略预演**：骨架产出前，强制进行“痛点 / 政策 / 壁垒”三角逻辑推演。
- **判词即王道 (Action Title is King)**：完全摒弃描述性标题，构建具备完整逻辑连贯性的 Ghost Deck 大纲并经用户确认。
- **单页六段式解剖工程 (Slide Anatomy)**：每一页严格恪守 Kicker → Lead-in → Visual Body → Evidence → Trust_Anchor → Bumper 结构。
- **跨界红队审计 (Multi-Agent Audit)**：模拟 *医院信息科主任*、*卫健委/医保局*、*传统 IT 竞对* 视角，或携手 `pricing-strategy` 审计商业模式。
- **极致视觉信噪比**：硬性限制纯文本 Bullet (≤3) 且强制包含对标基线 (Baseline)，不达标禁止组装。
- **4 阶段生命周期**：战略锚定 → 骨架编排 → 单页解剖 → 视觉转化，严守绿区沙箱隔离。

## 使用场景
当负责草拟与提交高级汇报演讲、面向决策层的高阶研报演示，或具备严密逻辑体系并追求视觉极简控制的企业级商业文档时调用。

## 工具链
| 脚本 | 用途 |
|------|------|
| `build-deck.py` | 编排引擎 (Prompts → Images → PPTX/PDF) |
| `generate-prompts.py` | 从 outline.md 生成单页 Prompt |
| `generate-images.py` | AI 驱动的幻灯片图像生成 |
| `merge-to-pptx.ts` | 合并为 PowerPoint |
| `merge-to-pdf.ts` | 合并为 PDF |
