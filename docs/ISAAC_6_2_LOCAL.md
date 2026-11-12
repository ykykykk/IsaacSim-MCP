# 本机 Isaac Sim 6.2 集成

> 下文记录 0.6.0 本机版迁移历史。当前 0.7.0 实现、提供者版本、工具集与限制见 [工作流指南](WORKFLOW_6_2.md)，历史检查不覆盖本轮新逻辑。

2026-11-12，本地分支 `codex/isaac-6.2-mpm`，版本 `0.6.0+bauma.20261112`。
基于 `https://github.com/Tim0320/IsaacSim-MCP` 的
`repair/ciie-p0-20261021` / `4bb95d8`；不将本机修改冒充上游发布。

## 安装边界

- 源码与独立 `.venv`：`F:/Resources/Projects/Software/IsaacSim-MCP`。
- 宿主：`F:/isaac-sim/6.2.0`；实际构建以 `get_capabilities` 为准。
- `extsUser/isaac.sim.mcp_extension` 联接到本库同名扩展目录。
- Full 共用 `F:/Documents/Kit/apps/Isaac-Sim Full/user.toml` 使用
  `${app}/../extsUser`，不再固定搜索 6.1 源码；旧 6.1 的自身联接仍保留。
- 本机启动器 / Codex 配置：legacy profile，TCP `127.0.0.1:8876`，stdio。
- 6.2 状态文件：`%LOCALAPPDATA%/IsaacSim-MCP/6.2/runtime-8876.json`。
- 官方文档 MCP 仍独立运行于 9904；不替换它。旧 6.1 / 6.2 tools 副本保留。
- 修复 V6 `get_physics_params` 到已有 physics runtime 的缺失委托；不复制另一套物理实现。

## MPM 工具

粒子实现仍由 `sany.granular_mpm` 拥有；本库只负责结构化命令。

| 工具 | 行为 |
|---|---|
| `get_mpm_status` | 读取 stage、timeline、构建状态和实际物料，不下载粒子数组 |
| `get_mpm_config` | 读取已写入与补默认值后的配置，以及原始字符串 SHA-256 |
| `update_mpm_config` | 默认 preview；显式关闭 preview 才写 Session Layer |
| `request_mpm_rebuild` | 默认 preview；显式关闭才排队替换物料，不等于构建完成 |

修改 / 重建要求 stage 身份与配置 hash 匹配、时间线停止、构建器空闲。
不自动启用插件，不播放，不保存磁盘，不隐式重建。
Session 修改不会立刻改变已构建物料；保存到拥有层仍需另行明确操作。
重建使用插件的 `request_rebuild(..., author=False)`，避免延迟构建把配置写回当前拥有层。
超时后先读状态，不能盲目重发。写入失败保留具体原因；构建完成由后续状态决定。

## 运行诊断

Capabilities 返回实际宿主 PID 与当前 `/log/file`。健康探针和 capabilities
均缓存该端点身份；supervisor 将其写入版本 / 端口隔离的状态文件。
诊断优先读取已绑定端点的日志。目录扫描到的文件只作参考，不能单凭旧日志
宣称当前宿主崩溃。端口仍在但未回应标记 `busy_or_unresponsive`，不假定忙或已死。
本机扫描根限制到 Full/6.2；不会把 Full/6.1 日志当当前实例证据。

## 回退与验证边界

关闭宿主后，将扩展联接、Codex / Bauma MCP command 与 `ISAACSIM_MCP_REPO`
改回 `F:/isaac-sim/6.2.0/tools/Tim0320-IsaacSim-MCP`，重启 Codex 即可回退 MCP。
粒子插件的 author 参数默认仍为 True，旧调用行为不变。
源码变更不是仿真验证；本次仅进行安装所需的工具发现、扩展加载及只读连接检查，
不打开工程、不播放、不写入配置、不构建物料，不运行测试 / lint / 性能基准。

2026-11-12 空宿主检查完成：实际 `6.2.0-rc.14` / PhysX，扩展 Python
版本 `0.6.0+bauma.20261112`，134 工具；`get_mpm_status` 返回 stopped / not_built，
`get_runtime_status` 返回 responsive / endpoint_bound=true；保存到源扩展也已加载。
初次检查发现 Full 共用配置优先加载 6.1 MCP，修正该配置后完成上述检查。
证据在本库 `logs/install-host-final-readonly-20261112.json`（本机日志不入 Git）。
未执行配置写入 / 物料重建；检查进程已关闭，不保留隐藏宿主。
