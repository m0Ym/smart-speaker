<div align="center">

# 🎙️ USTB AI Speaker

**一个完全离线的智能音箱 AI 语音交互系统**

本地唤醒 · 语音对话 · 音乐播放 · 智能家居 · 手势体感游戏 · 科幻实时仪表盘

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows%20%7C%20WSL2-blue?style=for-the-badge)
![ASR](https://img.shields.io/badge/ASR-sherpa--onnx%20%7C%20Paraformer-orange?style=for-the-badge)
![TTS](https://img.shields.io/badge/TTS-VITS%20%7C%20EdgeTTS-yellow?style=for-the-badge)
![LLM](https://img.shields.io/badge/LLM-llama.cpp%20%7C%20Qwen2.5-1.5B-purple?style=for-the-badge)

</div>

---

## 📖 目录

- [项目简介](#-项目简介)
- [核心特性](#-核心特性)
- [技术栈](#-技术栈)
- [快速开始](#-快速开始)
- [使用指南](#-使用指南)
- [系统架构](#-系统架构)
- [核心技术详解](#-核心技术详解)
- [配置参考](#-配置参考)
- [项目结构](#-项目结构)
- [模型说明](#-模型说明)
- [部署到音箱硬件](#-部署到音箱硬件)
- [贡献指南](#-贡献指南)
- [许可证](#-许可证)

---

## 📌 项目简介

**USTB AI Speaker** 是一套运行在嵌入式智能音箱上的**全离线**语音交互系统。从硬件层的声音采集、回声消除，到模型层的语音识别 / 语音合成 / 本地大模型推理，再到应用层的技能执行、状态广播与科幻仪表盘，全部在本机闭环完成，**不依赖任何云端服务**。

系统以事件驱动的消息总线为核心，将音频、NLP、视觉、技能、UI 等模块解耦为可插拔组件；所有 AI 引擎（唤醒词、VAD、ASR、TTS、LLM）均采用**策略模式**设计，可随时替换实现而不改动业务代码。此外还集成了**双目视觉深度估计**、**MediaPipe 手势识别**与一套**延迟优化到毫秒级的体感切水果游戏**，构成一个多模态的完整智能体体验。

> 设计目标：在资源受限的嵌入式设备上，达到 **"唤醒 → 识别 → 理解 → 应答" 全链路低延迟** 的流畅对话体验。

---

## ✨ 核心特性

| 能力 | 说明 |
|------|------|
| 🎙️ **自定义唤醒词** | 基于 Picovoice Porcupine，支持任意自定义唤醒词，支持打断（Barge-in） |
| 🗣️ **多引擎语音识别** | sherpa-onnx（Paraformer）、Whisper、Faster-Whisper 可插拔，中文流式识别 |
| 🤖 **本地大模型对话** | llama.cpp 加载 Qwen2.5-1.5B-Instruct（GGUF 量化），完全离线，支持 Function Calling |
| 🔊 **多引擎语音合成** | VITS（Piper 小雅）/ Edge-TTS / pyttsx3 / eSpeak-NG 自动降级链 |
| 🔇 **专业音频链路** | AEC 回声消除 → 带通滤波 → 谱减法降噪 → WebRTC VAD → 能量门控 |
| 🎵 **音乐播放** | 本地音乐库管理、播放/暂停/切歌/音量，全局单例播放器防状态不同步 |
| 🏠 **智能家居** | 可扩展的语音控制技能框架，覆盖灯光、空调等场景 |
| ✋ **手势控制** | MediaPipe 实时手势识别（手指伸展分类、挥手检测），支持语音与手势双模态控制 |
| 📐 **双目深度估计** | OpenCV SGBM 立体匹配 → 视差图 → 物理距离估算，用于空间感知 |
| 🍉 **体感切水果** | 手势驱动的切水果游戏：One Euro 滤波 + 速度估计 + 运动预测，端到端延迟可观测 |
| 📊 **科幻仪表盘** | Web（HTML/CSS/JS）+ pywebview 双形态，WebSocket 实时推送系统状态 |
| 📈 **SLA 监控** | 全链路指标采集（延迟、成功率、状态转移耗时），影子案例加密落盘 |
| ⏰ **技能插件化** | 9 种技能通过工厂注册，一行代码扩展新能力 |

---

## 🧰 技术栈

| 领域 | 技术 | 说明 |
|------|------|------|
| **语音识别** | [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) + Paraformer | 中文流式/非流式 ASR，ONNX 推理，int8 量化 |
| **唤醒词** | [Picovoice Porcupine](https://github.com/Picovoice/porcupine) | 离线唤醒词检测，可自定义关键词 |
| **VAD** | [WebRTC VAD](https://webrtc.org/) | 语音活动检测，判定说话起止 |
| **语音合成** | [Piper](https://github.com/rhasspy/piper)（VITS）/ Edge-TTS | 中文神经网络 TTS，自动降级 |
| **本地 LLM** | [llama.cpp](https://github.com/ggml-org/llama.cpp) + Qwen2.5-1.5B | GGUF 量化模型，CPU/GPU 推理，Function Calling |
| **音频处理** | NumPy + sounddevice | 带通滤波、谱减法降噪、AEC、能量门控 |
| **事件框架** | 自研 MessageBus | 事件驱动架构，50+ 事件类型，优先级订阅 |
| **状态管理** | 自研 StateMachine | 6 状态有限状态机，合法转移校验 |
| **实时通信** | [websockets](https://github.com/python-websockets/websockets) | 系统状态 WebSocket 广播（:8765） |
| **视觉** | [MediaPipe Hands](https://github.com/google-ai-edge/mediapipe) + OpenCV | 手部 21 关键点追踪、手势分类 |
| **深度估计** | OpenCV SGBM | 双目立体匹配，物理距离估算 |
| **桌面 UI** | [pywebview](https://github.com/r0x0r/pywebview) | 轻量 WebView 仪表盘窗口 |
| **游戏** | Pygame + Web Canvas | 游戏逻辑与渲染分离，WebSocket 同步 |
| **配置** | [pydantic](https://github.com/pydantic/pydantic) + dotenv | 类型安全配置，环境变量覆盖 |
| **监控** | 自研 SLAMonitor + [cryptography](https://github.com/pyca/cryptography) | SLA 指标采集，影子案例 Fernet 加密 |

---

## 🚀 快速开始

### 环境要求

- **Python** 3.8+（推荐 3.10 / 3.11）
- **操作系统**：Linux（含 WSL2）/ Windows / 树莓派类嵌入式设备
- **硬件**：麦克风 + 扬声器（音箱本体或开发机），摄像头（可选，用于手势与体感游戏）

### 1. 克隆仓库

```bash
git clone https://github.com/m0Ym/smart-speaker.git
cd smart-speaker/speaker/smartspeaker
```

### 2. 安装依赖

```bash
pip install -r requirements.txt        # 语音核心依赖
pip install -r ../LinuxFruitV2/requirements.txt   # （可选）体感游戏依赖
```

> 若在 WSL2 / 嵌入式 Linux 上运行，需先安装系统级依赖：
> ```bash
> sudo apt install portaudio19-dev libopencv-dev python3-opencv
> ```

### 3. 准备模型

将模型放入 `speaker/models/`（详见 [模型说明](#-模型说明)）：

```
speaker/models/
├── asr/sherpa-onnx-paraformer-zh-2023-09-14/   # ASR 模型（需下载，~243MB）
└── vits-zh/                                     # TTS 模型（需下载，~63MB）
```

### 4. 运行

```bash
python main.py              # 默认：融合模式（语音核心 + 仪表盘）
```

---

## 🎮 使用指南

### 运行模式

| 命令 | 模式 | 说明 |
|------|------|------|
| `python main.py` | **fusion** | 语音核心 + 仪表盘（默认） |
| `python main.py --mode preview` | **preview** | 仅仪表盘 UI，无语音 |
| `python main.py --mode cli` | **cli** | 仅语音核心，命令行交互 |
| `python main.py --mode browser` | **browser** | 语音核心 + HTTP，浏览器访问 |

### 语音交互示例

说话前先说唤醒词（默认 **"你好小智"**）：

```
你好小智，播放音乐          → 启动音乐播放
你好小智，下一首            → 切换歌曲
你好小智，查询北京的天气     → 天气技能
你好小智，设置一个闹钟       → 闹钟技能
你好小智，讲个笑话          → 笑话技能
你好小智，打开切水果         → 启动体感切水果游戏
你好小智，再见              → 语音关闭系统
```

唤醒词、音色、语速等全部可通过 `.env` 覆盖，见 [配置参考](#-配置参考)。

### 硬件音频设备

系统自动扫描音频设备：输入设备匹配 `FYSP003` 系列麦克风，输出匹配 `UACDemoV10` 扬声器。也可通过 `INPUT_DEVICE_NAME` / `OUTPUT_DEVICE_NAME` 指定。

---

## 🏗️ 系统架构

```
┌───────────────────────────────────────────────────────────────────┐
│                           用户 / 场景                              │
└───────┬───────────────────────────┬───────────────────────┬───────┘
        │ 麦克风                     │ 摄像头（可选）         │ 触屏/浏览器
┌───────▼───────────┐   ┌───────────▼────────────┐   ┌──────▼─────────┐
│  音频采集链路       │   │  视觉感知模块           │   │  UI / 仪表盘    │
│  sounddevice      │   │  MediaPipe 手势        │   │  pywebview      │
│  16kHz / 单声道    │   │  双目 SGBM 深度估计     │   │  Web 前端       │
└───────┬───────────┘   └───────────┬────────────┘   └──────┬─────────┘
        │ AUDIO_INPUT               │ VISION_FRAME          │ UI_UPDATE
┌───────▼─────────────────────────────────────────────────────────────┐
│                     MessageBus 事件消息总线                          │
│        （50+ 事件类型 / 优先级订阅 / 事件历史 / 异步分发）            │
└───┬──────────┬───────────┬───────────┬───────────┬───────┬─────────┘
    │          │           │           │           │       │
┌───▼───┐ ┌────▼────┐ ┌────▼─────┐ ┌───▼────┐ ┌───▼────┐ ┌─▼─────────┐
│ Audio │ │ WakeWord│ │   ASR    │ │  NLP   │ │ TTS    │ │  Vision   │
│链路   │ │ Porcupine││ Paraformer│ │ Qwen2.5│ │ VITS   │ │  手势/深度 │
│AEC/VAD│ │  /VAD   │ │ /Whisper │ │ /意图  │ │ /Edge  │ │           │
└───┬───┘ └─────────┘ └──────────┘ └───┬────┘ └───┬────┘ └───────────┘
    │                                  │         │
    │                           ┌──────▼──────┐  │
    │                           │ DialogManager│ │
    │                           │ SkillFactory │ │
    │                           │  9 种技能    │ │
    │                           └──────┬──────┘  │
    │                                  │         │
┌───▼──────────────────────────────────▼─────────▼───────────────┐
│          WebSocket 广播 / SLA 监控 / 状态机 / 仪表盘             │
└──────────────────────────────────────────────────────────────────┘
```

### 核心设计思想

1. **事件驱动，模块解耦**：所有模块只通过 `MessageBus` 通信，互不直接引用。新增一个感知模块只需订阅/发布事件。
2. **策略模式，引擎可插拔**：唤醒词、VAD、ASR、TTS、LLM 全部抽象为策略接口，`AutoTTS` 等策略管理器实现运行时自动降级。
3. **单例管理，状态一致**：`MusicPlayerManager` 等全局单例确保多模块共享同一播放器实例，避免状态不同步。
4. **有限状态机，防非法迁移**：`IDLE → WAKED_UP → LISTENING → PROCESSING → SPEAKING`，每次转移都校验合法性。

---

## 🔬 核心技术详解

### 1. 音频处理流水线（`src/audio/`）

这是系统的"听觉中枢"，原始 PCM 数据经过五级处理才进入语音识别：

```
麦克风 PCM
   │
   ▼
① AEC 回声消除（AECProcessor）
   │  消除音箱自身播放的音频回灌，防止"自说自话"
   ▼
② 带通滤波（300Hz - 8000Hz）
   │  滤除低频环境噪声与高频杂音，保留人声主频带
   ▼
③ 谱减法降噪（ANS）
   │  基于噪声谱估计的背景稳态降噪，提升信噪比
   ▼
④ WebRTC VAD
   │  能量阈值 + 过零率联合判定语音起止，支持静音时长配置
   ▼
⑤ 能量门控（AudioGate）
   │  门控信号输出，门控恢复延迟防误触发
   ▼
唤醒词检测 / ASR
```

关键模块：
- **`AECProcessor`**：声学回声消除，避免扬声器声音被麦克风重新拾取。
- **`AudioPreprocessor`**：带通滤波（`FILTER_LOW_CUT` / `FILTER_HIGH_CUT`）+ 谱减法降噪（噪声历史 20 帧自适应衰减）。
- **`AudioGate`**：`controlled` 门控模式，支持门控恢复延迟、AEC 联动。
- **`device_finder`**：自动发现指定品牌麦克风/扬声器，免配置即插即用。

### 2. 多引擎策略体系（策略模式）

所有 AI 引擎抽象为策略接口，业务代码零改动即可替换：

| 能力 | 接口 | 内置实现 | 说明 |
|------|------|----------|------|
| 唤醒词 | `WakeWordStrategy` | `PorcupineWakeWord` / `MockWakeWord` | 本地关键词识别 |
| VAD | `VADStrategy` | `WebRTCVAD` / `MockVAD` | 语音活动检测 |
| ASR | `ASRStrategy` | `SherpaOnnxASR`、`ParaformerASR`、`WhisperASR`、`FasterWhisperASR` | 多引擎切换（`ASR_ENGINE`） |
| TTS | `TTSStrategy` | `SherpaOnnxTTS`、`EdgeTTSTTS`、`Pyttsx3TTS`、`EspeakNGTTS` | `AutoTTS` 自动降级链 |
| LLM | — | llama.cpp / 规则引擎 | `OFFLINE_MODE` 离线运行 |

**TTS 自动降级链**：`SherpaOnnxTTS（本地 VITS）→ Edge-TTS → pyttsx3 → eSpeak-NG`。本地模型缺失时自动回退在线引擎，保证系统永远"能说话"。

### 3. 事件驱动消息总线（`src/core/message_bus.py`）

自研的轻量事件总线，是全系统的"神经网络"：

- **50+ 预定义事件类型**：音频（`audio.*`）、音乐（`music.*`）、NLP（`nlp.*`）、视觉（`vision.*`）、系统（`system.*`）等
- **优先级订阅**：同一事件可注册多个处理器，按优先级依次执行（如全局音乐处理器 `priority=5` 优先于默认）
- **事件历史**：可查询最近 N 条事件，便于调试与状态恢复
- **同步 + 异步双通道**：`publish`（同步）与 `publish_async`（asyncio）并存

### 4. 有限状态机（`src/core/state_machine.py`）

系统行为由状态机驱动，禁止非法状态跳跃：

```
IDLE → WAKED_UP → LISTENING → PROCESSING → SPEAKING → IDLE
  │        │          │           │            │
  └────────┴──────────┴───────────┴────────────┴──→ ERROR（异常兜底）
```

- 每次转移校验 `VALID_TRANSITIONS` 白名单，非法转移直接拒绝
- 记录每次转移耗时（`StateTransition`），供 SLA 分析
- 状态变化通过 `SYSTEM_STATE_CHANGE` 事件广播到仪表盘

### 5. NLP 与 Function Calling（`src/nlp/`）

**意图识别（`recognizeIntent`）**：基于正则模式库的意图分类（天气/音乐/闹钟/闲聊/家居/游戏等），零延迟、无需模型。

**LLM 对话（`_try_llm_chat`）**：`OFFLINE_MODE=true` 时通过 llama.cpp 加载 `Qwen2.5-1.5B-Instruct` GGUF 模型推理，支持：
- 多轮上下文管理（`ChatMessage` 列表，`manageContext`）
- **流式输出**（`generateResponse` 生成器）：按语义分句（`SemanticChunker`，按 `。！？` 切分）逐句送入 TTS，实现"边说边生成"
- **Function Calling**：LLM 输出经 `_detect_function_call` 解析为结构化调用，`ToolExecutor` 执行 `system_tools` 注册的工具，结果回填上下文后生成最终回复

### 6. 技能系统（`src/skills/`）

基于注册表工厂（`SkillFactory`）的插件化架构：

| 技能 | 触发示例 | 实现 |
|------|----------|------|
| `weather` 天气 | "查询北京的天气" | 城市库 + 天气 API |
| `music` 音乐 | "播放音乐" / "下一首" | 全局 MusicPlayer |
| `alarm` 闹钟 | "设置一个闹钟" | 定时任务 |
| `joke` 笑话 | "讲个笑话" | 随机笑话库 |
| `chat` 闲聊 | 日常对话 | LLM / 规则 |
| `smarthome` 智能家居 | "打开客厅的灯" | 指令框架（可扩展） |
| `fruit_ninja` 切水果 | "打开切水果" | 启动体感游戏服务 |
| `gesture` 手势 | 手势切换 | 视觉手势识别联动 |
| `system_command` 系统命令 | "关机" / "打开应用" | 白名单安全执行 |

新增技能：继承 `BaseSkill` → 实现 `execute` → 在 `SkillFactory` 注册，一行完成。

### 7. 视觉与空间感知（`src/vision/`）

**手势识别（`GestureRecognizer`）**：
- MediaPipe Hands 提取 21 个手部关键点
- 手指伸展判定：指尖与近端指间关节距离 + 拇指夹角分类
- 挥手检测：跟踪手部横向运动轨迹
- 输出 `GestureResult`（手势类型 + 置信度），通过 `GESTURE_DETECTED` 事件联动技能

**双目深度估计（`VisionDepth`）**：
- 双目摄像头捕获左右视图（2560×720 拼接或双路）
- OpenCV **SGBM 半全局立体匹配**计算视差图
- 视差 → 深度换算（基线 `stereo_baseline`、焦距 `focal_length` 可标定）
- 输出目标距离（`DepthResult.distance`），用于空间交互（如手势靠近音箱触发操作）

### 8. 体感切水果游戏（`LinuxFruitV2/`）

手势驱动的完整体感游戏，核心难点是**交互延迟**：

```
摄像头 → MediaPipe 手部关键点 → One Euro 滤波 → 速度估计 → 运动预测 → 切水果判定 → WebSocket → Web 渲染
   │          │                      │              │            │
   └──────────┴──────────────────────┴──────────────┴────────────┴── LatencyAnalyzer 逐阶段计时
```

| 组件 | 作用 |
|------|------|
| **`OneEuroFilter`** | 一欧元滤波：低延迟 + 平滑，`min_cutoff`/`beta` 控制滤波强度 |
| **`VelocityEstimator`** | 加权历史窗口估计手部速度（5 帧加权） |
| **`MotionPredictor`** | 33ms 前向预测，补偿"采集→渲染"链路延迟 |
| **`SliceDetector`** | 挥切判定：速度得分 × 距离得分 × 方向一致性综合评分 |
| **`LatencyAnalyzer`** | 采集/推理/滤波/预测/渲染五阶段计时，端到端延迟可视化 |
| **`GameServer`** | WebSocket + HTTP 双服务，Pygame 逻辑 + Web Canvas 渲染分离 |

游戏特性：重力物理、粒子特效、连击（Combo）计分、炸弹、`SLASH_MODE_FRUIT_MULTIPLIER=3` 三倍得分模式、`GAME_FPS=60`。

### 9. SLA 监控（`src/monitoring/sla.py`）

- 采集全链路指标：唤醒延迟、VAD 延迟、ASR 延迟、LLM 首字延迟、TTS 延迟、整体响应时间
- 状态机各阶段耗时记录
- **影子案例（Shadow Cases）**：将典型交互案例加密（Fernet）落盘，用于回归测试与质量分析，敏感数据不落明文

### 10. UI 与仪表盘（`src/ui/` + `dashboard/` + `web/`）

- **主屏（`MainScreen`）**：1280×800 状态界面
- **墨水屏（`EInkScreen`）**：296×128 低功耗墨水屏，SPI 驱动，时钟/状态双模式
- **pywebview 仪表盘（`dashboard/`）**：IPC Bridge + WebChannel + 系统遥测
- **Web 前端（`web/`）**：科幻风格深色主题，粒子动画、霓虹光效，WebSocket 实时接收系统状态（唤醒词、状态机、延迟指标）

---

## ⚙️ 配置参考

所有配置集中在 `src/config.py`（pydantic 模型，类型安全），通过项目根目录 `.env` 文件以环境变量覆盖：

```bash
# ===== 音频 =====
AUDIO_SAMPLE_RATE=16000
WAKE_WORD=你好小智              # 自定义唤醒词
VAD_MODE=1
INPUT_DEVICE_NAME=FYSP003       # 麦克风设备名
OUTPUT_DEVICE_NAME=UACDemoV10   # 扬声器设备名
AEC_ENABLED=true
BARGE_IN_ENABLED=true           # 语音打断

# ===== ASR / TTS =====
ASR_ENGINE=sherpa_onnx          # sherpa_onnx / whisper / faster_whisper
SHERPA_ASR_MODEL=               # ASR 模型路径
TTS_ENGINE=auto                 # auto 自动降级
TTS_VOICE=zh-CN-XiaoxiaoNeural

# ===== NLP / LLM =====
OFFLINE_MODE=true               # 离线大模型推理
NLP_MODEL_PATH=models/LLM/qwen2.5-1.5b-instruct-q4_k_m.gguf
LLM_MAX_TOKENS=150
FUNCTION_CALLING_ENABLED=true

# ===== 视觉 =====
VISION_ENABLED=false
CAMERA_INDEX=0
STEREO_BASELINE=0.06            # 双目基线（米）
FOCAL_LENGTH=500.0              # 焦距（像素）

# ===== 系统 =====
LOG_LEVEL=INFO
ENVIRONMENT=auto
ENABLE_DATA_COLLECTION=true
```

---

## 📂 项目结构

```
smart-speaker/
├── speaker/                            # 核心代码
│   ├── smartspeaker/                   # 语音核心（主程序）
│   │   ├── main.py                     # 统一入口（4 种运行模式）
│   │   ├── src/
│   │   │   ├── audio/                  # 音频：AEC / 滤波 / VAD / 门控 / ASR / TTS / 播放
│   │   │   ├── core/                   # 框架：消息总线 / 状态机 / 策略 / 工厂 / WebSocket
│   │   │   ├── dialog/                 # 多轮对话管理（会话状态机）
│   │   │   ├── monitoring/             # SLA 监控（指标 + 影子案例加密）
│   │   │   ├── nlp/                    # NLP：意图识别 / LLM 对话 / 语义分块 / 工具执行
│   │   │   ├── skills/                 # 技能系统（9 种插件化技能）
│   │   │   ├── ui/                     # 主屏 / 墨水屏 UI
│   │   │   ├── utils/                  # 单例日志等工具
│   │   │   └── vision/                 # 手势识别 / 双目深度估计
│   │   ├── dashboard/                  # pywebview 仪表盘引擎
│   │   └── web/                        # Web 前端（科幻仪表盘）
│   ├── LinuxFruitV2/                   # 体感切水果游戏
│   │   ├── tracking/                   # 手部追踪 / One Euro 滤波 / 运动预测 / 延迟分析
│   │   ├── game/                       # 游戏逻辑（物理 / 碰撞 / 计分 / 生成）
│   │   ├── gesture/ input/ filter/     # 手势检测 / 输入控制 / 信号滤波
│   │   ├── static/                     # Web 渲染端（Canvas / 音效 / 素材）
│   │   └── game_server.py              # WebSocket + HTTP 游戏服务
│   ├── models/                         # AI 模型（大文件不入库，见模型说明）
│   └── data/                           # 运行数据（日志 / 音乐库）
├── .gitignore
├── LICENSE
└── README.md
```

---

## 🤖 模型说明

系统完全离线运行需要以下模型（大文件不入库，请按表下载）：

| 用途 | 模型 | 大小 | 下载地址 |
|------|------|------|----------|
| ASR | sherpa-onnx-paraformer-zh-2023-09-14 | ~243MB | [ModelScope: speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx](https://www.modelscope.cn/models/damo/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx) |
| TTS | Piper zh_CN 小雅 medium（VITS） | ~63MB | [Piper 语音模型库](https://github.com/rhasspy/piper) / [HuggingFace: rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) |
| LLM（可选） | Qwen2.5-1.5B-Instruct GGUF | ~1GB | [Qwen 官方](https://huggingface.co/Qwen) + llama.cpp 量化 |

> 提示：仓库已包含模型配套配置（`config.yaml`、`tokens.txt`、词表等），只需下载模型本体（`.onnx` / `.gguf`）放入对应目录。
> 使用 Edge-TTS 引擎（`TTS_ENGINE=edge`）可省略 TTS 模型；`ASR_AUTO_DOWNLOAD=true` 可自动下载 ASR 模型。

---

## 📦 部署到音箱硬件

### systemd 服务（推荐）

```bash
# 1. 复制到设备
scp -r speaker user@speaker-ip:/opt/smart-speaker

# 2. 安装依赖并配置
ssh user@speaker-ip
cd /opt/smart-speaker
python3 -m venv venv && source venv/bin/activate
pip install -r smartspeaker/requirements.txt

# 3. systemd 服务
sudo tee /etc/systemd/system/smart-speaker.service > /dev/null <<'EOF'
[Unit]
Description=USTB AI Speaker
After=network.target sound.target

[Service]
WorkingDirectory=/opt/smart-speaker
ExecStart=/opt/smart-speaker/venv/bin/python smartspeaker/main.py --mode cli
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now smart-speaker
journalctl -u smart-speaker -f     # 查看日志
```

### WSL2 开发环境

WSL2 默认无音频设备，可通过 PulseAudio 转发或 usbipd USB 直通启用（详见项目 `docs` 目录的部署文档）。

---

## 🤝 贡献指南

欢迎贡献代码、文档或想法！

1. Fork 本仓库并创建你的分支：`git checkout -b feat/your-feature`
2. 提交改动：`git commit -m "feat: add your feature"`
3. 推送分支：`git push origin feat/your-feature`
4. 发起 Pull Request

**开发约定**：
- 新技能：继承 `BaseSkill`，在 `SkillFactory` 注册
- 新 AI 引擎：实现对应 `Strategy` 接口
- 代码风格：遵循 PEP 8，模块需带 docstring
- 涉及配置：同步更新 `config.py` 与本文档配置参考

---

## 📄 许可证

本项目基于 [MIT License](LICENSE) 开源。

## 🙏 致谢

- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) — 高性能离线语音推理框架
- [llama.cpp](https://github.com/ggml-org/llama.cpp) — 本地大模型推理
- [Piper](https://github.com/rhasspy/piper) — 中文 VITS 语音合成
- [MediaPipe](https://github.com/google-ai-edge/mediapipe) — 手部关键点追踪
- [Picovoice Porcupine](https://github.com/Picovoice/porcupine) — 唤醒词检测
- [pywebview](https://github.com/r0x0r/pywebview) — 轻量桌面 WebView
