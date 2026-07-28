# Preprints 管线配置参考 (deepxiv-sdk)

> 本文件为 `deepxiv_preprints_scout.py` 的配置说明。脚本只生成候选论文元数据，不替代全文核验或证据评价。

## 侦察目标
通过 **deepxiv-sdk** `Reader.search()` API 精确检索 ArXiv 预印本。

## 检索参数

| 参数 | 值 | 说明 |
|:---|:---|:---|
| search_mode | `hybrid` | BM25 + Vector 混合检索 |
| categories | `cs.AI, cs.LG, cs.CL, cs.CV, q-bio.QM` | ArXiv 分类过滤 |
| window | `7 天` | 可通过 `--window` 修改；空结果不自动扩大用户指定范围 |
| max_per_query | `15` | 每个 query 拉取上限 |
| top_n_enrich | `30` | brief() 提纯数量上限 |

## 检索关键词

1. `clinical AI large language model`
2. `medical foundation model multimodal`
3. `healthcare reasoning agent workflow`
4. `biomedical knowledge graph LLM`
5. `digital health federated learning`
6. `radiology AI diagnostic imaging`
7. `EHR clinical NLP transformer`

## 可选补充信号

- 只有用户接受扩大候选范围时才使用 `--include-trending`；热门度不是证据强度，也不能替代主题和日期筛选。

## 输出约束
- 禁止输出多余废话。
- 候选记录至少保留 arXiv ID、版本日期、分类和预印本状态。Citations、TLDR、Keywords 等字段仅在接口返回时填写。
- 最终报告必须回到原始摘要页或全文核验，不把脚本自动摘要作为论文证据。
- 输出路径: 用户指定目录或当前任务的输出目录。

## 调用方式
```bash
python assets/deepxiv_preprints_scout.py [--window 7] [--include-trending] [--output PATH]
```
