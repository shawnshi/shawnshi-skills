# _DIR_META.md - AI Daily Digest Scripts

## Vision
提供高性能、结构化的技术博客数据抓取能力，作为个人“逻辑编译器”的原始物料输入端。

## Index
* **digest.ts**: 核心 RSS 抓取器。负责 90+ 源的并发获取、时间过滤及 JSON 序列化。支持 `--raw` 模式对接 Agent 内置推理流。

## Maintenance Protocol
* **新增源**: 必须经过 Karpathy 级别审核或具同等技术深度。
* **解析逻辑**: 优先保持 Bun 原生 fetch 性能，禁止引入重型 XML 解析库。
