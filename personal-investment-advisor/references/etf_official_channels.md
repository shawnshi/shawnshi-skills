# ETF 官方通道清单（可用性核验，非事实来源）

- 目的：把"ETF 公司行动/净值证据能从哪里取"固化成可复用清单，避免每个标的重新试错；本文件只记录**通道可用性**，其中的时间与哈希是核验当刻的证据，不构成事实结论。
- 核验日期：2026-09-27（Asia/Shanghai）。用户代理约定：SEC 必须使用含真实邮箱的 `User-Agent`（本机默认 `PIA_SEC_USER_AGENT`）；无邮箱 UA 会被 403。
- 使用规则：① 零结果只有在"通道确实覆盖该标的"且附可审计对照查询时才等于"无事件"；② 提供商与交易所/管理人的告警可能同源，匹配只证明提供商一致；③ 不同来源的精度不同（见第 3 节）。

## 1. 可取（本次实测成功）

| 通道 | 入口 | 层级 | 用途 | 核验证据 |
|---|---|---|---|---|
| SEC EDGAR 申报索引 | `https://data.sec.gov/submissions/CIK##########.json` | regulator | 发行人/基金申报清单、申报日 | 44,922 B，sha256 `6b3b41fb…`（CIK 0001067839）；带邮箱 UA 必填 |
| SEC N-CSRS 原件 | `https://www.sec.gov/Archives/edgar/data/<cik>/<accession>/<doc>` | audited_filing | 基金半年度分配/财务摘要（期间口径，非逐次 ex 日） | 939,304 B，sha256 `b34e8cab…`（QQQ N-CSRS 2026-06-01） |
| 交易所分红馈送（Nasdaq） | `https://api.nasdaq.com/api/quote/<symbol>/dividends?assetclass=etf` | exchange | 分配事件：ex/生效日 + 金额（可达 58 条历史） | 9,738 B，sha256 `fc6abbcc…`（QQQ） |
| 管理人官方净值（CN） | 景顺长城 `servlet/json?funcNo=904142&fundid=<code>`；易方达/富国产品页服务端渲染 | official_product_data | 单位净值与净值日期 | 1,186 B `0c01701f…`（159072）；392,802 B `d975db54…`（159934 页） |
| 上金所/上期所官方行情 | `sge.com.cn/graph/Dailyhq?instid=Au99.99`；`shfe.com.cn/data/tradedata/future/dailydata/kx<YYYYMMDD>.dat` | exchange | 黄金/铜价格一手序列 | 97,095 B `ec05f070…`；123,100 B `6c3dc738…` |
| cninfo 交易所披露（股票） | `cninfo.com.cn/new/hisAnnouncement/query` | exchange | A 股发行人公告（含日期与 PDF） | 窗口查询对股票返回 >0 条（如 603259 7 条） |

## 2. 不可用/受限（本次实测失败，记录失败码）

| 通道 | 入口 | 失败表现 | 影响 |
|---|---|---|---|
| Invesco 产品页与 API | `invesco.com/...product-detail?ticker=QQQ`、`api.invesco.com`、`dng-api.invesco.com` | 页面为 265 KB JS 外壳（无数据）；`api.` SSL EOF；`dng-api` 501/400 | 拿不到 QQO 每份净值与分销明细的管理人原件 |
| 上交所基金公告栏目 | `sse.com.cn/disclosure/fund/announcement/` | 27,229 B 页面无可解析条目 | ETF 法定披露不可用 |
| 上交所通用查询 | `query.sse.com.cn/commonQuery.do?sqlId=COMMON_SSE_FUND_FUNDLIST_L` | `success:false / System Error` | 基金列表渠道不可用 |
| 深交所基金公告 API | `szse.cn/api/report/ShowReport/data?...CATALOGID=1803_gonggao` | HTTP 403；另一 CATALOGID 返回 `recordcount=0` | ETF 法定披露不可用 |
| 证监会基金电子披露 eID | `eid.csrc.gov.cn/fund` | 191 B 存根页 | ETF 法定披露不可用 |
| cninfo 对 ETF | 同 cninfo 查询接口，标的为 515650/159934/159072 | 返回 0 条（对照：同查询对股票返回 >0） | **渠道覆盖性未证明**；且重复查询会出现 **165 B 空壳**（`totalRecordNum=0`、`announcements=null`），空壳不是零结果 |
| SEC browse-edgar atom | `sec.gov/cgi-bin/browse-edgar?...type=N-CSR&output=atom` | 403（无邮箱 UA） | 用 `data.sec.gov` + Archives 直达替代 |
| 管理人公告 PDF 直达 | `cdn.efunds.com.cn/owch/data/bulletin/<YYYYMMDD>/<name>.pdf` | 目录按日可枚举但文件名不可枚举；2025-09-16 份额合并公告未定位到托管件 | 159934 份额合并比例目前只有转载件（见第 3 节） |

## 3. 精度与一致性发现（本轮实测）

