# Microduck Studio

[English](README.md) | 简体中文

Microduck Studio 是连接 [`microduck`](../microduck) 和
[`microduck_rl`](../microduck_rl) 的本地开发工具：通过一个浏览器界面集中展示开发状态、
控制仿真机器人，并安全地编排强化学习冒烟测试。

它**不会**重新实现机器人运行时或训练环境。它使用 `robotd` 现有的 JSON-RPC 协议，读取
仿真器身体已有的 TCP 协议，检查两个 Git 仓库，并调用 `microduck_rl` 的正式 CLI 启动训练任务。

## 项目关系

三者不是包含关系，而是三个独立 Git 项目，关系如下：

```text
microduck_rl ──训练、导出 ONNX 策略──▶ microduck
                                          ▲
                                          │ JSON-RPC 控制与状态
                                          │
microduck-studio ──开发、调试、可视化、任务编排
        │
        └──调用 microduck_rl 的训练命令、读取训练结果
```

- `microduck`：机器人运行时。负责 `robotd`、硬件通信、安全控制、加载并执行策略。
- `microduck_rl`：训练项目。负责 MuJoCo 仿真、强化学习环境、奖励函数、训练及 ONNX 导出。
- `microduck-studio`：辅助开发工具。它不属于前两个项目，也不提供核心运行或训练逻辑；
  只是通过现有接口把状态查看、手机控制、训练启动和日志展示集中到 Web 页面。

因此当前目录结构表达的是“同一个开发工作区中的三个独立仓库”：

```text
microduck-dev/          # 仅作为 Codex 工作区，不是 Git 仓库
├── microduck/          # 独立仓库
├── microduck_rl/       # 独立仓库
└── microduck-studio/   # 独立仓库
```

严格来说，Studio 与另外两个项目有“工具集成关系”，但没有代码归属或包含关系。
`microduck` 和 `microduck_rl` 不依赖 Studio，没有 Studio 也能正常开发、训练和运行。

## v0.1 包含的功能

- 支持手机操作的驾驶控件，使用持久 `robotd` 连接，并在松开控件时停止运动。
- 启用、停止、坐下/站立、翻滚和踢球动作。
- 实时显示机器人、仿真器、仓库分支及工作区修改状态。
- 查找 ONNX 文件但不在 Web 进程中加载模型的模型目录。
- 可选择启用的强化学习冒烟测试启动器。它只构造文档规定的 `uv run train ...` 命令，
  不接受任意 shell 输入。
- 在 `.studio-runtime/` 中保存本地任务状态和日志。

## 启动开发链路

### 准备条件

