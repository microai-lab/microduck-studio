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

## 快速开始

完整的 macOS 开发链路需要 Docker Desktop、`git`、`curl`、Python 3 和
[`uv`](https://docs.astral.sh/uv/)。

### 1. 下载三个仓库

Studio 不能脱离另外两个项目单独启动完整链路：`microduck` 提供 `robotd` 和策略，
`microduck_rl` 提供 MuJoCo 身体与 Viewer。三个仓库必须位于同一个工作区的同级目录：

```text
microduck-dev/          # 仅作为工作区，不是 Git 仓库
├── microduck/          # robotd、robotctl、策略和运行时协议
├── microduck_rl/       # MuJoCo 身体、Viewer、环境和训练
└── microduck-studio/   # Web 界面和开发链路编排
```

全新安装时，下载当前开发环境使用的三个仓库，并把官方运行时仓库注册为 `upstream`：

```bash
mkdir -p ~/microduck-dev
cd ~/microduck-dev

git clone https://github.com/ttfont/microduck.git
git clone https://github.com/ttfont/microduck_rl.git
git clone https://github.com/microai-lab/microduck-studio.git

git -C microduck remote add upstream https://github.com/pollen-robotics/microduck.git
git -C microduck fetch upstream sim-remote-io
```

下载地址：[microduck](https://github.com/ttfont/microduck)、
[microduck_rl](https://github.com/ttfont/microduck_rl) 和
[microduck-studio](https://github.com/microai-lab/microduck-studio)。前两个是
[官方运行时仓库](https://github.com/pollen-robotics/microduck) 和
[官方 RL 仓库](https://github.com/pollen-robotics/microduck_rl) 的开发分支仓库。

如果仓库已经存在，请不要重复克隆；只需确认目录结构符合上图，并确保
`git -C microduck rev-parse upstream/sim-remote-io` 能够成功执行。

### 2. 准备 RL 环境

macOS 原生 Viewer 从 `microduck_rl` 的虚拟环境运行：

```bash
cd ~/microduck-dev/microduck_rl
uv sync
```

### 3. 启动并验证完整链路

```bash
cd ~/microduck-dev/microduck-studio
./scripts/dev-stack.sh
```

打开 **http://127.0.0.1:8090**。该命令会启动原生 MuJoCo Viewer、支持仿真的 `robotd`
以及 Studio，最后通过移动仿真机器人验证完整控制链路。仅能打开网页不代表已经就绪；请等待：

```text
control probe passed: MuJoCo moved ... m
```

> 启动器不会切换兄弟仓库的工作分支。它会把所需的 `upstream/sim-remote-io` 运行时版本
> 展开到隔离的本地状态目录。

## 主要能力

| Web 控制 | 实时可见性 | 安全编排 |
|---|---|---|
| 适合手机操作的移动、启用/停止、坐下/站起、前滚翻和踢球 | 运行时、仿真器、仓库、策略、任务及连接状态 | Docker Compose 生命周期、端到端控制探测和白名单 RL 冒烟测试 |

运动控制始终使用一个持久 `robotd` 连接。松开控件、隐藏页面、连接断开或 Studio 关闭时
都会发送 `robot.stop`；`robotd` 始终是最终安全和电机控制权威。

## 日常使用

以下命令都在 `microduck-studio` 中运行：

| 目的 | 命令 |
|---|---|
| 启动或干净重启全部服务，并验证控制链路 | `./scripts/dev-stack.sh` |
| 联合检查 Studio、`robotd` 和 MuJoCo | `./scripts/dev-stack.sh status` |
| 在当前终端打开实时监控 | `./scripts/dev-stack.sh monitor` |
| 仅停止该开发链路 | `./scripts/dev-stack.sh stop` |

关闭 MuJoCo 窗口会停止仿真器，而且不会触发自动重启。再次执行启动命令即可恢复完整链路。

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

当前工作区包含三个独立 Git 仓库：

```text
microduck_rl
  MuJoCo 身体 + 训练 + ONNX 导出
       │ TCP/NDJSON :7801               policy.onnx + manifest
       ▼                                      │
microduck 仿真身体 ◀── robotd ────────────────┘
                         ▲
                         │ Unix socket 上的 JSON-RPC/NDJSON
                         │
                    Microduck Studio ◀── 浏览器
```

- **microduck** 负责 `robotd`、硬件 I/O、安全、策略加载和电机控制权。
- **microduck_rl** 负责 MuJoCo 模型、环境、奖励、训练和 ONNX 导出。
- **microduck-studio** 负责浏览器体验、状态聚合和经过白名单限制的本地编排。

运行时和训练项目都不依赖 Studio；Studio 只使用它们公开的协议和工具。

## 容器和进程

项目使用的容器定义全部保存在本仓库，并按组件隔离：

```text
docker/
├── microduck/       # robotd 与 robotctl 运行镜像
├── microduck-rl/    # 可选的 Linux/无窗口 MuJoCo 镜像
└── studio/          # Studio Web 镜像
compose.yaml         # robotd、Studio、robotctl 与无窗口 MuJoCo 服务
```

启动器使用 `docker compose up`、`down` 和 `run`。Docker Desktop 无法直接显示这套
macOS 原生 GUI，因此默认链路中的 MuJoCo Viewer 仍是宿主机进程。`mujoco-headless`
profile 用于 Linux/CI，不替代默认的 macOS Viewer。

常用诊断命令：

```bash
docker compose ps
docker compose logs -f studio robotd
docker compose run --rm --no-deps robotctl health
```

最后一条命令会运行临时工具容器，不会打开 Docker Shell。

<details>
<summary><strong>仅运行 MuJoCo Viewer</strong></summary>

如果完整链路已占用 7801 端口，请先停止它，然后从同级 RL 仓库启动仿真器身体：

```bash
./scripts/dev-stack.sh stop
cd ../microduck_rl
uv run mjpython -m mjlab_microduck.sim.body_server --keyframe HOME --port 7801
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
