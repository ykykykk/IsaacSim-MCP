# 0.7.0：面向复杂 USD 与 MPM 的工作流

本轮代码目标：Windows / Isaac Sim 6.2。2026-11-12 已完成 MCP 定向离线、lint 与隔离宿主 USD 工作流验收，见[验收记录](development/WORKFLOW_6_2_VALIDATION.md)。未验收外部插件、物理仿真或性能。
此前 0.6.0 本机版在 6.2.0-rc.14 的空宿主只读检查，不代表本版新增编辑/构建/保存已经运行验证。

此前安装更新的基本检查：editable 包版本为 0.7.0，MCP 客户端可导入并注册本机所选领域的 85 个工具，包含 4 个新增工作流/枚举工具。未连接 Isaac；这不是宿主功能验证。

## 安装与配置

通用默认仍为 loopback / 8766 / legacy / all domains。本机使用 8876，写在不入库的
`config.local.json` 及 Full 的 `user.toml`；不要复制本机盘符作为他人的默认值。

1. 安装完整 Isaac Sim 6.2 与本仓库独立 Python 环境，按已有安装指南安装本包。
2. 从 `config.example.json` 复制 `config.local.json`，填入自己的 `isaac_root` 和可用端口。
3. 通过 `scripts/run_isaac_sim.ps1` 启动宿主，通过 `scripts/run_mcp_server.ps1` 启动 MCP。
   启动器把解析后的端口显式交给 Kit；不要让服务端和宿主分别猜端口。
4. 使用自己的官方 Isaac 启动入口时，在对应 Kit 配置中显式配置相同端口与扩展目录。
5. MCP 客户端也可直接运行 `.venv/Scripts/python.exe -m isaac_mcp.server`。

优先级：显式启动参数 > 环境变量 > `ISAAC_MCP_CONFIG` 指定文件（或仓库 `config.local.json`）> 通用默认。
`python -m isaac_mcp.config` 只显示有效配置与来源，不启动 Isaac。
`.env.example` 仍只是参考，不会自动加载。`config.local.json` 不提交 Git。

MPM 可选插件需要 provider API 2（本轮 `sany.granular_mpm` 0.3.1）；保存可选插件需要
provider API 1（本轮 `bauma.save_to_source` 1.1.0）。只安装 MCP 不会自动获得这两个外部插件。
没有相应提供者时返回明确不可用，不自动启用/安装插件，不阻碍其他领域工具。
插件升级前关闭宿主，完成后重开；本轮不使用热重载。不要跨版本复用旧扩展加载路径。

## 工具集

名称兼容 profile 与领域过滤正交：

```json
{"tool_profile":"legacy", "tool_domains":"core,scene,physics,mpm"}
```

领域：core（诊断、任务、产物、模拟控制）、scene（USD、物体、材质、灯光、资产、图、保存）、
physics、robotics（机器人、控制器、运动、传感器、ROS）、mpm、sdg（Replicator/人物）。
core 始终保留。`all` 恢复完整工具集；legacy/consolidated 的原名称合并语义不变。
列表在 MCP 启动时固定；修改配置后重新连接客户端。工具数以 source-derived inventory 为准。

## 身份、支持与证据

`get_capabilities.runtime` 返回 instance_id、stage_id、root_identifier、edit_target、实际扩展目录、
Python 模块路径、代码版本与 provider_capabilities。source_revision 未提供安装元数据时为 unknown。
PID 和日志仍与端点绑定；重新打开同一 USD 也产生新的 Stage 身份。
入队写请求绑定 Stage 身份，写命令串行执行；切场景后拒绝尚未执行的旧写请求。

PhysX 的旧 6.0.1 验证记录保留在 evidence_scope/evidence_version。
6.2 返回当前 runtime_version 和 unverified，不能因复用适配器就冒称当前版本已经验收。
implemented/supported 表示实现路径，不代替版本限定的验证结果。

## USD 批处理与撤销

1. `apply_stage_batch(operations, preview=true)` 返回 plan_id。
2. 原样提交 operations，并使用该 plan_id、preview=false。
3. 相关层、Stage/编辑目标或加载规则改变则拒绝过期计划。
4. 成功返回 transaction_id，可用 `undo_stage_transaction` 先预览、再显式撤销。

