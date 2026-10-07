# A 股发行人/交易所披露通道清单（可用性核验，非事实来源）

- 目的：把「A 股发行人公告从哪里取、零结果怎么才算零」固化成可复用清单，避免每一轮重新试错；本文件只记录**通道可用性与取用规则**，其中的实测值与哈希是核验当刻的证据，不构成事实结论。
- 核验日期：2026-10-01（Asia/Shanghai）。通道会变化，每次使用前必须重新核验，不得把本文件的结论当作当前可用性保证。

## 取用规则（先于任何查询）

1. **零结果必须配对照**：只有在同一通道、同一判据下，一个已知会返回条目的区间或同类标的返回 >0，而目标区间返回 0 时，0 才可以读作「窗口内无新增公告」。无对照的 0 一律记为 `coverage_unproven`。
2. **通道失败 ≠ 无数据**：传输失败、维护页、限流空壳、反爬挑战页都必须记稳定原因码并在报告中披露，不得归一化为「无公告」。
3. **原件优先、摘录件标明来源**：原件字节可得时记录其 `content_sha256`；只能经渲染通道取回正文时，落盘**摘录件**并显式声明「非原件字节、取回通道见检索台账」。
4. **窗口口径**：`published_at` 取平台/交易所给出的发布时间（SSE 用 `ADDDATE`，SZSE 用 `publishTime`），不得填 `retrieved_at`、文件 mtime 或原件重验时间；并逐条标明是否晚于上一轮复核终止时点。
5. **落盘前校验文件类型**：PDF 必须匹配 `%PDF` 魔数；拿到 HTML（含 `acw_sc__v2` 挑战页、维护页、404 外壳）时必须失败关闭并记 `waf_challenge_blocked` 或 `maintenance_page`，**不得把 HTML 存成 `.pdf` 当作原件**。

## 通道状态（2026-10-01 实测）

| 通道 | 入口 | 状态 | 取用要点 |
|---|---|---|---|
| 上交所公告查询 API | `GET http://query.sse.com.cn/security/stock/queryCompanyBulletin.do` | **可用** | 必带 `Referer: http://www.sse.com.cn/disclosure/listedinfo/announcement/`；`securityType` 必填：主板 `0101,120100,020100,020200,120200`、科创板 `020100`；返回 `TITLE`/`SSEDATE`/`ADDDATE`/`URL`。ETF 走该端点返回 0 条 → 对 ETF 属**覆盖未证明**，不得读作无公告 |
| 上交所 PDF 原件 | `static.sse.com.cn/disclosure/listedinfo/announcement/c/new/<date>/<code>_<date>_<id>.pdf` | **直连被拦；纯 Python 绕过路线已证伪** | 直连（含 `--compressed`、浏览器 UA、`--http1.0`、`Referer`）只得到 **3872 B 的 `acw_sc__v2` JS 挑战页（HTML）**；须改用具备 JS 渲染能力的抓取通道取回正文，再按规则 3 落盘摘录件。2026-10-02 一次有界探测：按挑战页给出的 `posList`/`mask` 自算 `acw_sc__v2` 仍返回挑战页（算法/变体不符），**不再尝试本地绕过**——该路线不作为可依赖能力，也不得写进脚本 |
| 深交所公告 API | `POST https://www.szse.cn/api/disc/announcement/annList` | **可用（有条件）** | 必须 `https` + `Content-Type: application/json` + `Referer: https://www.szse.cn/disclosure/listed/notice/index.html`；body `{"seDate":[start,end],"stock":[code],"channelCode":["listedNotice_disc"],"pageSize":N,"pageNum":1}`。改用 `http` 或缺少 JSON 头 → **HTTP 500 维护页（约 2226 B）**，属通道失败。**长跨度窗口陷阱（2026-10-02 实测）**：3 个月级窗口（如 2026-08-01~10-02，pageSize=100）可返回 `200` 但 `data` 为空，而同标的按月切分（09-01~09-30、06-01~08-31）分别返回 11/50 条——即**真公告被读成 0**。因此必须按月切分或窄窗口查询，并对每个 0 结果做同类对照（本次 300502/002487 均因此被纠正） |
| 巨潮资讯网（交易所指定披露平台） | `POST http://www.cninfo.com.cn/new/hisAnnouncement/query` | **本轮不可用** | 8 只 A 股标的的窗口查询全部返回 `totalAnnouncement=0`；用 2026-09-29 曾实际返回公告的同一窗口（2026-09-15~09-29）做对照，仍为 0 → 通道不返回数据。另据 `etf_official_channels.md`：该接口对不可满足请求会返回与真零同形的 165 B 空壳，须内置识别与有界重试 |
| SEC EDGAR（美股发行人） | `GET https://data.sec.gov/submissions/CIK##########.json`；原件 `https://www.sec.gov/Archives/edgar/data/<cik>/<accession>/<doc>` | **可用** | 必须带含用途说明的 User-Agent；Form 4/144 为 XML，可直接解析字段 |
| 基金管理人官网 | 例：富国 `/wbs-file/fund_report/<YYYYMMDD>/<文件>.pdf` | **可用（渲染差异需辨）** | 详情/公告页为 JS 渲染：`curl` 拿到的「您访问的页面不见了」外壳可能只是渲染差异，渲染抓取可返回正常页。报告原件 PDF（中期报告/年报）通常可直接 `curl` 取回并用 `pdftotext` 提取 |
| 管理人产品详情/每日净值入口 | 富国：`https://www.fullgoal.com.cn/fundDetail/<code>/index.html` | **已定位（2026-10-02）** | 服务端渲染 HTML，直接 `curl` 可取（515650 实例 167,087 B）。提取方式：在 SSR HTML 中匹配 `单位净值(YYYY-MM-DD)` 后的第一个 `<strong>` 即单位净值。**净值观测点累积**（历史序列由前端接口加载、无法稳定直取，故改为按日累积）：`python -B scripts/fund_nav_ledger.py --code <code> --manager fullgoal --ledger <workspace>/fund_nav_ledger.jsonl --allow-network`（幂等；(code, nav_date) 去重，离线可用 `--from-file`，失败关闭码 `page_not_found` / `nav_not_rendered`）。仍须遵守：不得用市场价代替 NAV；只记录页面标注的净值日期，不得拿「期末口径」冒充当日口径（页面内 `newestAsset` 等字段可能仍是上期快照） |

## 失败码约定

- `channel_unavailable`：通道存在但本轮整体不返回可用数据（如巨潮本轮）。
- `waf_challenge_blocked`：返回反爬/JS 挑战页（如上交所 PDF 直连）。
- `maintenance_page`：返回维护页（如深交所 http/缺头调用）。
- `coverage_unproven`：目标返回 0 但缺少有效对照，或不覆盖该标的类别（如 ETF 走上交所股票端点）。
- `render_variance`：同一 URL 在不同抓取方式下返回外壳与正常页，须以渲染结果为准并记录方式。
