# 认知审计与日志管理 (auditingdiary)

个人日志的自动化管理与深度认知审计工具，能够收集日常上下文、分析行为模式并输出高瞻远瞩的战略校准建议。

## 核心能力

| 能力 | 说明 |
|---|---|
| **原子日志写入** | 通过 `tempfile` + `os.replace` 安全写入，防止数据丢失 |
| **周期性认知审计** | 周/月/年三级审计体系，含模块化提示词 |
| **量化自我** | 情绪、专注度、标签趋势统计与分析 |
| **日期范围读取** | 按时间段精确提取日志条目 |
| **语义对齐** | 强制标签体系对齐 `references/semantic_layer.md` |
| **记忆同步** | 审计后自动回写战略洞察至 `memory.md` |

## 文件结构

```
auditingdiary/
├── SKILL.md                    # 核心指令与工作流
├── agents/gemini.yaml          # Gemini 适配配置
├── scripts/
│   ├── diary_ops.py            # 日志引擎 (写入/搜索/统计/读取/备份)
│   ├── memory_sync.py          # memory.md 双向同步
│   ├── discovery_engine.py     # 工作产出扫描引擎
│   └── prompt_compiler.py      # 周度提示词编译器
├── prompts/
│   ├── SESSION_ANALYSIS.md     # 会话分析模板
│   ├── WEEKLY.md               # 周度审计入口
│   ├── MONTHLY.md              # 月度审计模板
│   ├── ANNUAL.md               # 年度审计模板
│   └── weekly/PART_I-VI*.md    # 周度审计模块化提示词
└── references/
    ├── config.md               # 配置文件 (路径/偏好/功能开关)
    ├── templates.md            # 日志模板 (标准/扩展/极简)
    ├── semantic_layer.md       # 标签本体定义
    └── work_nodes.md           # 工作目录索引
```

## 常用命令

```bash
# 写入日志
python scripts/diary_ops.py prepend --file "diary" --content_file "tmp/entry.md"

# 按日期范围读取
python scripts/diary_ops.py read --file "diary" --from "2026-02-15" --to "2026-02-21"

# 搜索
python scripts/diary_ops.py search --file "diary" --query "MedicalAI"

# 统计
python scripts/diary_ops.py stats --file "diary"

# 扫描工作产出
python scripts/discovery_engine.py --days 7 --extensions .md .pptx .docx
```

## 技能联动

- `${garmin-health-analysis}`: 健康数据输入（HR、Body Battery、Sleep）
- `${thinker-roundtable}`: 年度审计时联动多维度战略审视

## 使用场景

当用户希望"记录今天的工作流"、"帮我总结这一周的日志"或发起针对个人工作效率与认知盲区的"日度/周度审计"时。