- **分红**：交易所记录 5 位小数（`$0.75143`），提供商只公布 3 位（`0.751`）。两者若不量化到共同精度会**逐行不匹配**；当前约定为量化到提供商精度（默认 3 位，`--amount-decimals`），原始金额保留在捕获件中。
- **QQQ 分红一致性**：400 天窗口内 5 条事件，日期与量化金额完全一致 → packet 通过，ETF 历史解锁（251 行）。
- **159934 份额合并不一致**：管理人公告比例 **0.948126035**（2025-09-16 公告、2025-09-22 实施）对应因子 `1:1.054712`；提供商（yfinance）公布的拆股因子为 0.948128，对应 `1:1.054710`。二者在第 6 位小数相差 **2.186e-6** → 门禁报 `corporate_action_conflict`，历史继续被抑制。
  - 含义：提供商的拆股/合并因子是**近似值**，不等于管理人公告比例。
  - 待决定（契约问题）：拆股/份额合并类事件是否允许**有据可查的容差**（例如相对 1e-4，理由是提供商发布精度），还是必须与管理人比例逐位一致；若允许容差，必须在门禁与回执中显式记录容差来源。
  - 待补证：取得管理人托管件（`cdn.efunds.com.cn/owch/data/bulletin/20250916/...`）或交易所公告原件作为 `issuer`/`exchange` 层级定位符。

## 3bis. 容差机制（可显式启用，默认关闭）

- **默认**：因子必须逐位相等（`factor_tolerance` 缺省），与历史行为一致。
- **启用方式**：packet 携带 `factor_tolerance`（或 `pia.py etf-packet assemble --factor-tolerance <值> --tolerance-basis relative|absolute --tolerance-justification "…" --tolerance-source <定位符>`），**四项必须齐备**；缺任意一项即失败关闭。
- **比较语义**：`event_type` 与 `effective_date` 必须逐位相等（**永不容差**）；仅因子按声明基准比较（relative = `|a-b| <= tol*max(|a|,|b|)`；absolute = `|a-b| <= tol`）。
- **披露**：命中容差的对写入回执 `event_mismatches.within_tolerance`（逐条列出官方与提供方值）与 `tolerance_used`；未启用时该列表为空。
- **已跑通的实例（159934）**：相对 1e-4，理由“提供方只公布 6 位小数，管理人比例有 9 位”，源为公告转载件；结果 `packet_verified=true`、`tolerance_used=true`、`within_tolerance=[{official: 1:1.054712, provider: 1:1.054710}]`，随后 `yf.py` 绑定成功并取回 **243 行**日线（2025-09-24 → 2026-09-24）。同一 packet 不声明容差时仍为 `corporate_action_conflict`（失败关闭）。
- **不得做的事**：不要为单次通过而把容差调到恰好盖住差异（如 1e-9）；容差必须来自**发布精度**类可陈述理由，并在理由文本中写明。

## 3ter. 零结果对照协议（`coverage-probe`）

- **命令**：`pia.py etf-packet coverage-probe --channel {cninfo,nasdaq} --target <符号> --control <另一符号> --target-class stock|etf --control-class stock|etf --channel-scope "…" --as-of-date … --task-dir …`
- **判据**：
  - `covered_zero_events`：对照与目标**同类**且对照计数 > 0，而目标计数 = 0 —— 此时零才等于“无事件”；
  - `covered_with_events`：目标计数 > 0；
  - `coverage_unproven`：对照计数为 0，或对照与目标**不同类**（弱对照）；
  - `channel_unavailable`：传输失败、响应行不可解析，或（cninfo）**经一次重试后仍是 165 B 空壳**。
- **只有 `covered_*` 才输出可用的 `official_coverage` 块**（含 `control_query_count` 与 `control_query{symbol,channel_scope}`）；其余情形一律不生成，避免用“未证明的零”去装配 packet。
- **空壳识别（本轮新增）**：cninfo 对限流/不可满足请求会返回与真零完全同形的 165 B 响应，因此适配器内置识别与**一次有界重试**，并把 `empty_shell`/`attempts` 写入捕获件与 `query_quality_notes`；**原先“cninfo 不覆盖 ETF”的判断据此修正为“覆盖性未证明”**（同一会话中同一载荷对 601899 直连可返回 19 条，说明是限流而非覆盖缺失）。
- **Nasdaq 逐标的差异（本轮实测）**：QQQ/QQQM/TQQQ/TLT/SMH/IBB 可解析（58/24/24/202/14/46 行）；SPY/IVV/VOO/IWM/XLK/SCHD/AGG/KWEB/VTI/VEA/ARKK 返回 498 B 的 `N/A` 存根 —— 后者被当作**解析失败**而不是零分红。
- **实例**：`--channel nasdaq --target QQQ --control QQQM --target-class etf --control-class etf` → `covered_with_events`（58 / 24，basis `same_instrument_class_control`）；`--channel cninfo --target 601899.SS --control 603259.SS` → `channel_unavailable`（两侧均空壳，附提醒）。

本清单的全部实测结论可由以下命令复现（均在任务目录内，不写技能目录）：

## 4. 复现方式

- `pia.py etf-packet coverage-probe …`（零结果对照协议，见 §3ter）
- `pia.py etf-packet derive-official-events --symbol <sym> --feed-file <nasdaq.json> --as-of-date <date> --task-dir <dir>`
- `pia.py etf-packet assemble --evidence-file <evidence.json> --task-dir <dir>`（门禁在进程内运行，未通过则不发布 packet）
- 原始抓取与哈希：`scratch/pia/<task>/etf-official-channel/probe_manifest.json`
