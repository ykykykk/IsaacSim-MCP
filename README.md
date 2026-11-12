# IsaacSim-MCP

通过 MCP，让 AI 客户端控制 NVIDIA Isaac Sim 的场景、机器人、传感器与仿真工作流。

**当前版本：0.7.0 · 主要维护环境：Windows / Isaac Sim 6.2**

[快速开始](#快速开始) · [功能概览](#功能概览) · [客户端配置](#客户端配置) · [最新验收报告](docs/development/MCP_6_2_ACCEPTANCE.md) · [文档目录](docs/README.md)

## 验收状态

2026-11-12，在 **Isaac Sim 6.2.0-rc.14 / Windows / PhysX** 隔离宿主中完成约定范围验收：

- **706 项离线测试通过，0 失败**；53 项按实时宿主或 Unix 启动器标记排除。
- `legacy` 模式 **136 / 138** 个工具已有成功实机覆盖；`full` 模式 **158 / 160** 个工具名已有成功实机覆盖。
- **USD Search、Beaver3D 未调用、未验收**，不计入通过项。
- 已修复并复测机器人混合 GPU 场景、Kaya 控制、人物 schema、MPM 任务桥接，以及 ROS 相机和雷达停止后无法重播的问题。
- MPM 和保存插件仅作为外部提供者参与隔离测试，未修改其源码或正式项目资产。

“实机覆盖”包含原生 MCP 调用，以及扩展命令执行、操作后读回与离线路由契约的组合证据；不代表所有参数组合或其他版本都已验证。具体范围见[验收报告](docs/development/MCP_6_2_ACCEPTANCE.md)和[逐项结果](docs/development/MCP_6_2_ACCEPTANCE_RESULTS.json)。

## 目录

- [功能概览](#功能概览)
- [架构](#架构)
- [快速开始](#快速开始)
- [客户端配置](#客户端配置)
- [工具模式与领域过滤](#工具模式与领域过滤)
- [启动与故障恢复](#启动与故障恢复)
- [HTTP 与远程访问](#http-与远程访问)
- [支持范围](#支持范围)
- [安全与操作边界](#安全与操作边界)
- [常见问题](#常见问题)
- [开发与文档](#开发与文档)
- [许可证与来源](#许可证与来源)

## 功能概览

| 领域 | 能力 |
|---|---|
| USD 场景 | 创建、查询、变换、组合、引用、语义标注、类型化属性、多层批处理、保存与受控撤销 |
| 机器人 | 关节状态与驱动、运动规划、夹爪、移动底盘；处理场景或机器人替换后的运行时重建 |
| 相机与雷达 | RGB、深度、分割等相机输出，RTX LiDAR 点云；原生 MCP 图片和大型数据传输 |
| 物理与材质 | PhysX 场景、刚体、碰撞体、碰撞组、关节、PBR 材质和物理材质 |
| 图与 ROS 2 | Action Graph、ScriptNode，以及 Clock、TF、JointState、相机和雷达发布器 |
| 合成数据与人物 | Replicator SDG 任务、NavMesh、人物生成、移动、注视、空闲及行为控制 |
| 可选 MPM 桥接 | 配置发现与对比、Session 参数修改、版本校验、异步构建与任务状态 |
| 可选源文件保存桥接 | 预览并提交选定的 Session 默认值到一个源文件，保留无关覆盖 |
| 诊断与治理 | 命令 ID、幂等控制、任务取消、操作后读回、回滚、脱敏日志和崩溃恢复状态 |

**本仓库只维护 MCP。** MPM 求解器和保存插件是独立项目，不随本仓库安装，也不会被工具自动安装或启用。缺少提供者时返回明确错误，不影响其他领域。

[工具清单](docs/reference/TOOL_INVENTORY.md)由源码自动生成；实际可用工具以当前 `tools/list` 和 `get_capabilities` 为准。

## 架构

```text
AI 客户端 → Python MCP 服务 → TCP → Isaac Sim 扩展 → 处理器 → 适配器 → Isaac Sim
```

```mermaid
flowchart LR
    A[AI / MCP 客户端] -->|stdio 或 Streamable HTTP| B[Python MCP 服务]
    B -->|本地 TCP| C[Isaac Sim 扩展]
    C --> D[命令处理器]
    D --> E[V5 / V6 适配器]
    E --> F[Isaac Sim / USD / PhysX]
```

MCP 服务与 Isaac Sim 是独立进程：客户端启动 MCP 服务，Isaac Sim 内的扩展执行场景操作。详细分工见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 快速开始

准备完整的 Isaac Sim 6.2 安装，以及 Python 3.10 或更新版本。MCP 服务使用独立 Python 环境；扩展使用 Isaac Sim 自带环境。

### 1. 安装 MCP 服务

```powershell
git clone https://github.com/ykykykk/IsaacSim-MCP.git
cd IsaacSim-MCP
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

### 2. 配置本机路径与端口

```powershell
Copy-Item config.example.json config.local.json
```

编辑 `config.local.json`，例如：

```json
{
  "isaac_root": "F:/isaac-sim/6.2.0",
  "host": "127.0.0.1",
  "port": 8766,
  "tool_profile": "legacy",
  "tool_domains": "all"
}
```

安装路径是示例，请按本机实际位置填写。端口必须与 Isaac Sim 扩展一致；已有配置使用其他端口时，不必改回 8766。`config.local.json` 不提交 Git。

配置优先级：**显式启动参数 > 环境变量 > 配置文件 > 通用默认值**。可用 `ISAAC_MCP_CONFIG` 指定另一个配置文件；`.env.example` 仅供参考，不会自动加载。

### 3. 启动 Isaac Sim

```powershell
.\scripts\run_isaac_sim.ps1
```

启动器根据配置加载本仓库扩展，并显式传递连接端口。需要进程监督与异常恢复时，改用：

```powershell
.\scripts\run_isaac_sim_supervised.ps1
```

### 4. 连接客户端

按下一节配置 MCP 客户端。连接后先调用 `get_capabilities`，再调用 `get_scene_info`，确认宿主版本、扩展来源及当前场景，再执行修改。

详细安装说明见 [Windows 安装指南](docs/getting-started/INSTALLATION_WINDOWS.md)；6.2 配置及工作流契约见 [6.2 工作流指南](docs/WORKFLOW_6_2.md)。历史验收结论以本页链接的最新报告为准。

## 客户端配置

默认使用 **stdio**，不需要 HTTP 或公网入口。支持 `mcpServers` 格式的客户端可参考：

```json
{
  "mcpServers": {
    "isaac-sim-live": {
      "command": "F:\\Resources\\Projects\\Software\\IsaacSim-MCP\\.venv\\Scripts\\python.exe",
      "args": ["-m", "isaac_mcp.server"],
      "env": {
        "ISAAC_MCP_HOST": "127.0.0.1",
        "ISAAC_MCP_PORT": "8766"
      }
    }
  }
}
```

将 `command` 改为仓库虚拟环境的绝对路径，端口与宿主保持一致。不同客户端的配置文件格式可能不同，但启动命令和参数相同。

| 环境变量 | 默认值 | 用途 |
|---|---|---|
| `ISAACSIM_ROOT` | 由本机配置指定 | Isaac Sim 安装目录 |
| `ISAAC_MCP_CONFIG` | 仓库 `config.local.json` | 配置文件路径 |
| `ISAAC_MCP_HOST` | `127.0.0.1` | Isaac Sim 扩展的 TCP 地址 |
| `ISAAC_MCP_PORT` | `8766` | Isaac Sim 扩展的 TCP 端口 |
| `ISAAC_MCP_TOOL_PROFILE` | `legacy` | 工具名称与接口模式 |
| `ISAAC_MCP_TOOL_DOMAINS` | `all` | 工具领域过滤 |
| `ISAAC_MCP_TRANSPORT` | `stdio` | MCP 传输方式 |

## 工具模式与领域过滤

工具模式控制名称和接口：

- **`legacy`**：默认模式，保留既有工具名称和参数契约。
- **`consolidated`**：使用 `action`、`publisher_type` 等参数合并同类操作，减少客户端工具数量。
- **`full`**：同时暴露两套名称，供迁移和测试使用，不建议长期使用。

领域过滤独立于工具模式：

| 领域 | 内容 |
|---|---|
| `core` | 诊断、任务、产物与仿真控制；始终保留 |
| `scene` | USD、物体、材质、灯光、资产、图与保存 |
| `physics` | 物理配置与构建 |
| `robotics` | 机器人、控制器、运动、传感器与 ROS 2 |
| `mpm` | 可选 MPM 桥接 |
| `sdg` | Replicator 与人物 |

例如只开放场景和物理相关工具：

```powershell
$env:ISAAC_MCP_TOOL_PROFILE = "consolidated"
$env:ISAAC_MCP_TOOL_DOMAINS = "core,scene,physics"
```

修改后重新启动 MCP 服务，并让客户端重新获取工具列表。完整名称对照见[工具模式说明](docs/reference/TOOL_PROFILES.md)。

## 启动与故障恢复

监督启动器沿用本机路径、扩展、端口及物理 GPU 选择策略。默认在 300 秒窗口内最多重启 3 次，采用递增等待；退出码为 `0` 时视为正常关闭，不自动重开。若已存在健康宿主，或端口被无响应进程占用，会拒绝重复启动。

MCP 服务仍由客户端独立启动。`get_runtime_status` 可在 Isaac Sim 不可连接时读取最后已知退出状态、重启次数及脱敏日志摘要：

- `ISAAC_RUNTIME_RECOVERING`：正在恢复，等待后再查询。
- `ISAAC_RUNTIME_CRASHED`：已崩溃，先检查原因。
- `ISAAC_RUNTIME_UNAVAILABLE`：宿主不可用，检查启动器与配置。

**断线后不自动重放写操作。** 恢复连接后先读回状态，确认前一次操作是否生效，再决定下一步。

状态文件默认位于 `%LOCALAPPDATA%\IsaacSim-MCP\6.2\runtime-<port>.json`。可通过 `ISAAC_MCP_RUNTIME_STATE_FILE` 和 `ISAAC_MCP_RUNTIME_LOG_FILE` 指定状态文件及 Kit 日志位置。详情见[运行监督与崩溃恢复](docs/concepts/RUNTIME_SUPERVISION.md)。

## HTTP 与远程访问

本地 stdio 是默认方案。确需 Streamable HTTP 时，在单独的 PowerShell 中启动：

```powershell
$env:ISAAC_MCP_TRANSPORT = "streamable-http"
$env:ISAAC_MCP_HTTP_HOST = "127.0.0.1"
$env:ISAAC_MCP_HTTP_PORT = "8000"
$env:ISAAC_MCP_TOOL_PROFILE = "consolidated"
$env:MCP_ALLOWED_HOSTS = "localhost,127.0.0.1"
.\.venv\Scripts\python.exe -m isaac_mcp.server
```

MCP 地址为 `http://127.0.0.1:8000/mcp`。HTTP 的 8000 端口与扩展 TCP 的 8766 端口用途不同，不能混用。

**现有 HTTP 服务没有身份认证。Host 校验不等于认证，不要直接公开端口或通过无认证隧道暴露控制接口。** 远程部署需要独立配置认证、授权及访问审计，本仓库不自动部署公网服务。

## 支持范围

| 组件 | 当前状态 |
|---|---|
| Isaac Sim 6.2 / Windows | 当前维护目标；最新实机验收构建为 6.2.0-rc.14 |
| PhysX | 当前实机验收后端 |
| Isaac Sim 6.0.1 / Windows | 保留上游历史验证记录，不与 6.2 证据混用 |
| Isaac Sim 5.1.x | 保留旧版适配器，不在本轮验收范围 |
| Newton | 仅使用当前能力矩阵明确支持的功能；未纳入本轮 PhysX 验收 |
| MPM / 保存插件 | 可选外部提供者；本轮验证 MCP 桥接，不代表生产规模性能或求解精度验收 |
| USD Search / Beaver3D | 可选外部服务；本轮未调用、未验收 |
| Isaac Lab MCP | 独立范围，尚未纳入本项目 |

软件包、扩展、响应格式和能力矩阵使用独立版本规则，见[协议版本与迁移](docs/concepts/PROTOCOL_VERSIONING_AND_MIGRATION.md)。

## 安全与操作边界

- `isaac-sim-live` 才是实时场景控制通道；文档查询不能证明场景已经改变。
- 写入须满足时间轴、后端、扩展、对象归属及路径条件；破坏性验收仅限明确指定的临时场景。
- 工具出现在列表中不等于功能通过；验收需要执行结果、操作后读回及清理证据。
- 优先使用具名工具。`execute_script` / `reload_script` 只应执行可信代码，并受执行策略限制。
- 参数修改、构建、播放、内存提交与磁盘保存是不同操作，不互相隐式触发。
- API 密钥不应写入源码、聊天中的 MCP 参数、报告或 Git 提交。
- 本仓库不接管其他插件源码，不自动修改用户正式场景。

## 常见问题

### 无法连接 Isaac Sim

确认宿主已启动、扩展已加载，且客户端和宿主使用相同 TCP 地址与端口。调用 `get_runtime_status` 查看退出或恢复状态。不要把 `ISAAC_MCP_PORT` 填成 HTTP 服务端口。

若崩溃报告程序尚未退出，可能暂时没有退出码；运行时诊断仍可提供最新 Kit 日志的有限摘要。完整日志保留在本机。

### 工具显示正常，调用却返回 `Unknown tool`

客户端缓存的工具列表可能与当前模式不一致。确认 `ISAAC_MCP_TOOL_PROFILE` 和 `ISAAC_MCP_TOOL_DOMAINS`，重启服务并重新连接客户端。

例如 `legacy` 使用 `play_simulation`、`open_gripper`，`consolidated` 使用 `control_timeline`、`control_gripper`。迁移期间可临时使用 `full`，完成后切回所需模式。

### 相机成功返回，但客户端没有显示图片

使用 RGB `capture_camera_output(..., output_type="rgb", return_mode="image")` 或 `capture_image(..., return_mode="image")`。`artifact` 返回受管理的数据句柄，`inline` 返回 JSON 中的 base64，均不等同于原生 MCP `ImageContent`。

若响应已有 `ImageContent`，但界面仍不显示，需检查客户端是否支持图片内容。若收到 `CAMERA_FRAME_NOT_READY`，先检查相机、时间轴与渲染状态，不在单次请求中无限重试。

### 机器人替换后出现无效物理张量或 IK 错误

当前实现会在场景或机器人身份变化后丢弃旧绑定，并重建失效的物理运行时。若仍报错，确认 MCP 服务与扩展来自同一版本，重新启动 Isaac Sim 后读回关节配置。不要用反复播放、暂停或盲目重发写命令代替诊断。

### ROS 2 发布器或可选插件不可用

先查询 `get_ros2_status` 或 `get_capabilities`。ROS 2 需要启用 bridge、core、nodes 扩展；MPM 和源保存需要各自外部提供者。工具不会替用户自动启用插件。

### HTTP 返回 `421 Misdirected Request`

请求的 Host 不在允许列表中。`MCP_ALLOWED_HOSTS` 接受逗号分隔的精确主机名，不接受 `*.example.com` 这类通配符。调整 Host 列表不会为服务增加身份认证。

## 开发与文档

开发依赖使用 `uv sync --dev` 安装。需要主动运行离线检查时：

```powershell
$env:PYTHONUTF8 = "1"
$env:ISAAC_MCP_TOOL_DOMAINS = "all"
$env:ISAAC_MCP_TOOL_PROFILE = "legacy"
uv run pytest -q -m "not live and not unix_launcher"
uv run ruff check .
```

以上为 Windows 离线验收命令。实机测试需另行显式启用，并使用[隔离场景测试框架](docs/development/LIVE_TEST_HARNESS.md)；禁止把历史破坏性测试指向正在编辑的用户场景。

常用文档：

- [最新 6.2 验收报告](docs/development/MCP_6_2_ACCEPTANCE.md)
- [6.2 工作流与安装配置](docs/WORKFLOW_6_2.md)
- [文档目录](docs/README.md)
- [工具清单](docs/reference/TOOL_INVENTORY.md)与[工具模式](docs/reference/TOOL_PROFILES.md)
- [架构](ARCHITECTURE.md)与[信息权威来源](docs/reference/AUTHORITY.md)
- [错误码与恢复规则](docs/reference/ERROR_CODES.md)
- [机器人运行时生命周期](docs/reference/ROBOT_RUNTIME_LIFECYCLE.md)
- [开发代理工作约定](.agents/skills/omniverse-windows-workspace/SKILL.md)

## 许可证与来源

本项目基于 [Tim0320/IsaacSim-MCP](https://github.com/Tim0320/IsaacSim-MCP)，延续 [whats2000/isaacsim-mcp-server](https://github.com/whats2000/isaacsim-mcp-server) 的工作，使用 [MIT 许可证](LICENSE)。分发修改版时请保留许可证、版权声明与上游归属。
