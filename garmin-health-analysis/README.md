# 佳明健康数据分析 (garmin-health-analysis)

专为个体构建数字孪生生理模型，全面提取、处理、查询并将基于 Garmin 生态设备产生的高维健康时间序列数据转化为战略级个人洞见。

## 核心能力

- **私有数据集成**：依托认证与对接能力完整获取历史穿戴及环境生理数据记录，覆盖 20+ 项健康指标。
- **高阶生理分析**：提供流感预测警报 (Garmin Flu)、身心分层执行准备度 (Readiness)、完整生理审计 (Bio-Metric Audit) 和个性化战略干预建议。
- **时间点精确查询**：支持自然语言时间点查询，如"下午3点的心率"、"上午9点的 Body Battery"。
- **活动文件深度分析**：下载 FIT/GPX/TCX 活动文件，按距离/时间查询任意数据点的海拔、配速、心率、功率等。
- **交互式可视化看板**：生成 Bio-Metric Audit 仪表盘，含多维图表与专家审计报告（HTML/Chart.js）。
- **FHIR 标准输出**：支持 HRV、RHR、睡眠、压力等指标的 HL7 FHIR Observation 导出，兼容医疗数据交换标准。

## 使用场景

当用户开始查询"上月睡眠模式变化"、"近期静息心率异常警告"、"我下午 3 点心率多少"、"上次跑步最快配速"，或企划建立自身数字生理仪表盘进行长期动态跟踪时调用。

## 安装

**Unix/macOS:**
```bash
bash install.sh
```

**Windows:**
```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```
