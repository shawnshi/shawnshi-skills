# Garmin Health Analysis: 生理智能预测引擎

<!-- 
@Input: Garmin Connect Metrics (Sleep/HRV/Stress), User Queries
@Output: Interactive Health Dashboards (HTML), Physiological Risk Alerts
@Pos: [ACE Layer: Perception] | [MSL Segment: Clinical Intelligence]
@Maintenance: Monthly token refresh & FHIR mapping calibration.
@Axioms: Data Before Subjective | Pattern Recognition | Readiness Over Motivation
-->

> **核心内核**：将原始生理体征数据转化为具备“临床可预测性”的决策准备度模型，实现环境智能 (ACI) 的生理感知。

## 0. 本质与边界 (Essence & Boundary)
- **核心定义**: 数字化身 (Digital Twin) 的健康审计器，负责解码身体发出的微弱信号（如 HRV 异动）并将其转化为行动建议。
- **反向定义**: 它不是一个简单的计步器，而是一个基于长期趋势的生理状态预警机。
- **费曼比喻**: 就像是在你身上装了一个“仪表盘”，它能告诉你明早可能会感冒，或者你现在的状态不适合做重大决策。

## 1. 生态位映射 (Ecosystem DNA)
- **MSL 契约**: 负责处理“生理指标”、“睡眠阶段”、“免疫指标”等实体，对齐 FHIR 标准。
- **ACE 角色**: 作为 **Physiological Sensor (生理感知器)**，为系统提供实时的“人机回环”生理状态输入。

## 2. 逻辑机制 (Mechanism)
- [Raw Data Ingest] -> [Trend Modeling] -> [Risk Pattern Recognition] -> [Strategic Dashboarding]

## 3. 策略协议 (Strategic Protocols)
- **准备度优先 (Readiness First)**：决策前必须检查 Executive Readiness 分数，防止在高认知熵值下盲目行动。
- **免疫预警 (Garmin Flu)**：识别 RHR 飙升与 HRV 骤降的耦合模式，强制触发休息协议。
