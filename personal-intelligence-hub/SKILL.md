---
name: personal-intelligence-hub
description: 对技术与医疗数字化开展多来源情报扫描、历史去重、原始来源核验、动态领域配比、情景推演和红队审查，并生成带来源的战略简报。用于“今日资讯简报”“昨日资讯简报”“情报扫描”“战略简报”“过去一周动态”“竞争信号”等需要当前外部信息和行动判断的请求；正式日简报按归档合同自动保存。
---

# 战略情报扫描

## 准备

1. 明确主题、地域、时间窗口、受众和决策用途。用户只说“今日资讯简报”时，默认扫描过去 7 日的中国、美国与全球技术及医疗数字化资讯。
2. 读取 `references/strategic_focus.json`、`references/quality_standard.md`、`references/briefing_schema.json` 和 `references/subagent_prompts.json`。生成 Markdown 时再读取 `references/briefing_template.md`。
3. `briefing_schema.json` 是机器合同；权重和比例只是方法参数。用户指定主题或比例时，以用户要求覆盖默认配置。
4. 运行脚本前检查 `requirements.txt` 和当前环境；不要自动安装依赖或修改全局配置。临时文件写入当前任务隔离的 scratch 目录。

## 扫描顺序

1. **先处理基线**：使用 `references/karpathy_feeds.json` 运行 `scripts/fetch_news.py`，读取和筛选基线候选。基线完成前不得启动补充检索。
2. 检查用户授权新闻目录中的历史简报，按 URL、标题指纹和事件语义去重。
3. **再补充检索**：读取 `references/subagent_prompts.json`，根据基线缺口调用：
   - `TechRadar`：通用技术；
   - `HealthcareRadar`：医疗AI与医疗数字化；
   - `Sentinel`：医疗政策、支付、竞对和采购；
   - `Ranger`：两个领域的失败、漏洞、监管和执行摩擦。
4. 补充检索只能填补基线缺口，不得重复已有事件。优先使用监管公告、公司公告、政府或机构网站、论文、标准和项目主页；新闻与评论只作线索或补充。
5. 记录事件日期、发布日期、抓取时间和直接链接。当前信息必须联网核验；不能访问的来源写入覆盖缺口，不得视为已核验。
6. 合并重复报道，区分事实、来源主张、分析推断、行动建议和未知项。对高影响结论执行反证检查。

## 领域分类与配比

1. 每条候选只能有一个 `primary_domain`：
   - `technology`：基础模型、推理、多模态、智能体、开源、算力、芯片、数据基础设施、软件工程、开发者工具、网络安全和软件供应链；
   - `healthcare_digital`：医疗AI、EHR/HIS、FHIR/HL7、临床工作流、医保支付、医疗器械证据、医院运营、采购、合规和医疗IT竞对。
2. 混合事件可填写 `secondary_domains`，但只按 `primary_domain` 计数。
3. 先执行证据质量门槛，再按领域配额选择；不得用弱资讯补足比例。
4. 默认比例为技术 40%、医疗数字化 60%。条目数不足 10 时使用最大余数法，例如 7 条为 3:4、5 条为 2:3、3 条为 1:2。
5. 只有经过红队审查的 L4，或同时具备高可信 L3、原始来源和近期决策影响的资讯，才允许触发当日比例调整。单日最多调整 20 个百分点；两个领域同时出现高影响资讯时维持默认比例。
6. 某领域合格候选不足时允许另一领域补位，但必须填写 `mix.supply_exception`，披露目标比例、实际比例和缺口原因。

## 生成与校验

1. 按“结论—证据—影响—行动—未知项”组织简报。行动项写明负责人类型、触发条件和观察指标。
2. 结构化管线依次使用：
   - `python scripts/fetch_news.py --window-days <N> --focus-config <PATH>`
   - `python scripts/refine.py --focus-config <PATH> [--min-score <N>] [--max-items <N>]`
   - `python scripts/validate_refined_json.py <input.json>`
   - 独立语义评估和逻辑红队；
   - `python scripts/forge.py`
   - `python scripts/briefing_gate.py <briefing.json>`
3. 脚本参数不确定时查看帮助或源文件，不猜测命令。
4. 最终报告分成“技术”和“医疗数字化”两栏，显示默认比例、有效比例、实际条数、调整理由和候选缺口。
5. Schema、类型、日期、枚举、重复 URL、领域计数、比例计算、未说明的偏离、占位符和未审计 L4 属于硬错误。硬错误未清零不得归档或宣称完成。
6. 不凑 Top 10；没有足够证据时允许少于 10 条或为空。

## 自动归档合同

1. “今日资讯简报”“昨日资讯简报”等正式日简报默认自动保存，不再询问是否归档。用户明确要求不保存时除外。
2. 保存目录优先级：用户本次指定目录 > `PIH_NEWS_DIR` > 由 `hub_utils.NEWS_DIR` 解析的默认新闻归档目录。
3. 文件名为 `intelligence_YYYYMMDD_briefing.md`，并保存同名 JSON 快照。同日重跑采用原子替换。
4. 只有质量门通过后才能写入正式文件。保存后重新读取 JSON，核对 UTF-8、Schema、历史重复、领域计数、比例和文件路径。
5. 返回 Markdown/JSON 绝对路径、保留条数、实际比例、链接核验结果和覆盖缺口。写入失败时不得宣称已归档。

## 输出边界

- 自动归档只授权正式新闻简报，不授权写入长期记忆、知识图谱、索引或外部系统。
- 不自动发布、发邮件或修改外部数据。
- 不输出隐藏推理过程，只交付证据、判断、反证、验证结果和未知项。
