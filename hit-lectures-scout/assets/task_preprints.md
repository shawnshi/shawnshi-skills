# Preprints 管线配置参考 (deepxiv-sdk)

> 本文件为 `deepxiv_preprints_scout.py` 的配置说明。实际参数已硬编码于脚本中。
> 修改检索策略时，同步更新脚本中的常量区块。

## 侦察目标
通过 **deepxiv-sdk** `Reader.search()` API 精确检索 ArXiv 预印本。

## 检索参数

| 参数 | 值 | 说明 |
|:---|:---|:---|
| search_mode | `hybrid` | BM25 + Vector 混合检索 |
| categories | `cs.AI, cs.LG, cs.CL, cs.CV, q-bio.QM` | ArXiv 分类过滤 |
| window | `7 天` (弹性扩至 `14 天`) | 滑动窗口，不足 5 篇自动扩展 |
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

## 补充信号
- `Reader.trending(days=7, limit=30)` — 热门论文自动补充

## 输出约束
- 禁止输出多余废话。
- 每篇论文必须包含: arXiv ID (含链接)、Citations、Categories、Published、TLDR、Keywords。
- 输出路径: `~/.gemini/tmp/playgrounds/Response_Preprints.md`

## 调用方式
```bash
python assets/deepxiv_preprints_scout.py [--window 7] [--output PATH]
```