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

## 运行

如需在 macOS 上启动完整开发链路——MuJoCo Viewer、加载内置策略且支持仿真的 `robotd`，
以及 Studio——请先启动 Docker Desktop，然后运行：

```bash
cd ~/microduck-dev/microduck-studio
./scripts/dev-stack.sh
```

启动器不会切换任何兄弟仓库的分支。它会在隔离的本地状态中构建上游仿真运行时，按依赖顺序
启动所有服务，并在最后执行端到端控制探测。只有 HTTP 移动请求经过 `robotd` 和策略后确实
让 MuJoCo 模型产生可测位移，脚本才会报告成功；仅 Web 页面可访问不算启动完成。

使用 `./scripts/dev-stack.sh status` 检查状态，使用 `./scripts/dev-stack.sh stop` 仅停止该
启动器创建的服务。

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
完整链路启动器会自动创建并配置 Docker 到宿主机的 socket 转发。

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
