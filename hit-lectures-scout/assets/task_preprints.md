# Preprints 管线配置参考 (deepxiv-sdk)

> 本文件为 `deepxiv_preprints_scout.py` 的配置说明。脚本只生成候选论文元数据，不替代全文核验或证据评价。

## 侦察目标

通过本机已验证的 **deepxiv-sdk 0.3.1** `Reader.search()` API 检索 ArXiv 预印本候选；未验证线上可达性、召回率或检索排序质量。其他 SDK 版本明确报错，不自动安装或升级。

## 检索参数

| 参数 | 值 | 说明 |
| :--- | :--- | :--- |
| source | `arxiv` | SDK retrieve 接口；不传已弃用且被忽略的 search_mode，不承诺 BM25 + Vector |
| use_fine_rerank | SDK 默认 `false` | 分类只作过滤；不承诺服务内部排序机制 |
| categories | `cs.AI, cs.LG, cs.CL, cs.CV, q-bio.QM` | ArXiv 分类过滤 |
| window / dates | 默认 `7` | **行为修正**：含 cutoff 当天共 7 个日历日（不再回退 7 天形成 8 日期）；`--window 1..366` 或成对 `--date-from/--date-to` 历史闭区间，不可混用，总跨度最多 366 日，结束日不得晚于 cutoff |
| cutoff / timezone | 单一当前时刻 / `Asia/Shanghai` | 可传带偏移且非未来 `--cutoff`，统一转换上海时区；未知/非日期粒度 publish_at 单列待核验，不能假冒本期。同日日期不证明早于 cutoff 时刻 |
| query | 默认下列 7 条 | 重复 `--query` 完全覆盖默认；最多 20 条，每条 1..300 字符，不接受空白或控制字符 |
| max_per_query | `15` | 每个 query 拉取上限 |
| max_enrich | `30` | `--max-enrich 0..30` 只限制 brief，不删除未增强候选；按发现顺序，不再按引用量优先；范围外/无合法标识者不调用 brief |
| request_timeout / max_retries | `45 秒 / 2` | `--request-timeout 1..120`；SDK 独有重试，连接/超时最多 3 次 HTTP 尝试，无外层重试。requests timeout 不是单次调用的硬墙钟 deadline |
| budget_seconds | `300` | `--budget-seconds 1..3600`，从输出预检前开始以单调时钟计时，每个 SDK 逻辑调用前准入检查；在途调用不能取消，最后一调用超预算也披露 partial/error；不承诺总墙钟硬上界 |

## 检索关键词

1. `clinical AI large language model`
2. `medical foundation model multimodal`
3. `healthcare reasoning agent workflow`
4. `biomedical knowledge graph LLM`
5. `digital health federated learning`
6. `radiology AI diagnostic imaging`
7. `EHR clinical NLP transformer`

## 可选补充信号

- 仅显式 `--include-trending` 且窗口恰为当前日及前 6 日时调用当前热门；历史或其他窗口记录 skip，不调用不匹配的热门接口。热门独立为补充流，即使 ID 与主题检索相同也不混作主题命中；本地按日期分为范围内补充、范围外、身份/日期待核验。热门度不是证据强度。

## 输出约束

- 禁止输出多余废话。
- 所有本地通过有界批次校验的候选全保留，分别呈现日期合格主题候选、热门补充、待核验和范围外候选；候选不是正式研究。原始带版本 arXiv ID 不截尾合并，另关联 base ID；ID 仅校验格式，不证明真实存在。非法格式隔离为无链接/不增强候选，缺失 ID 为 schema_error。authors/version/version_date 仅 SDK 确实返回合法字段时保留，不从 ID 编造版本日期或作者。
- Citations、TLDR、Keywords 等仅使用接口返回的合法字段；缺失/None 不等于 0。brief 与已有 ID/发布日期/作者/标题/版本/版本日期冲突时保留原记录、标注冲突并停止后续调用，状态 partial。多查询命中保留每条来源；相同 ID 跨查询身份冲突同样披露。
- 每批最多 search 15 / trending 30 行；最多 20 查询，即本地最多 330 候选（默认 105，热门另 30）。已消费文本最多 4000 字符，字符串列表最多 50 项且合并仍受 4000 限制；坏类型/超限批次整体 schema_error，先前批次保留，不把坏批次丢掉后声称穷尽。SDK 自身已物化的 HTTP JSON 大小不由本地归一化硬限制。
- 远端文本统一单行实体转义，不能注入 Markdown 结构/HTML/链接；URL 仅合法 http(s)，禁止认证信息、空白、控制字符及反斜杠，链接分隔字符编码；回执 JSON 转义围栏字符。字段超限报错，不无限物化。
- 最终报告必须回到原始摘要页或全文核验，不把脚本自动摘要作为论文证据。
- 输出路径默认当前目录 `Response_Preprints.md`，可用裸文件名或绝对路径；Reader 前解析绝对路径，拒绝已有目标、缺父目录、非法 Windows 路径、UNC/重解析父目录及 `DHLS-*`/`DigitalHealthLecturesScout` 正式目标。候选只能放任务隔离目录，不能指定自定义正式报告路径绕过门禁，无覆盖模式。
- 文件输出仅 Windows + Python >=3.13 + 已安装 pywin32；其他平台/能力缺失 fail closed，不安装。同父 `mkdtemp` 原生 0700 私有目录，检查 DACL；完整写入/fsync/读回草稿及待发布副本，再用 Windows 原生 no-replace rename，回读内容并校验私有 ACL。不使用共享正式归档器，不把候选私有权限用于正式归档。
- 私有 `.deepxiv-draft-*` 恢复目录保留，终端给出精确路径；写失败只留草稿/暂存，不写半成品目标；rename 后读回失败可能已有完整候选，终端 error 标明失败范围，不自动删除或回滚竞争目标。文件固定警示 CANDIDATE DRAFT ONLY，内嵌检索状态不代表写入成功；只认终端 publication.state=verified 及匹配 SHA-256。父目录仍须由可信本地用户控制；不承诺抵抗同用户/管理员非合作替换或崩溃后持久性。

