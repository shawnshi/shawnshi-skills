# _DIR_META.md - Intelligence Hub Scripts

## Vision
提供高性能、多源结构化情报采集与 AI 精炼能力，作为个人"逻辑湖"的原始物料输入端与推演引擎。

## Index
* **fetch_news.py**: Phase 1 多源侦察引擎。支持 100+ RSS/API 源的并发抓取、增量缓存与重试逻辑。
* **calibrate_focus.py**: Phase 0 动态校准引擎。基于 `memory.md` 词频分析动态调整战略关键词权重。
* **refine.py**: Phase 2 AI 精炼引擎。评分排序原始情报，生成结构化提示词供 AI 进行二阶推演。
* **forge.py**: Phase 4 简报锻造引擎。整合 AI 精炼结果，按模板渲染最终战略简报。
* **update_index.py**: Phase 5 归档索引器。自动维护 Markdown 与 JSON 双格式情报总目。

## Maintenance Protocol
* **新增源**: 必须更新 `references/karpathy_feeds.json` 并同步 `SKILL.md` 维护协议。
* **解析逻辑**: 保持 `fetch_news.py` 的 `fetch_with_retry` 模式，禁止引入重型依赖。
* **路径协议**: 全部使用 `pathlib` 相对路径解析，严禁硬编码绝对路径。