- macOS，且 Docker Desktop 已启动。
- 宿主机已安装 `git`、`curl`、Python 3 和
  [`uv`](https://docs.astral.sh/uv/)。
- `microduck`、`microduck_rl` 和 `microduck-studio` 作为同级目录检出。
- 先在 `microduck_rl` 中执行一次 `uv sync`，准备 RL 环境。

启动器当前使用 `microduck` 的 `upstream/sim-remote-io` 版本提供仿真后端，
并将源码展开到隔离的运行目录。它不会修改或切换当前工作区的分支。

### 一键启动

如需在 macOS 上启动完整开发链路——MuJoCo Viewer、加载内置策略且支持仿真的 `robotd`，
以及 Studio——请先启动 Docker Desktop，然后运行：

```bash
cd ~/microduck-dev/microduck-studio
./scripts/dev-stack.sh
```

启动器不会切换任何兄弟仓库的分支。它会在隔离的本地状态中准备上游仿真运行时，先启动
macOS 原生 MuJoCo Viewer，再通过 Docker Compose 按依赖顺序构建并启动 `robotd` 和 Studio，
最后执行端到端控制探测。只有 HTTP 移动请求经过 `robotd` 和策略后确实让 MuJoCo 模型产生
可测位移，脚本才会报告成功；仅 Web 页面可访问不算启动完成。

使用 `./scripts/dev-stack.sh status` 检查状态，使用 `./scripts/dev-stack.sh stop` 仅停止该
启动器创建的服务。

### 常用命令

以下命令都在 `microduck-studio` 中执行：

| 目的 | 命令 |
|---|---|
| 启动或重启全部服务，并执行控制探测 | `./scripts/dev-stack.sh` |
| 联合检查 Studio、`robotd` 和 MuJoCo | `./scripts/dev-stack.sh status` |
| 在当前终端打开 `robotctl` 实时可视化监控 | `./scripts/dev-stack.sh monitor` |
| 仅停止该开发链路 | `./scripts/dev-stack.sh stop` |

关闭 MuJoCo 窗口会停止该仿真进程，它不会自动重启。需要恢复完整链路时，
再次执行 `./scripts/dev-stack.sh`。

### 打开 `robotctl` 可视化监控

先启动开发链路，然后在同一个 `microduck-studio` 目录中执行启动器命令：

```bash
./scripts/dev-stack.sh monitor
```

如果不经过启动器封装，也可以直接通过 Compose 调用同一个监控程序：

```bash
docker compose run --rm --no-deps --build robotctl monitor
```

两条命令都会把监控界面直接连接到当前终端。它们会启动一个一次性的 `robotctl` 工具容器，
并连接开发链路已有的运行时 socket；它们**不会**打开或进入 Docker Shell。推荐使用启动器
命令，因为它还会先确认 `robotd` 正在运行。

监控快捷键：

| 按键 | 动作 |
|---|---|
| `q`、`Esc` 或 `Ctrl-C` | 退出监控 |
| `[` / `]` 或 `Left` / `Right` | 旋转三维机器人视角 |
| `d` | 显示或隐藏三维机器人视图 |

终端宽度达到 110 列时才会显示三维视图；较窄的终端仍会显示实时状态和关节表格。

### 容器目录

项目使用的容器定义全部放在本仓库，并按组件隔离：

```text
docker/
├── microduck/       # robotd 与 robotctl 运行镜像
├── microduck-rl/    # 可选的 Linux/无窗口 MuJoCo 镜像
└── studio/          # Studio Web 镜像
compose.yaml         # robotd、Studio、robotctl 与无窗口 MuJoCo 服务
```

启动器统一调用 `docker compose up`、`down` 和 `run`，不使用 `docker run`
分别启动容器。Docker Desktop 无法直接显示这套 macOS 原生 GUI，因此默认开发
链路中的 Viewer 仍是宿主机进程；`mujoco-headless` Compose profile 用于
Linux/CI，不替代默认的 macOS Viewer。

常用的 Compose 直接命令：

```bash
docker compose ps
docker compose logs -f studio robotd
docker compose run --rm --no-deps robotctl health
```

健康检查命令会启动一个临时工具容器，让 `robotctl` 连接同一个运行时 socket；
它不会进入已运行的 `robotd` 容器。交互式监控请参见
[打开 `robotctl` 可视化监控](#打开-robotctl-可视化监控)。

### 仅启动 MuJoCo Viewer

如果完整链路已占用 7801 端口，请先停止它，然后从同级 RL 仓库直接运行
仿真器身体：

```bash
./scripts/dev-stack.sh stop
cd ../microduck_rl
uv run mjpython -m mjlab_microduck.sim.body_server --keyframe HOME --port 7801
```

关闭 Viewer 窗口或在该终端按 `Ctrl-C` 即可停止。这种模式只显示模型并提供
仿真器 TCP 端点，不会启动 `robotd` 或 Studio。

### 联通检查

启动命令不只是等待端口打开：它会让一条移动指令经过
`Web -> Studio -> robotd -> 策略 -> MuJoCo`，并要求仿真器产生可测位移。
出现 `control probe passed` 表示 Web 控制链路在启动时已经正常。

如果之后点击页面但机器人不动：

1. 执行 `./scripts/dev-stack.sh status`，三行状态都必须在线/健康。
2. 在 Studio 中确认 `robotd` 和仿真器卡片都显示已连接，然后点击 **启用 RL**。
3. 检查 `docker compose logs -f studio robotd` 和
   `.studio-runtime/dev-stack/mujoco.log`，查找断连或策略拒绝信息。
4. 重新执行 `./scripts/dev-stack.sh`。它会停止上一次启动所属的进程，
   启动干净链路，并在报告就绪前重新执行端到端控制探测。

如果只需单独运行 Studio，不启动完整仿真控制链路：

```bash
cd ~/microduck-dev/microduck-studio
uv sync --extra dev
cp .env.example .env
uv run microduck-studio
```

在 Mac 上打开 `http://127.0.0.1:8090`；也可以在同一可信 Wi-Fi 网络中的手机上打开
`http://<mac-lan-ip>:8090`。使用 8090 端口可避免与 `microduck` 的 `mediad` 以及占用
8080 端口的现有演示页面冲突。

当 Studio 与 `robotd` 在同一环境中运行时，默认的 `/run/robotd.sock` 是合适的配置。
在 Compose 开发栈中，Studio 与 `robotd` 通过命名运行时卷共享这个 socket。

## 训练任务

训练启动功能默认关闭，需要明确启用：

```bash
MICRODUCK_STUDIO_ENABLE_JOBS=true uv run microduck-studio
```

首个产品化操作是使用 64 个环境、运行 5 次迭代的冒烟测试，与
`microduck_rl/AGENTS.md` 的要求一致。当前版本不会开放长时间训练任务。

## 安全

Studio v0.1 没有身份验证。除非在可信局域网中使用，否则应绑定到 `127.0.0.1`。
按住控制器时，运动指令会作为连续通知反复发送；松开指针、页面隐藏、连接断开以及
`robotd` 的 deadman 机制都会停止运动。

## 许可证

Microduck Studio 使用 [MIT 许可证](LICENSE)。
