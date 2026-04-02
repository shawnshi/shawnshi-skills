# Advanced Tooling Reference & Workflow

此文档包含 `personal-health-analysis` 的进阶命令行工具使用方法。在需要时查阅。

*注意：执行以下脚本时，请确保工作目录为 `C:\Users\shich\.gemini\skills\personal-health-analysis\` 或使用绝对路径。*

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

### 5. 自定义大屏输出路径 (Custom Dashboard Output)
```bash
# 手动指定保存路径
python scripts/garmin_chart.py dashboard --days 7 --output C:\Users\shich\.gemini\memory\garmin\tactical_report.html
```

### 6. 临床互操作 (FHIR Export)
```bash
python scripts/garmin_fhir_adapter.py hrv --days 30
```
