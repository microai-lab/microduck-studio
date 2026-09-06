<p align="center">
  <img src="docs/images/microduck-studio-hero-placeholder.png" alt="Microduck Studio 开发工作区预览" width="100%">
</p>

<h1 align="center">Microduck Studio</h1>

<p align="center">一个用于开发、仿真和验证 Microduck 的本地控制台。</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
  <img alt="Docker Compose" src="https://img.shields.io/badge/Docker_Compose-2496ED?logo=docker&logoColor=white">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-f2c94c"></a>
</p>

<p align="center">
  支持 AI Coding：
  <a href="https://developers.openai.com/codex/">Codex</a> ·
  <a href="https://code.claude.com/docs/en/overview">Claude Code</a> ·
  <a href="https://cursor.com/docs/agent/overview">Cursor Agent</a> ·
  <a href="https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli">GitHub Copilot CLI</a>
</p>

<p align="center">
  <a href="#使用-ai-coding-工具启动">AI 启动</a> ·
  <a href="#快速开始">快速开始</a> ·
  <a href="#robotctl-monitor">终端监控</a> ·
  <a href="#三个项目如何协作">项目架构</a> ·
  <a href="#页面无法控制机器人时">故障排查</a>
</p>

<p align="center">
  <sub>概念预览——这张占位图以后会替换为 Web 界面、<code>robotctl monitor</code> 与 MuJoCo 的真实整合截图。</sub>
</p>

