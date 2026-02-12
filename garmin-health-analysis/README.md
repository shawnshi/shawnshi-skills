# garmin-health-analysis
<!-- Input: Garmin Connect credentials, natural language queries. -->
<!-- Output: Interactive HTML dashboards, FHIR Observations, readiness scores. -->
<!-- Pos: Cognitive/Health Layer (Patient Anchor). -->
<!-- Maintenance Protocol: Update 'garmin_auth.py' upon OAuth2 flow changes. -->

## 核心功能
将 Garmin 院外体征数据转化为临床级的生理智能分析。支持“Garmin 感冒”模式探测与高阶执行决策准备度评估。

## 战略契约
1. **数据伦理**: 严禁存储明文凭证，必须通过 Token 化 Session 进行交互。
2. **临床互操作**: 支持将 HRV/RHR 等核心指标导出为 FHIR 标准格式，为数字健康中台提供数据锚点。
3. **主动预防**: 当生理指标出现显著偏离（如 RHR 飙升）时，必须触发预警诊断流程。
