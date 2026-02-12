# skill-creator
<!-- Input: Skill names, resource specs, GEB-Flow manifests. -->
<!-- Output: Standardized skill directories, _DIR_META.md, compliant scripts. -->
<!-- Pos: Meta-Tool/Evolution Layer (The Guardian). -->
<!-- Maintenance Protocol: Update 'scripts/quick_validate.py' with new architectural standards. -->

## 核心功能
Gemini 技能进化的核心协议。作为 GEB-Flow 体系的守护者，确保所有新技能具备“分形自描述”与“渐进式披露”的高级架构标准。

## 战略契约
1. **分形完整性**: 任何由本技能创建的模块必须包含 `_DIR_META.md`，且所有脚本必须挂载 Standard Header。
2. **自检机制**: 技能在上线前必须通过 `quick_validate.py` 的合规性扫描。
3. **同步语义**: 严禁文档与逻辑脱节，任何底层逻辑变更必须强制回溯更新 `SKILL.md` 的指令清单。
