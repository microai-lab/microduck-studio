# Product roadmap

## v0.1 — local development console

- `microduck` / `microduck_rl` 仓库、分支和工作区状态
- `robotd` JSON-RPC 健康检查、手机遥控和技能触发
- MuJoCo simulator body TCP 状态
- ONNX 模型目录与受限 smoke training
- 本地任务日志

## v0.2 — reproducible runtime profiles

- 一键启动和停止 `robotd`、MuJoCo bridge 与 Studio
- 原生 Linux、macOS 开发机、Docker 三套显式 profile
- 启动前依赖诊断和端口/Socket 冲突提示

## v0.3 — training workbench

- 实验参数模板、种子与 checkpoint 对比
- TensorBoard / Weights & Biases 链接聚合
- 模型导出、评估和回归门禁

## v0.4 — hardware-assisted validation

- 真实机器人连接前的仿真回放
- 急停、限速、控制租约与审计记录
- 仿真/实机观测差异报告

Studio 不成为第三套控制或训练实现。它只编排两个上游项目提供的稳定接口；
缺少接口时，先在上游定义接口，再从 Studio 调用。
