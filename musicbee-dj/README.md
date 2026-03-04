# 🎵 MusicBee-DJ (AI 驻场策展人)

**MusicBee-DJ** 是专为 Gemini CLI 打造的**智能本地音乐控制引擎与情绪策展系统（Curation Engine）**。
它超越了传统的“随机播放器”范畴，利用“JIT即时挂载 + 毫秒级 XML 引擎 + DJ 算法数学模型”，根据你当前的情绪、任务强度和场景，全自动为你生成并无缝切入能量最适宜的背景音。

---

## 🌟 核心理念与架构 (GEB-Flow Compliant)

传统的 MusicBee 控制只能触发静态歌单（如“喜欢”或“最新”）。而通过本技能：
1. **0 延迟挂载引擎**：通过后台静默抓取并缓存 iTunes XML，本程序能在毫米级时间内对几万首本地无损音乐进行切片，并即时编译为 JIT `.m3u` 歌单推给 MusicBee。
2. **多维特征感知**：不仅仅根据风格（Genre），它会提取心率（BPM）、总时长（Total Time），打捞库底长草的金曲。
3. **DJ 情绪经营（Curation Engine）**: 
   * **能量爬坡与降落**：自动构建“钟形/阶梯递进”的 BPM 能量曲线，前置舒缓热身 -> 中段极度专注 -> 后段平稳落地。确保心流不断裂。
   * **黄金听感配比**：生成的歌单中，永远维持 “60% 经典金曲 (产生安全感) + 30% 落灰发掘 (制造惊喜) + 10% 新鲜血液” 的绝佳比例。

---

## 🛠️ 前置条件配置 (Installation & Setup)

1. **必要设置**：打开你的 MusicBee，进入 `编辑 (Edit) > 首选项 (Preferences) > 库 (Library)`，**勾选开启 `共享 iTunes 兼容库 XML`**。
2. 打开本技能目录下的 `config.yaml`，确认以下两个绝对路径是否符合你的电脑环境：
   * `musicbee.exe_path`: (MusicBee.exe 的准确位置)
   * `musicbee.xml_path`: (你在步骤 1 中开启后，XML 文件的准确落盘位置)

---

## 💬 如何使用 (How to Trigger)

基于 Gemini NLP 意图引擎，你只需向命令行/侧边栏自然表达你的感受或需要：

- **根据场景驱动 (Scene & Energy)**
  * *"我要集中精神写几个小时代码了，给我放点极速的白噪音。"* -> (触发 `focus` 场景，剔除低 BPM 曲目，进入高能量模型)
  * *"我累了，休息一会儿，放点安静的背景乐。"* -> (触发 `relax` 场景，BPM 设置上限，强制插入 Ambient / Intro 作为降落伞)

- **根据风格驱动 (Direct Genre)**
  * *"放点爵士乐 (Jazz)"*
  * *"来点赛博朋克 (Cyberpunk)"*

- **降级响应保护 (Zero-Shot Fallback)**
  * 即使你提到的场景没有在 `config.yaml` 中配置（例如 *"做家务时听的"*），系统也不会崩溃报错。大模型会推算其背后对应的情感并转换为基础流派（Pop/Dance）平滑接管。

---

## ⚙️ 进阶：配置与自定义你的 DJ (Advanced Configuration)

所有的“场景”与“算法加权”都可以随时在 `config.yaml` 中根据你的收听口味热更新：

```yaml
# 1. 你可以将任意新生成的隐喻词条绑定到你期望的曲风上
scenes:
  coding:
    genres: ["Cyberpunk", "Synthwave", "Trance", "Techno"]

# 2. 控制听歌偏好比例 (加起来必须近似 = 1.0)
curation:
  anchor_ratio: 0.6    # 那些你经常循环的老歌
  discovery_ratio: 0.3 # 躺在库里常年沾灰的歌
  novelty_ratio: 0.1   # 上周刚刚下载的新歌

# 3. 控制大模型判定“激烈”与“舒缓”时的物理 BPM 阈值
energy_curves:
  high_intensity_min_bpm: 110 
  low_intensity_max_bpm: 100 
```

---

*“在数字噪音横行的时代，我们将白噪声的控制权交给算法，把心流（Flow）交还给大脑。”* —— Strategic Architect
