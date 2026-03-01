# Integration: Planning-with-Files for Long-Form Content

## 概述
使用 planning-with-files 管理复杂的长篇写作项目（5000+字，多角度分析）。

## 适用场景
- 需要多轮研究和写作的复杂主题
- 多个子主题需要分别深入
- 长篇系列文章
- 需要跟踪进度和迭代的项目

## Manus-Style 工作流

### 文件结构
```
project/
├── task_plan.md       # 总体计划和任务分解
├── findings.md        # 研究积累
├── progress.md        # 进度追踪
├── drafts/
│   ├── section1.md   # 分段草稿
│   ├── section2.md
│   └── section3.md
└── final.md          # 最终整合
```

## 阶段化工作流

### Phase 1: 规划（使用 planning-with-files）

**创建 task_plan.md**：
```markdown
# 写作计划：医疗AI的多维困境

## 目标
一篇7000字的深度分析，覆盖技术、伦理、监管、经济四个维度

## 任务分解
1. [ ] 研究技术现状（2天）
2. [ ] 研究伦理争议（1天）
3. [ ] 研究监管政策（2天）
4. [ ] 研究经济模型（1天）
5. [ ] 撰写技术部分（1天）
6. [ ] 撰写伦理部分（1天）
7. [ ] 撰写监管部分（1天）
8. [ ] 撰写经济部分（1天）
9. [ ] 整合润色（1天）

## 里程碑
- 研究完成：Day 6
- 初稿完成：Day 10
- 终稿完成：Day 11
```

### Phase 2: 研究积累（使用 findings.md）

```markdown
# 研究发现

## 技术维度
### 关键数据
- Nature Medicine 2023: AI影像诊断准确率95% vs 人类88%
- 但罕见病场景：AI 72% vs 专科医生89%

### 洞察
AI在标准化任务上超越人类，但在long-tail场景下降

## 伦理维度
### 关键冲突
责任归属：当AI误诊，谁负责？
- 医生说：我只是参考AI
- AI厂商说：我们只提供建议
- 患者：那谁负责？

[继续积累...]
```

### Phase 3: 分段创作（使用 personal-writing-assistant）

**每个维度单独创作**：

```bash
# 技术部分
python assistant.py \
  --topic "医疗AI的技术能力与边界" \
  --mode Deep \
  --template industry-analysis \
  > drafts/section1_tech.md

# 伦理部分
python assistant.py \
  --topic "医疗AI的责任归属困境" \
  --mode Deep \
  --style provocative \
  > drafts/section2_ethics.md

# ... 其他部分类似
```

### Phase 4: 进度追踪（使用 progress.md）

```markdown
# 写作进度

## 已完成
- [x] 技术部分草稿（2500字）
- [x] 伦理部分草稿（2000字）

## 进行中
- [ ] 监管部分（50%，预计明天完成）

## 待办
- [ ] 经济部分
- [ ] 整合润色

## 问题和阻塞
- 监管部分缺少欧盟的最新数据，需要补充研究
- 伦理部分和监管部分有重叠，需要重新梳理边界
```

### Phase 5: 整合（人工 + personal-writing-assistant）

**人工整合**：
- 合并各部分
- 消除重复
- 统一tone和风格
- 添加过渡段落

**personal-writing-assistant 辅助**：
```bash
# 生成统一的开篇和结尾
python assistant.py \
  --topic "医疗AI：一个系统性困境的全景分析" \
  --mode Summary \
  --template thought-leadership \
  > intro_conclusion.md
```

## 优势

| 维度 | 传统一次性写作 | Planning-with-Files + PWA |
|------|--------------|---------------------------|
| 复杂度管理 | ✗ 容易混乱 | ✓✓✓ 清晰分解 |
| 进度可见性 | ✗ 不透明 | ✓✓✓ 实时追踪 |
| 迭代灵活性 | ✗ 大改困难 | ✓✓✓ 分段调整 |
| 质量控制 | ✗ 整体检查困难 | ✓✓✓ 分段质控 |

## 最佳实践

### ✅ DO
- 先完成完整的 task_plan.md 再开始写作
- 在 findings.md 中持续积累研究，即使暂时用不上
- 每完成一个section，更新 progress.md
- 保留所有草稿版本（用git或手动备份）

### ❌ DON'T
- 跳过规划阶段直接写作（长篇项目会失控）
- findings.md 混入个人观点（应该只记录事实和数据）
- 忽略 progress.md（失去进度可见性）

## 示例：7天完成7000字深度文章

**Day 1-3**: 研究阶段
- 使用 research-analyst 收集信息
- 持续更新 findings.md
- 每天end of day更新 progress.md

**Day 4-6**: 分段写作
- 每天使用 personal-writing-assistant 完成1-2个section
- 每个section 1500-2000字
- 完成后立即自查 CHECKLIST.md

**Day 7**: 整合润色
- 人工整合各section
- 使用 humanizer-zh-pro 润色
- 最终质控

## 工具组合

完整工作流的技能组合：
1. **planning-with-files**: 项目管理
2. **research-analyst**: 信息收集
3. **personal-writing-assistant**: 内容创作
4. **humanizer-zh-pro**: 最终润色

## 未来增强

可能的自动化：
- [ ] 自动从 task_plan.md 生成写作任务列表
- [ ] 自动从 findings.md 提取相关数据到各section
- [ ] 自动检测各section的风格一致性
- [ ] 自动生成 progress 报告
