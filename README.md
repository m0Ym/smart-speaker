# USTB AI Speaker 智能音箱 AI 语音交互系统

北京科技大学（USTB）生产实习 / 结课考核项目。基于本地 AI 模型，实现了一台可离线运行的智能音箱：支持唤醒词、语音对话、音乐播放、智能家居控制、体感切水果游戏，并配备科幻风格的实时仪表盘界面。

![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Platform](https://img.shields.io/badge/Platform-Linux%2FWindows-blue?style=flat-square)

---

## 功能特性

| 模块 | 说明 |
|------|------|
| 🎙️ 语音唤醒 | 自定义唤醒词（默认"你好小智"），支持打断（Barge-in） |
| 🗣️ 语音识别 (ASR) | 基于 sherpa-onnx + Paraformer 中文流式识别，完全离线 |
| 🤖 本地大模型对话 | llama.cpp 加载 Qwen2.5-1.5B-Instruct（GGUF），支持 Function Calling |
| 🔊 语音合成 (TTS) | sherpa-onnx / Piper VITS 中文语音（小雅），支持自动降级 |
| 🎵 音乐播放 | 本地音乐库播放、上一曲/下一曲/暂停/继续，支持语音与界面双控制 |
| 🏠 智能家居 | 语音控制指令框架（灯、空调等场景可扩展） |
| 🍉 体感游戏 | 手势控制切水果游戏（MediaPipe + Pygame） |
| ✋ 手势识别 | 摄像头实时手势识别与距离感知（双目深度估计） |
| 📊 科幻仪表盘 | Web 前端（HTML/CSS/JS）+ WebSocket 实时推送系统状态 |
| ⏰ 技能系统 | 天气、闹钟、笑话、闲聊、系统命令等 9 种技能插件化注册 |

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                       用户 / 场景                            │
└───────────────┬─────────────────────────────┬───────────────┘
                │ 麦克风输入                    │ 手势 / 深度相机
┌───────────────▼──────────────┐   ┌───────────▼───────────────┐
│  AudioProcessor 音频链路      │   │  Vision 视觉模块           │
│  预处理 → 滤波 → VAD → 门控  │   │  手势识别 / 深度估计        │
└───────────────┬──────────────┘   └───────────┬───────────────┘
                │ 唤醒词                        │
┌───────────────▼──────────────────────────────────────────────┐
│                    MessageBus 消息总线（事件驱动）             │
├───────────────┬───────────────┬───────────────┬──────────────┤
│ ASR (Paraformer)│ NLP (Qwen2.5)│ ToolExecutor  │ DialogManager│
│ 语音转文字      │ 意图理解/对话 │ 工具调用执行   │ 多轮对话管理  │
└───────────────┴───────┬───────┴───────┬───────┴──────────────┘
                        │               │
              ┌─────────▼──────┐  ┌─────▼──────────────┐
              │ SkillFactory  │  │ TTS 语音合成        │
              │ 9 种技能插件   │  │ (VITS / 边缘 TTS)   │
              └─────────┬──────┘  └─────┬──────────────┘
                        │ 播放/控制      │ 音频输出
              ┌─────────▼───────────────▼──────────────┐
              │  仪表盘 WebSocket 广播 / SLA 监控       │
              │  pywebview / 浏览器科幻界面             │
              └────────────────────────────────────────┘
```

核心运行方式：事件驱动的消息总线（`src/core/message_bus.py`）串联音频、NLP、技能与 UI 各模块；音频链路包含自动回声消除（AEC）、噪声抑制、能量门控等多级处理。

## 目录结构

```
├── speaker/                          # 核心代码
│   ├── smartspeaker/                 # 语音核心
│   │   ├── main.py                   # 统一入口（4 种运行模式）
│   │   ├── src/                      # 源码
│   │   │   ├── audio/                # 音频采集、AEC、VAD、门控、播放、TTS
│   │   │   ├── core/                 # 消息总线、状态机、WebSocket 广播
│   │   │   ├── dialog/               # 多轮对话管理
│   │   │   ├── monitoring/           # SLA 监控
│   │   │   ├── nlp/                  # 大模型对话、流式缓冲、工具执行
│   │   │   ├── skills/               # 技能系统（9 种技能）
│   │   │   ├── ui/                   # 墨水屏 / 主屏 UI
│   │   │   ├── utils/                # 日志工具
│   │   │   └── vision/               # 手势识别、深度估计
│   │   ├── dashboard/                # pywebview 仪表盘引擎
│   │   └── web/                      # Web 前端（科幻风格仪表盘）
│   ├── LinuxFruitV2/                 # 体感切水果游戏（MediaPipe + Pygame）
│   ├── models/                       # AI 模型（见下方"模型说明"，大文件需自行下载）
│   └── data/                         # 运行数据（日志 / 音乐库，不入库）
├── .gitignore
├── LICENSE
└── README.md
```

## 快速开始

### 环境要求

- Python 3.8+（推荐 3.10/3.11）
- Linux（含 WSL2）或 Windows
- 麦克风与扬声器（音箱本体 / 开发机）
- （可选）摄像头，用于手势与体感游戏

### 1. 安装依赖

```bash
cd speaker/smartspeaker
pip install -r requirements.txt   # 语音核心依赖
```

> 注意：`requirements.txt` 在 `speaker/smartspeaker/` 目录下（体感游戏另见 `speaker/LinuxFruitV2/requirements.txt`）。

### 2. 准备模型

将以下模型放入 `speaker/models/`（详见下文"模型说明"）：

```
speaker/models/
├── asr/sherpa-onnx-paraformer-zh-2023-09-14/   # ASR 模型（需下载）
└── vits-zh/                                     # TTS 模型（需下载）
```

### 3. 运行

```bash
cd speaker/smartspeaker
python main.py              # 默认：融合模式（语音核心 + 仪表盘）
python main.py --preview    # 仅仪表盘 UI，不启动语音
python main.py --cli        # 仅语音核心，命令行交互
python main.py --browser    # 语音核心 + HTTP，浏览器访问仪表盘
```

说话前先说唤醒词（默认"你好小智"），例如：*"你好小智，播放音乐"*。

### 4. 配置

所有配置项集中在 `src/config.py`，均可通过项目根目录 `.env` 环境变量覆盖（如 `WAKE_WORD`、`AUDIO_SAMPLE_RATE`、`ASR_ENGINE`、`NLP_MODEL_PATH` 等）。配置文件会自动从 `speaker/.env` 或当前目录加载。

### 5. 部署到 Linux 音箱设备

参考 `docs/WSL_DEPLOYMENT.md`（WSL2 开发环境搭建、PulseAudio 音频转发 / USB 设备直通、systemd 服务部署）。核心部署命令：

```bash
# 1. 将项目复制到音箱设备
scp -r speaker user@speaker-ip:/opt/smart-speaker

# 2. SSH 到音箱并安装服务
ssh user@speaker-ip
cd /opt/smart-speaker
sudo bash scripts/install.sh    # 如脚本缺失，直接使用 python 虚拟环境 + systemd 托管
sudo systemctl start smart-speaker
```

## 模型说明

本项目完全离线运行，需要以下模型（大文件不入库，请自行下载）：

| 用途 | 模型 | 大小 | 下载地址 |
|------|------|------|----------|
| ASR 语音识别 | sherpa-onnx-paraformer-zh-2023-09-14 | ~243MB | [ModelScope: damo/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx](https://www.modelscope.cn/models/damo/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx) |
| TTS 语音合成 | Piper zh_CN 小雅 medium (VITS) | ~63MB | [Piper 语音模型库](https://github.com/rhasspy/piper) / [HuggingFace: rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) |

下载后解压到对应目录（如上文所示）。若使用 Edge TTS 引擎（`TTS_ENGINE=edge`），TTS 模型可省略；`ASR_AUTO_DOWNLOAD=true` 时 ASR 模型也可自动下载。

## 相关项目

- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) — 离线语音识别 / 合成推理框架
- [llama.cpp](https://github.com/ggml-org/llama.cpp) — 本地大模型推理
- [MediaPipe](https://github.com/google-ai-edge/mediapipe) — 手势识别
- [Piper](https://github.com/rhasspy/piper) — VITS 中文语音合成

## License

[MIT](LICENSE)
