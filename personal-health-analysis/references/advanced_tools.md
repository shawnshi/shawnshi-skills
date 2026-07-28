# Advanced Tooling Reference & Workflow

此文档包含 `personal-health-analysis` 的进阶命令行工具使用方法。在需要时查阅。

*注意：从技能目录执行以下相对路径脚本，或向脚本传入明确的输入和输出路径。*

### 1. 长程纪律与趋势追踪 (Long-term / Heatmaps)
```bash
python scripts/garmin_intelligence.py insight_cn --period 30d
python scripts/garmin_intelligence.py audit --period YTD
```

### 2. 扩展指标 (Extended Metrics)
```bash
python scripts/garmin_data_extended.py training_readiness --date 2026-02-21
python scripts/garmin_data_extended.py spo2 --date 2026-02-21
python scripts/garmin_data_extended.py respiration --date 2026-02-21
python scripts/garmin_data_extended.py max_metrics --date 2026-02-21
```

### 3. 时间点精确查询 (Point-in-Time Query)
```bash
python scripts/garmin_query.py heart_rate "3:00 PM" --date 2026-02-21
python scripts/garmin_query.py stress "15:00" --date 2026-02-21
```

### 4. 活动文件分析 (Activity File Analysis)
```bash
python scripts/garmin_activity_files.py download --activity-id 12345678 --format fit
python scripts/garmin_activity_files.py query --file ... --distance 5000
python scripts/garmin_activity_files.py analyze --file ...
```

### 5. 报告与大屏输出路径 (Report and Dashboard Output)
```bash
# 分配同一批次的 Markdown 与 HTML 路径；默认目录为
# 当前工作区的 output/personal-health-analysis
python scripts/report_output.py --days 7

# 将分配结果中的 html 路径传给大屏生成器
python scripts/garmin_chart.py dashboard --days 7 --output <html-path>

# 仅需 HTML 时可直接运行；仍会写入默认 Garmin 报告目录
python scripts/garmin_chart.py dashboard --days 7
```

使用 `GARMIN_REPORT_DIR` 可覆盖报告目录。不要把临时 JSON、FIT/GPX、数据库副本或认证令牌写入该目录。

### 6. 临床互操作 (FHIR Export)
```bash
python scripts/garmin_fhir_adapter.py hrv --days 30
```