Microduck Studio 把现有的
[`microduck`](https://github.com/pollen-robotics/microduck) 运行时和
[`microduck_rl`](https://github.com/pollen-robotics/microduck_rl) 仿真/训练项目连接成一套
基于浏览器的开发流程。它负责呈现状态和安全控制，不会复制机器人安全、策略推理、仿真物理
或训练逻辑。

## 使用 AI Coding 工具启动

任何能够访问项目文件和本地终端的 AI Coding 工具都可以启动完整链路，不需要专用集成。
常用工具包括 [Codex](https://developers.openai.com/codex/)、
[Claude Code](https://code.claude.com/docs/en/overview)、
[Cursor Agent](https://cursor.com/docs/agent/overview) 和
[GitHub Copilot CLI](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli)。

使用本地会话打开 `microduck-dev` 工作区，然后输入：

```text
帮我启动 Microduck Studio 的所有服务。先阅读 AGENTS.md 和 microduck-studio/README.zh-CN.md，
检查三个同级仓库、Docker、uv，以及 7801 和 8090 端口；然后进入 microduck-studio 运行
./scripts/dev-stack.sh。等待出现“control probe passed”后，再报告 Studio 地址以及 Studio、
robotd 和 MuJoCo 的状态。不要启动训练任务，也不要切换或修改兄弟仓库的工作分支。
```

> 应使用能够访问 Docker 和桌面环境的本地 Agent 会话。云端或后台 Agent 可能运行在另一台
> 机器上，无法在开发主机上显示原生 MuJoCo Viewer。

## 快速开始

### 环境要求

- Docker（含 Docker Compose）
- `git` 和 `curl`
- Python 3 和 [`uv`](https://docs.astral.sh/uv/)

> 各项目均可直接在宿主机运行，本身不强制依赖 Docker。`dev-stack.sh` 使用 Docker 隔离
> `robotd` 与 Studio Web 的构建和运行环境，因此一键联合启动仍需 Docker。macOS 可以使用
> Docker Desktop，也可以使用其他兼容的 Docker 运行环境。

### 1. 下载三个仓库

Studio 不能脱离另外两个项目单独启动完整链路：`microduck` 提供 `robotd` 和策略，
`microduck_rl` 提供 MuJoCo 身体与 Viewer。三个仓库必须位于同一个工作区的同级目录：

```text
microduck-dev/          # 仅作为工作区，不是 Git 仓库
├── microduck/          # robotd、robotctl、策略和运行时协议
├── microduck_rl/       # MuJoCo 身体、Viewer、环境和训练
└── microduck-studio/   # Web 界面和开发链路编排
```

全新安装时，下载该开发工作区使用的三个仓库：

```bash
mkdir -p ~/microduck-dev
cd ~/microduck-dev

git clone https://github.com/ttfont/microduck.git
git clone https://github.com/ttfont/microduck_rl.git
git clone https://github.com/microai-lab/microduck-studio.git
```

下载地址：[microduck](https://github.com/ttfont/microduck)、
[microduck_rl](https://github.com/ttfont/microduck_rl) 和
[microduck-studio](https://github.com/microai-lab/microduck-studio)。前两个是
[官方运行时仓库](https://github.com/pollen-robotics/microduck) 和
[官方 RL 仓库](https://github.com/pollen-robotics/microduck_rl) 的开发分支仓库。

如果仓库已经存在，请不要重复克隆，只需确认目录结构符合上图。

### 2. 准备仿真后端

完整的 MuJoCo 联调需要官方 `microduck` 的 `sim-remote-io` 分支。当前开发分支的常规运行时
没有 `robotd --sim` 后端；该分支提供远程 `RobotIo` 实现，使 `robotd` 可以连接 MuJoCo
身体服务（默认 TCP `127.0.0.1:7801`）。

首次准备工作区时执行：

```bash
git -C microduck remote add upstream https://github.com/pollen-robotics/microduck.git
git -C microduck fetch upstream sim-remote-io
```

`remote add` 只需执行一次；如果已经存在 `upstream`，只执行第二条即可。这些命令只添加仓库
地址并下载分支，不会切换 `microduck` 的当前分支。启动器会读取
`upstream/sim-remote-io` 并把源码展开到 Studio 的隔离状态目录；如果没有提前获取，它也会
自动把该分支下载到 `.studio-runtime/dev-stack/sim-runtime.git`，不会修改兄弟仓库的分支
或工作区文件。`robotd --sim` 在完整控制链路中的作用见
[三个项目如何协作](#三个项目如何协作)。

### 3. 准备 RL 环境

macOS 原生 Viewer 从 `microduck_rl` 的虚拟环境运行：

```bash
cd ~/microduck-dev/microduck_rl
uv sync
```

### 4. 启动并验证完整链路

```bash
cd ~/microduck-dev/microduck-studio
./scripts/dev-stack.sh
```

打开 **http://127.0.0.1:8090**。默认 `native` 模式会在 macOS 后台启动 MuJoCo，以获得
流畅的原生 OpenGL 离屏渲染，但不会弹出桌面 Viewer；支持仿真的 `robotd` 与 Studio 在
Docker 中运行。启动器最后通过移动仿真机器人验证完整控制链路。仅能打开网页不代表已经
就绪；请等待：

```text
control probe passed: MuJoCo moved ... m
```

> 启动器不会切换兄弟仓库的工作分支。它会把所需的 `sim-remote-io` 运行时版本
> 展开到隔离的本地状态目录。

## 主要能力

| 能力 | 内容 |
|---|---|
| Web 控制 | 适合手机操作的移动、启用/停止、坐下/站起、前滚翻和踢球 |
| 实时可见性 | 浏览器内 MuJoCo 画面、机器人遥测、仓库/任务状态及模型发现 |
| 安全编排 | Docker Compose 生命周期、端到端控制探测和白名单 RL 冒烟测试 |

运动控制始终使用一个持久 `robotd` 连接。松开控件、隐藏页面、连接断开或 Studio 关闭时
都会发送 `robot.stop`；`robotd` 始终是最终安全和电机控制权威。

## 日常使用

以下命令都在 `microduck-studio` 中运行：

| 目的 | 命令 |
|---|---|
| 启动或干净重启全部服务，并验证控制链路 | `./scripts/dev-stack.sh` |
| 默认在后台运行本机 MuJoCo | `./scripts/dev-stack.sh` |
| 显式打开桌面 MuJoCo Viewer | `./scripts/dev-stack.sh --viewer` |
| 启动但不执行仿真移动探针 | `./scripts/dev-stack.sh --skip-control-probe` |
| 最后页面关闭 10 秒后停止后台 MuJoCo | `./scripts/dev-stack.sh --stop-on-browser-close` |
| 启动全容器 CPU 渲染链路 | `./scripts/dev-stack.sh --sim-mode docker --gpu none` |
| 使用 Linux DRI/EGL GPU 透传 | `./scripts/dev-stack.sh --sim-mode docker --gpu dri` |
| 使用 Linux NVIDIA/EGL GPU 透传 | `./scripts/dev-stack.sh --sim-mode docker --gpu nvidia` |
| 联合检查 Studio、`robotd` 和 MuJoCo | `./scripts/dev-stack.sh status` |
| 在当前终端打开实时监控 | `./scripts/dev-stack.sh monitor` |
| 仅停止该开发链路 | `./scripts/dev-stack.sh stop` |

状态卡中的 `robotd` 与 MuJoCo 按钮会随连接状态显示“启动”或“重启”。按钮通过启动器创建的
受限宿主机管理器执行固定操作，不接受任意命令；重启 MuJoCo 时会等待端口恢复并连带重启
robotd。网页服务本身停止时按钮不可用，仍需执行 `./scripts/dev-stack.sh`。

只有显式使用 `--viewer` 时才会打开桌面窗口；关闭该窗口会停止仿真器，可以使用状态卡中的
“启动”按钮恢复。默认后台模式仍使用同一份本机权威世界和离屏渲染。

使用 `--stop-on-browser-close` 后，最后一个场景 WebSocket 持续断开 10 秒便只停止 MuJoCo；
宽限期内刷新或重新连接会取消退出。未指定该参数时，后台 MuJoCo 会一直运行，直到执行
`dev-stack.sh stop`。`--headless` 仍作为默认行为的兼容显式写法保留。

### 如何选择渲染模式

本机 macOS 开发时，请使用默认命令；这是没有 Linux GPU 主机时唯一面向流畅本地演示的模式：

| 场景 | 命令 | 渲染器与预期效果 |
|---|---|---|
| macOS 本地开发（推荐） | `./scripts/dev-stack.sh` | macOS 原生离屏 OpenGL；权威 MuJoCo 世界在后台运行，桌面 Viewer 不会打开。 |
| 检查原生 Viewer | `./scripts/dev-stack.sh --viewer` | 对同一仿真服务打开桌面 Viewer；关闭窗口会停止 MuJoCo。 |
| macOS Docker Desktop 或纯 CPU CI | `./scripts/dev-stack.sh --sim-mode docker --gpu none` | Docker 内的 OSMesa 软件渲染。物理和场景状态仍来自权威世界，但视频流可能较慢。 |
| 配有集显/AMD/Intel GPU 的 Linux 主机 | `./scripts/dev-stack.sh --sim-mode docker --gpu dri` | 将 `/dev/dri` 映射到 MuJoCo 容器并使用 EGL。 |
| 已安装 NVIDIA Container Toolkit 的 Linux 主机 | `./scripts/dev-stack.sh --sim-mode docker --gpu nvidia` | 请求 `gpus: all` 并使用 EGL。 |

`dri` 是 Linux 的 Direct Rendering Infrastructure（直接渲染基础设施）：它通过主机 GPU
设备文件提供访问，而不是另一套 GPU API。macOS Docker Desktop 不支持这种透传。GPU 选项必须
显式写在命令行中，因此可从 Shell 历史清楚地看到使用了哪条硬件路径。`--gpu` 仅可与
`--sim-mode docker` 同用；`--viewer` 和 `--stop-on-browser-close` 属于 native 模式，后者还要求
以后台/headless 方式运行。

### 网页工作台说明

页面包含三个实时区域，它们的数据权威各不相同：

| 区域 | 数据来源 | 可执行操作 |
|---|---|---|
| **MuJoCo 场景** | `duck-body` 从权威 `MjModel` 与 `MjData` 快照渲染出的缓存 JPEG/PNG 帧 | 拖动旋转、滚轮或触控板缩放、双击复位。操作的是权威相机，不是浏览器端重建的姿态。 |
| **ROBOTD TELEMETRY** | Studio 经持久本地 socket 连接读取 `robotd` monitor 协议 | 查看策略、命令、IMU、里程计、关节目标/偏差、机器人缩略图和循环频率。这是 robotd 遥测的 Web 呈现，不是另一套控制循环。 |
| **控制与服务卡片** | `robotd` JSON-RPC 与启动器安装的固定操作服务管理器 | 发送移动意图、启用/停止技能；当启动器正在运行时，可启动/重启 `robotd` 或 MuJoCo。 |

使用页面顶部的语言切换选择中文或英文。它只改变界面文字，不会改变服务、策略或数值单位。
场景卡片还可以选择画质档位：

| 档位 | 最大画面尺寸 | 编码 | 适用情况 |
|---|---:|---|---|
| 流畅 | 960×540 | JPEG，质量 82 | 带宽和延迟要求最低。 |
| 清晰（默认） | 1920×1080 | JPEG，质量 95 | 常规桌面使用。 |
| 无损 | 1920×1080 | PNG | 适合静态检查，帧率可能明显降低。 |

浏览器会按场景 CSS 尺寸乘以屏幕像素倍率请求画面，再受当前档位的上限约束，从而避免高密度屏幕
上被低分辨率视频放大后的模糊感。场景内容和仿真时间来自同一个 MuJoCo 权威世界；不同操作系统、
GL 驱动或 GPU 型号之间不承诺逐像素完全一致。

## `robotctl monitor`

推荐命令会直接在当前终端打开实时可视化监控：

```bash
./scripts/dev-stack.sh monitor
```

等价的 Compose 直接命令为：

```bash
docker compose run --rm --no-deps --build robotctl monitor
```

两种方式都会启动一个一次性的 `robotctl` 工具容器，并连接已有的运行时 socket；它们不会
进入 Docker Shell 或正在运行的 `robotd` 容器。推荐使用脚本，因为它会先确认 `robotd`
正在运行。

| 按键 | 动作 |
|---|---|
| `q`、`Esc` 或 `Ctrl-C` | 退出 |
| `[` / `]` 或 `Left` / `Right` | 旋转三维机器人视角 |
| `d` | 显示或隐藏三维机器人视图 |

三维视图要求终端至少 110 列宽；较窄的终端仍可显示实时状态和关节表格。

## 三个项目如何协作

该工作区包含三个独立 Git 仓库，各自保持单向、清晰的职责边界：

```text
浏览器
   │ HTTP / JSON API
   ▼
Microduck Studio
   │ Unix socket 上的 JSON-RPC / NDJSON
   ▼
robotd --sim ◀──────── policy.onnx + manifest ─────── microduck_rl 导出
   │
   │ TCP / NDJSON :7801
   ▼
duck-body / MuJoCo ────────────────────────────────── microduck_rl
```

- **microduck** 负责 `robotd`、硬件 I/O、安全、策略加载和电机控制权。
- **microduck_rl** 负责 MuJoCo 模型、环境、奖励、训练和 ONNX 导出。
- **microduck-studio** 负责浏览器体验、状态聚合和经过白名单限制的本地编排。

运行时和训练项目都不依赖 Studio；Studio 只使用它们公开的协议和工具。浏览器场景由
`duck-body` 在世界锁内快速复制权威 `MjData`，然后在锁外完成渲染和 JPEG 编码；Studio
只长轮询缓存帧并转发给浏览器。因此动态物体、接触和其他场景元素都来自实际物理世界，
不再是根据遥测重建的姿态镜像。
在浏览器场景中拖动可旋转权威 MuJoCo 相机，使用鼠标滚轮或触控板可缩放，双击可恢复
默认视角。

### `robotd --sim` 的作用

`robotd --sim` 是一种启动模式，不是独立的运行环境。它会运行完整的 `robotd`，只是用远程
仿真适配器替代真实电机和传感器 I/O：

- 从 `microduck_rl` 的 `duck-body` 服务读取关节与传感器状态。
- 通过 TCP 把控制目标发送回 MuJoCo。
- 控制循环、策略推理、安全检查和 JSON-RPC 接口保持不变。
- Studio 和 `robotctl` 因而可以使用与真机相同的控制接口操作仿真机器人。

该后端不会启动 Viewer、执行训练或绕过 `robotd` 的安全逻辑。Docker 为一键工作流提供
进程和依赖隔离，与 `--sim` 启动模式是两个不同概念。

## 容器和进程

### Compose 布局

项目使用的容器定义全部保存在本仓库，并按组件隔离：

```text
docker/
├── microduck/       # robotd 与 robotctl 运行镜像
├── microduck-rl/    # 无窗口权威 MuJoCo 渲染镜像
└── studio/          # Studio Web 与画面代理镜像
compose.yaml             # 基础服务与 CPU 渲染
compose.gpu-dri.yaml     # Linux /dev/dri + EGL 覆盖配置
compose.gpu-nvidia.yaml  # Linux NVIDIA + EGL 覆盖配置
```

不带参数时始终使用 macOS 原生权威渲染器，但在后台运行且不打开 Viewer；需要桌面 Viewer
时显式传入 `--viewer`。Docker/GPU
模式只能通过命令行参数选择，确保当前硬件模式清楚地留在 Shell 历史中。
`--sim-mode docker` 会把 `duck-body` 也放入 Compose。macOS Docker Desktop 不支持
Linux GPU 透传，因此其
OSMesa 渲染能保持场景一致，但速度较慢；流畅演示请使用 native 模式。Linux 主机上，
必须显式传入 `--gpu dri` 才会映射 `/dev/dri`，或传入 `--gpu nvidia` 申请 `gpus: all`；
两者使用相同的 EGL
画面协议和网页界面。

浏览器默认使用**清晰**档，并根据实际 CSS 尺寸乘以屏幕像素倍率请求画面。**流畅**档上限为
`960x540`、JPEG 质量 82；**清晰**档上限为 `1920x1080`、JPEG 质量 95；**无损**档上限为
`1920x1080`、PNG。启动阶段的回退画面为 `1280x720`、24 FPS、JPEG 质量 95，可通过
`MICRODUCK_RENDER_WIDTH`、`MICRODUCK_RENDER_HEIGHT`、`MICRODUCK_RENDER_FPS` 与
`MICRODUCK_RENDER_QUALITY` 覆盖；`MICRODUCK_MUJOCO_GL` 可显式指定 MuJoCo GL 后端。

### 诊断命令

```bash
docker compose ps
docker compose logs -f studio robotd
docker compose run --rm --no-deps robotctl health
```

最后一条命令会运行临时工具容器，不会打开 Docker Shell。

### 常见启动和显示问题

| 现象 | 检查与恢复方式 |
|---|---|
| 场景一直显示“等待 MuJoCo 画面” | 执行 `./scripts/dev-stack.sh status`，再检查 `.studio-runtime/dev-stack/mujoco.log`。Studio 在线时可使用 MuJoCo 卡片的启动/重启；网页无法打开时重新执行 `./scripts/dev-stack.sh`。 |
| 控制操作没有让仿真机器人移动 | 确认三个状态卡片都已连接，点击**启用 RL**，然后不要使用 `--skip-control-probe`，重新执行默认启动命令。只有完整控制链路确实移动机器人后，启动器才会报告 `control probe passed`。 |
| Docker 模式下场景很卡 | macOS 请使用默认 native 模式；Docker 内的 OSMesa 是 CPU 渲染。在支持的 Linux 主机上使用显式 `dri` 或 `nvidia` GPU 模式。优先切换为**流畅**档，而不是降低权威物理频率。 |
| 意外弹出了 MuJoCo 桌面窗口 | 仅传入 `--viewer` 才会打开 Viewer。请停止后使用 `./scripts/dev-stack.sh` 重启，它默认在后台运行。 |
| 启动/重启按钮不可用 | 这些按钮只会在 `dev-stack.sh` 安装本地白名单服务管理器后启用；它们不能启动 Studio Web 服务本身，此时应在终端重新启动整套服务。 |

### 分别运行组件

<details>
<summary><strong>仅运行 MuJoCo Viewer</strong></summary>

如果完整链路已占用 7801 端口，请先停止它，然后从同级 RL 仓库启动仿真器身体：

```bash
./scripts/dev-stack.sh stop
cd ../microduck_rl
uv run mjpython -m mjlab_microduck.sim.body_server --keyframe HOME --port 7801 --render
```

关闭 Viewer 或按 `Ctrl-C` 即可停止。该模式会提供仿真器 TCP 端点，但不会启动 `robotd`
或 Studio。

</details>

<details>
<summary><strong>仅运行 Studio</strong></summary>

```bash
uv sync --extra dev
cp .env.example .env
uv run microduck-studio
```

这只会启动 Web 服务。默认机器人 socket 为 `/run/robotd.sock`；Compose 链路则通过命名
运行时卷共享该 socket。8090 端口可以避开通常使用 8080 的 `microduck` 服务。

</details>

## 页面无法控制机器人时

1. 执行 `./scripts/dev-stack.sh status`；Studio、`robotd` 和 MuJoCo 必须全部在线/健康。
2. 确认 `robotd` 和仿真器卡片都已连接，然后点击 **启用 RL**。
3. 检查 `docker compose logs -f studio robotd` 和
   `.studio-runtime/dev-stack/mujoco.log`，查找断连或策略拒绝信息。
4. 重新执行 `./scripts/dev-stack.sh`。它会停止上次启动所属的进程，并在报告就绪前重新
   执行端到端控制探测。

## 训练冒烟测试

训练任务默认关闭。在宿主机上直接运行 Studio 时，可以这样启用：

```bash
MICRODUCK_STUDIO_ENABLE_JOBS=true uv run microduck-studio
```

Studio 只开放文档规定的 64 环境、5 次迭代冒烟测试。它使用 `shell=False` 构造白名单
`uv run train ...` 参数列表；任意 Shell 命令和长时间训练任务都不会开放。

## 开发

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## 安全

Studio v0.1 没有身份验证。除非处于可信局域网，否则请绑定到 `127.0.0.1`。Studio 只发送
意图；`robotd` 始终是唯一的安全和电机控制权威。

## 许可证

[MIT](LICENSE)