## 回执与失败语义

stderr 最后一行 JSON 分为 `retrieval` 与 `publication`；文件只内嵌逐对象相同的 retrieval，不预写发布成功。publication.state 为 verified/error/not_attempted，另有目标、私有草稿、哈希和失败范围。retrieval 记录每阶段 planned/attempted/succeeded/failed（未执行数 = planned - attempted）、错误阶段/调用序号/原生异常链/栈位置；counts 为 retrieved（通过批次校验的原始行数）、dedup（按原始版本 ID、在主题/热门流内分别去重）、eligible（日期合格主题候选）、unverified、out_of_range、supplemental、enriched、rendered。eligible 不证明主题相关性/真实身份/正式纳入，所有本地候选数等于 rendered。API 上限外未获取部分不是穷尽覆盖。

下表退出码还要求 publication.state=verified；任何输出失败均退出 1。

| status | 退出码 | 含义/文件 |
| :--- | :--- | :--- |
| success | 0 | 全部适用有界调用及选中 brief 成功，有候选；不代表研究证据完整 |
| empty | 0 | 全部配置检索明确成功且返回真实空列表，写入空候选说明 |
| partial | 3 | 有候选但检索/补充/brief/预算/身份冲突造成缺口，完整保留所有本地候选；不等于 empty |
| error | 1 | 无可保留候选且调用/契约失败，或 SDK/输出失败；不得报告零论文成功 |
| 参数错误 | 2 | argparse 使用错误；Reader 创建前退出，不进行检索 |

- 任何首次浮出的调用或 schema 错误均停止后续远端调用，包括认证、服务连接、超时、限流、trending 和 brief；这是保守停机策略，不换服务、不自动扩大查询、不叠加重试。已有候选可部分保留；搜索成功空列表后再遇失败仍是 error，不是 empty。
- search 只接受 `status=success, total_count=<非负整数>, result=[...]`，不再猜测 `results`；trending 接受 SDK 返回的 `papers/total`，底层还要求 `data` 包装。None、空对象、错误 status、非法 count/list 都不是空检索。brief 必须为含已知元数据字段的非空对象；缺失或非法 brief 作为失败披露，不伪造提纯。
- SDK 0.3.1 会将某些非法原始响应转换为空成功，因此脚本使用仅调用 super 的 `_make_request` 子类校验，在 SDK 归一化之前拦截；这是受版本及签名检查保护的**私有接口依赖**，未知契约 fail closed，没有新 HTTP 实现。
- 诊断仅保留原生异常类型、数值 code（含可安全提取的 HTTP code）与异常链栈帧的文件名/函数/行号。禁止输出异常 message、完整请求 URL、token、locals 或源码行；因此部分自由文本服务原因不可见。SDK/HTTP 指定 logger 仅在本次串行调用期间抑制，并在 finally 恢复原状态，不改变永久日志配置。
- 候选文件不是 DHLS 正式报告或共享归档回执。共享归档 DHLS-03 仍独立阻断，本阶段通过不等于正式自动归档通过。默认最多 7 search + 30 brief = 37 个逻辑调用；max-enrich=0 时仅 7 次，候选仍全部保留；最多 20 search + 1 trending + 30 brief = 51 次，串行，无并发框架。调用量减少仅是本地/mock 证据，不声称网络提速。

## 调用方式

```bash
python -B assets/deepxiv_preprints_scout.py --help
# 在已经存在的任务隔离目录中，仅创建新候选文件：
python -B assets/deepxiv_preprints_scout.py --max-enrich 0 --output candidate.md
python -B assets/deepxiv_preprints_scout.py --date-from 2026-08-01 --date-to 2026-08-07 --query "clinical AI" --query "medical imaging" --budget-seconds 120 --output historical-candidate.md
```