legacy 不带 plan_id 的调用继续可用；新工作流应总是使用计划。
批处理对真实写入层做有界内存快照；恢复失败返回 ROLLBACK_FAILED，不标记全部恢复。
撤销限于同一 Stage、未再改写/保存的相关内容，10 分钟、最多 8 条、128 MiB 保留预算。
层级批处理快照上限 128 MiB；超过时拒绝，不降级为不带恢复的写操作。
MPM 参数编辑使用属性级快照，不复制 Session 中的粒子几何。
内存恢复不保证恢复磁盘、求解器或已经释放的物料。
`get_typed_attribute(..., include_source=true)` 可返回属性意见层与路径；任意属性的单位不猜测。

## MPM 配置与构建

1. `list_mpm_configs` 发现已加载 active prim 上的配置，不自动加载 payload。
2. `get_mpm_config` 返回 authored/effective、各意见层及磁盘配置、runtime_config、字段差异、requires_save/requires_rebuild。
3. `update_mpm_config` 保留 stage/hash 检查与默认 preview；实际修改只写 Session，不构建/播放/保存。
4. `request_mpm_rebuild(..., preview=false)` 返回 mpm-* job_id；使用现有 get_job_status/list_jobs/cancel_job 查询。

构建阶段包括验证/准备、碰撞准备、释放旧物料、分配粒子与求解器、绑定显示及运行对象。
每阶段在 Kit 更新间调度；实际同步分配期间可能不响应请求，不伪装实时进度或百分比。
queued/running/cancel_requested 与终态 succeeded/failed/cancelled/interrupted 区分。
取消仅在安全点兑现；分配/绑定期间不接受取消。不强杀 Kit，也不复制两套大型粒子存储。
旧物料释放后失败可导致 runtime_available=false；不会自动重建旧配置。

`get_runtime_status.mpm_jobs` 读取有界本地任务日志，在主线程忙时也可报告最后已知阶段。
该字段明确标记 last_known_only、更新时间与 endpoint_bound；不是实时读数。
宿主重启后旧未完成任务标记 interrupted，不自动重放。
日志默认 `%LOCALAPPDATA%/IsaacSim-MCP/6.2/mpm-<port>.json`，可用 `ISAAC_MCP_JOB_STATE_FILE` 显式设置。

## 精确保存到源

`preview_source_commit` 接收查询返回的 expected_context、prim_path、明确的 attributes 列表。
有多个拥有层候选时必须指定 target_layer；影响其他已加载实例时需显式 allow_shared。
`commit_source_changes(plan_id, save=true)` 执行一次保存；重复请求读取收据，不重复写盘。
save=false 仅改变内存，目标层仍需用户后续保存；它不是已完成磁盘提交。

首轮范围刻意明确：已有参数属性的 Session 默认值 → 一个已有拥有层文件。
不迁移整层/子树，不支持动画时间样本、连接参数、实例代理或生成粒子数组/位姿。
属性事务只保存选定值，不复制大粒子 Session；单次最多 64 个参数、参数指纹材料限 1 MiB。
拥有层已 dirty 时拒绝，以免 Save 顺带保存其他未授权改动。
匿名 Session 的相对 asset path 没有明确文件锚点时拒绝，不能猜测资产位置。
共享影响只覆盖当前已加载 Stage，其他工程未知。

源文件保存成功后，只清除本次选定的 Session 默认值。无关覆盖、属性元数据及场景布置保留。
磁盘尝试失败可能返回 disk_state=unknown；保存成功但清理失败返回 partial/saved=true。
返回错误和具体恢复结果，先检查状态再制定补救，不盲重发。不生成 before USD 备份。
`save_stage_as` 仍只导出根层，不是 Session 打包或整工程备份。

## 回退与执行边界

本地分别维护 MCP、MPM、保存插件三个 Git 提交。回退时关闭宿主并回到匹配组合，再重连 Codex。
此版本未替用户开启播放、重建、保存工程、执行验收或发布 GitHub。
HTTP 仍没有身份认证；本轮不开放网络端口，不推荐无认证 Funnel。
需要运行验收时按设计文档的最小场景逐项执行，不自动扩大到全量测试或正式 Bauma 工程。
记录与回放是设计中的后续独立阶段，不属于本轮 A—D 完成条件。
