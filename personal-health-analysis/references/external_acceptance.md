# 外部链路验收与信任边界

只在用户要求验证真实 Garmin 链路、GarminDB 同步环境、外部 FHIR 工具或接收端时读取本资料。Mock、dry-run、已有文件、进程启动或历史测试均不能记为真实链路通过。

## 1. 状态口径

- `not_requested`：本次未要求。
- `unavailable`：已要求，但资产、凭据或环境不可用。
- `indeterminate`：执行过，但结果不足以判断。
- `failed`：契约、校验或接收失败。
- `passed`：只有独立信任根已经验证签名，或受控执行器实际运行绑定工具并解析机器结果后才能使用；本技能的调用方自报材料不能产生此状态。

任何 `required=true` 的门禁只要不是 `passed`，外部验收就没有成立。结构 Schema 通过不能替代官方 Validator、Profile/IG、术语或接收端验收；HTTP 2xx 也不能直接解释为临床互操作。`fhir_external_acceptance.py` 没有独立信任根，因此其 `ok` 固定为 `false`。

## 2. 真实 Garmin 读取

显式调用本技能即授权读取请求窗口内全部受支持健康指标，未给窗口时默认最近 7 天；用户指定更窄指标时必须缩小。真实读取前仍须说明使用非官方 Garmin Connect 接口并取得本次联网授权，不得由健康数据默认授权推导登录、刷新令牌、同步、下载轨迹或扩大日期范围。当前选定解释器还必须先通过 `<SKILL_PYTHON> scripts/runtime_preflight.py --mode live`；该预检不授予联网或其他副作用，也不要求使用虚拟目录。

登录会使用上游客户端的移动 SSO 流程，并可能读取账户 Profile/Settings。技能不再用当日健康摘要探测会话。持久令牌写入是独立动作：

```bash
<SKILL_PYTHON> scripts/garmin_auth.py login --email <EMAIL> --allow-network --allow-token-write
```

恢复已有会话时使用令牌的临时副本，避免刷新过程改写持久令牌目录。技能依据显式调用自动提供 `--allow-health-data`，并始终传入请求窗口：

```bash
<SKILL_PYTHON> scripts/garmin_data.py sleep --source live --days 1 --allow-network --allow-health-data
<SKILL_PYTHON> scripts/garmin_data.py hrv --source live --start 2026-08-08 --end 2026-08-08 --allow-network --allow-health-data
```

遇到 429 立即停止，不退避重试，不切换接口。验收记录只保存命令范围、返回状态、响应形状、覆盖日期和缺失状态；除非用户要求，不复制原始健康数值。

## 3. 原始活动文件

用户须指定活动 ID、格式和会话隔离目录，并分别允许联网和下载；健康数据 CLI 标志由技能自动附加，但不替代这两项副作用授权：

```bash
<SKILL_PYTHON> scripts/garmin_activity_files.py download --activity-id <ID> --format fit --output-dir <SESSION_SCRATCH> --allow-network --allow-health-data --allow-download
```

上游 `ORIGINAL` 返回 ZIP；技能只接受恰好一个、路径安全、未加密且大小受限的 `.fit` 成员，并在落盘前校验 FIT 文件头、`.FIT` 标记、声明长度、可选头 CRC 和文件 CRC，再以原子 create-if-absent 方式发布。回执包含文件 SHA-256 与字节数。轨迹文件不得进入普通报告目录或未经许可的外部服务。

## 4. GarminDB 同步环境

同步仍采用短期计划、精确窗口、显式 runner 和双授权。技能可缩小计划校验到进程启动之间的窗口：二次复核计划/配置/runner、`python -I -B`、清理 Python/pip 与 TLS 信任覆盖环境、关闭 stdin、一次性消费授权。私有 CA 不能通过继承环境注入；若确有需要，须另建把 CA 路径、摘要与用途绑定计划的受控流程。

这些控制不能抵御同一 Windows 用户下能够同时修改技能、计划、Python、动态库和 runner 的敌对进程。若验收目标包含该威胁，必须把 runner 放到技能进程之外的信任边界，例如：

- 独立低权限服务账号与只读输入；
- 组织代码签名和受保护证书库；
- WDAC/AppLocker 或等价执行策略；
- 已签名、不可变的容器或虚拟机镜像。

Wheel 清单和 runner SHA-256 是完整性证据，不是发布者签名。基础 Python 标准库、系统 DLL、TLS/SQLite 动态库和操作系统加载器属于外部运行时边界。

## 5. FHIR 分层验收

本地导出仅为 `FHIR_EXPORT_RESEARCH_ONLY`。四道门禁必须分开记录：

1. `r4_structure`：官方 R4 4.0.1 资产和 Validator；只有 JSON Schema 时最多记为 `indeterminate/schema_only`。
2. `profile_ig`：Bundle、Observation、Provenance 各自的 canonical、版本、IG 包及依赖哈希。
3. `terminology`：本地术语资产或另行授权的术语服务器。当前 Observation 为 text-only；若 Profile 要求 coding，必须失败，禁止自动补 LOINC。
4. `receiver`：CapabilityStatement、合成 Bundle 实际投递、OperationOutcome 摘要和接收方证明。2xx 只说明传输接受。

`fhir_external_acceptance.py` 不运行外部工具、不验证签名，也不联系接收端；它只盘点调用方提供的材料，并检查文件与调用方摘要是否一致。证据 JSON 顶层必须包含 `version: 1`、`bundle_sha256` 和四个完整 gate；每个 gate 都要有 `required` 与上述状态。调用方声明 `passed` 时，工具会检查下列字段，字段一致最多得到 `indeterminate`，并标记 `unsigned_caller_evidence_cannot_establish_pass`：

- R4：Validator 路径/版本/SHA-256、`hl7.fhir.r4.core#4.0.1` 包及零 error/fatal 结果；
- Profile/IG：三类资源的 canonical、版本、包路径/SHA-256及零 error/fatal 结果；
- Terminology：当前 text-only 导出不能声明临床术语等价通过；
- Receiver：CapabilityStatement、OperationOutcome 与接收方证明的文件/SHA-256、合成数据实际投递、2xx 和零 `error/fatal` 结果。

这些检查只能发现材料内部不一致；任意字节及其自算摘要、调用方自报零错误或未签名证明都不能关闭门禁。输出中的 `evidence_contract_ok=true` 只表示证据 JSON 契约可解析，`external_acceptance_established` 和 `clinical_interoperability` 固定为 `false`。

接收端测试默认只能发送合成 Bundle。若要发送真实健康数据，用户必须另行明确数据范围、目标接收方和用途；该授权不能由联网授权、FHIR 导出授权或合成测试授权推导。

## 6. 仍需外部提供的材料

- 真实 Garmin 会话或凭据及本次联网授权；
- 受审核 GarminDB runner 和外部执行信任根；
- 官方 Validator/R4 包、Profile/IG 及依赖、术语资产的版本和 SHA-256；
- 接收端沙盒、认证、CapabilityStatement、Bundle 处理语义和接收方证明。

缺少上述材料时，应报告对应门禁 `unavailable` 或 `not_requested`，不能用本地单元测试替代。
