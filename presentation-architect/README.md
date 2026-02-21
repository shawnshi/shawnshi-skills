# 演示文稿架构师 (presentation-architect) V5.0

顶级战略演示文稿全栈架构师。引入麦肯锡级别的 Ghost Deck 生成机制、幻灯片解剖学 (Slide Anatomy) 与极简视觉信噪比 (SNR) 质量控制。

## 核心能力
- **判词即王道 (Action Title is King)**：完全摒弃描述性标题，构建具备完整逻辑连贯性的 Ghost Deck 大纲并经用户确认。
- **单页解剖工程 (Slide Anatomy)**：每一页严格恪守 Kicker → Lead-in → Visual Body → Evidence → Bumper 五段式结构。
- **三角红队审计 (Triple Adversary Audit)**：模拟 *医院信息科主任* (系统耦合/运维成本)、*卫健委/医保局* (DRG/DIP 合规)、*传统 IT 竞对* (壁垒穿透) 三角审计。
- **极致视觉信噪比**：限定 SNR ≥ 0.7，图表代码直译映射为 Mermaid / Image Prompt。
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
