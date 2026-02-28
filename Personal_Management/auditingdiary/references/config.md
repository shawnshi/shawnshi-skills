# DiaryAudit Configuration

此配置文件用于自定义 DiaryAudit 技能的各项设置。

---

## 📁 File Paths

### Diary Directory
**路径:** `privacy/`
**说明:** 日志文件存储的根目录（相对于工作区根目录）

### Diary Filename Pattern
**模式:** `{YYYY}Diary.md`
**说明:** 日志文件命名规则，`{YYYY}` 会被替换为实际年份
**示例:** `2026Diary.md`, `2027Diary.md`

### Calendar Script Path
**路径:** `skills/DiaryAudit/scripts/get_calendar_events.py`
**说明:** 日历事件获取脚本的完整路径（可选）

### Backup Directory
**路径:** `privacy/backups/`
**说明:** 备份文件存储目录

---

## 👤 Personal Settings

### Name
**值:** `师成`
**说明:** 用于审计报告标题中显示的姓名
**示例:** `张三` 或 `Zhang San`

### Timezone
**值:** `Asia/Shanghai`
**说明:** 时区设置，用于日期时间计算
**可选值:**
- `Asia/Shanghai` (中国标准时间)
- `America/New_York` (美国东部时间)
- `Europe/London` (英国时间)
- `Asia/Tokyo` (日本时间)

### Week Start Day
**值:** `Monday`
**说明:** 一周的起始日
**可选值:** `Monday` 或 `Sunday`

### Language
**值:** `zh-CN`
**说明:** 界面和报告语言
**可选值:** `zh-CN` (简体中文), `en-US` (英语)

---

## ⚙️ Feature Flags

### Enable Calendar Integration
**值:** `false`
**说明:** 是否启用日历集成功能
**效果:**
- `true`: 执行 `get_calendar_events.py` 获取日程
- `false`: 使用手动输入或占位符

### Auto Backup
**值:** `false`
**说明:** 是否在每次写入前自动创建备份
**建议:** 如果日志非常重要，建议设置为 `true`

### Export Enabled
**值:** `true`
**说明:** 是否启用导出功能

### Search Enabled
**值:** `true`
**说明:** 是否启用搜索功能

### Statistics Enabled
**值:** `true`
**说明:** 是否启用统计分析功能

---

## 📝 Custom Daily Log Sections

可以自定义日志模板的章节。每行一个章节名称。

**默认章节:**
```
今日工作
主要产出
认知结晶
熵增对抗
能量管理
明日战术锁定
标签
```

**可选章节（按需添加）:**
```
健康记录
人际互动
学习笔记
灵感收集
感恩时刻
```

**说明:** 修改此列表后，更新 `TEMPLATES.md` 中的模板以匹配。

---

## 🎨 UI Preferences

### Use Emoji
**值:** `true`
**说明:** 在日志和报告中使用表情符号
**效果:**
- `true`: 使用 📅 ✅ 💡 等图标
- `false`: 纯文本标题

### Date Format
**值:** `YYYY-MM-DD`
**说明:** 日期显示格式
**可选值:**
- `YYYY-MM-DD` (2026-01-29)
- `DD/MM/YYYY` (29/01/2026)
- `MM/DD/YYYY` (01/29/2026)

---

## 🔔 Reminder Settings

### Weekly Audit Reminder
**值:** `Sunday 20:00`
**说明:** 周度审计提醒时间

### Monthly Audit Reminder
**值:** `Last day of month 21:00`
**说明:** 月度审计提醒时间

### Daily Log Reminder
**值:** `Every day 21:00`
**说明:** 每日日志提醒时间

**注意:** 提醒功能需要额外的调度脚本支持，当前仅作为参考配置。

---

## 🔧 Advanced Settings

### Max Backup Count
**值:** `50`
**说明:** 最多保留的备份文件数量（超过后自动删除最旧的）

### Search Result Limit
**值:** `100`
**说明:** 搜索结果的最大返回数量

### Context Lines in Search
**值:** `20`
**说明:** 搜索结果中显示的上下文行数

---

## 📖 Usage Notes

1. **首次使用:** 请将 `[Your Name]` 替换为你的真实姓名
2. **路径修改:** 如果修改了目录路径，需要手动迁移现有文件
3. **脚本依赖:** 日历集成功能需要 `get_calendar_events.py` 脚本存在
4. **备份策略:** 建议定期将 `privacy/` 目录备份到云存储

---

**配置文件版本:** v1.0
**最后更新:** 2026-01-29
