# Integration: Research-Analyst Workflow

## 概述
将 research-analyst 与 personal-writing-assistant 协同使用，实现"深度研究 → 洞察写作"的完整工作流。

## 适用场景
- 需要大量背景资料的深度文章
- 数据驱动的行业分析
- 需要引用多源信息的观点文章
- 复杂主题的系统性论述

## 工作流程

### 阶段1：研究收集（使用 research-analyst）
```bash
# 启动研究任务
/research-analyst --topic "医疗AI的监管困境" --depth comprehensive
```

**research-analyst 会产出**：
- 背景资料综述
- 关键数据和统计
- 多源信息汇总
- 利益相关方分析
- 研究发现和洞察

### 阶段2：洞察提炼（过渡阶段）
审阅 research-analyst 的输出，识别：
- 哪些是"不方便说出的真相"
- 哪些数据支撑反常识观点
- 哪些利益博弈值得深挖
- 哪些假设是脆弱的

### 阶段3：文章创作（使用 personal-writing-assistant）
```bash
python assistant.py \
  --topic "医疗AI的监管困境" \
  --mode Deep \
  --role "政策分析师" \
  --style provocative
```

**写作时引用研究成果**：
- 在"Deep Logic Construction"阶段，使用 research-analyst 发现的利益博弈
- 在"Soul Synthesis"阶段，用具体数据支撑论点
- 在【分析师手记】中，引用 research-analyst 识别的研究gap

## 示例：完整工作流

### Step 1: Research
```
输入：/research-analyst --topic "远程医疗的可持续性"

research-analyst 输出：
- 市场数据：Teladoc、Amwell 财报分析
- 政策环境：Medicare 报销政策变化
- 用户调研：患者偏好数据（McKinsey 2023）
- 竞争格局：传统医疗机构的反击策略
```

### Step 2: 洞察提炼
基于研究发现，识别核心矛盾：
- 数据显示：疫情后远程医疗使用率下降37%
- 政策支持：Medicare延长了远程医疗报销
- 矛盾点：政策支持 vs 市场需求下降

**反常识洞察**：
"政府在推动一个市场不想要的东西"

### Step 3: 文章创作
使用 personal-writing-assistant，结构：

**开篇**（反常识观点）：
"政府花钱补贴远程医疗，但患者在用脚投票离开。这不是创新扩散，这是政策幻觉。"

**主体**（用研究数据支撑）：
- 引用 Teladoc 37% 的下降数据
- 引用 McKinsey 患者偏好调研
- 分析：便利性 vs 信任感的博弈

**【分析师手记】**：
"本文大量依赖 research-analyst 收集的2023年数据。如果2024年数据呈现不同趋势（如5G普及改变用户体验），结论需要更新。"

## 协同优势

| 维度 | research-analyst | personal-writing-assistant | 协同效果 |
|------|------------------|---------------------------|----------|
| 信息收集 | ✓✓✓ 系统性OSINT | ✗ 不擅长 | 研究提供弹药 |
| 逻辑推演 | ✓ 多层级推演 | ✓✓✓ 第一性原理 | 研究提供基础，写作提供洞察 |
| 语言表达 | ✓ 专业报告风格 | ✓✓✓ 克制有力 | 研究产出转化为可读文章 |
| 数据支撑 | ✓✓✓ 海量引用 | ✓ 选择性引用 | 研究提供证据库 |

## 文件交接格式

### research-analyst 的输出可以直接作为 personal-writing-assistant 的输入

**建议文件组织**：
```
project/
├── research/
│   ├── findings.md (research-analyst 产出)
│   ├── data.md (关键数据汇总)
│   └── sources.md (信息源清单)
└── article/
    ├── draft.md (personal-writing-assistant 产出)
    └── outline.md (写作大纲)
```

## 最佳实践

### ✅ DO
- 让 research-analyst 先做完整的信息收集
- 在写作前，手动审阅研究发现，提炼洞察
- 在文章中标注数据来源（来自 research-analyst 的哪个部分）
- 在【分析师手记】中承认研究的局限性

### ❌ DON'T
- 直接把 research-analyst 的输出当作文章（风格不对）
- 忽略 research-analyst 发现的反向证据（会导致cherry-picking）
- 过度依赖研究数据而缺乏自己的洞察

## 时间分配建议

对于一篇深度文章（4000+字）：
- **Research阶段**：40-50%时间（使用research-analyst）
- **洞察提炼**：20-30%时间（人工）
- **写作**：20-30%时间（使用personal-writing-assistant）
- **修改**：10%时间

## 未来增强

可能的自动化集成：
- [ ] research-analyst 自动生成"关键洞察"部分供写作参考
- [ ] personal-writing-assistant 自动从 findings.md 提取相关数据
- [ ] 统一的引用管理系统
