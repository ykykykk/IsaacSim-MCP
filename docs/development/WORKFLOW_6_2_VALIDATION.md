# MCP 0.7.0 定向验收记录

日期：2026-11-12（Asia/Shanghai）  
代码基线：`e558499`，本记录随本轮修复提交。  
范围：只验收和修改 IsaacSim-MCP 仓库，不验收、不启用、不修改 MPM 或保存插件。

## 结论

MCP 本轮定向验收通过。覆盖离线契约、Windows 启动器、真实 stdio 客户端和 Isaac 6.2 隔离宿主中的 USD 工作流。
这不是所有工具、机器人、传感器、ROS 2、SDG、粒子求解器或性能的全量验收。

## 修复

1. `get_capabilities` 的可选诊断不再因为日志接口/扩展管理器未就绪而使整条查询失败；明确返回 discovery_errors。测试注入的扩展管理器与运行身份查询使用同一实例。
2. 批量预览的 plan_id/context 原来放在 data 之外，被响应标准化丢弃。真实 TCP 调用复现后改入 data，并新增响应封装回归测试。
3. 同步修正 MCP 保存预览桥接的 context 封装位置；未启用或验收外部保存插件。
4. 更新离线测试夹具：6.2 启动版本、领域工具集、ToolAnnotations、UTF-8、Windows 本地化警告、新运行身份及历史证据语义。
5. 未绑定端点的旧崩溃日志仅作参考，不再让测试期待把它误判为当前端点崩溃。

## 离线记录

初轮选定的 12 个测试文件：46 passed / 33 failed；不是宿主故障计数，其中多数是旧夹具不匹配。
随后按失败项修复、定点复跑：64 个相关案例中 57 passed / 7 failed；最后剩余失败所属三个文件全部通过（29 passed）。
新增配置/领域隔离回归 8 passed；新增预览封装与恢复失败契约 2 passed。
这些运行合计覆盖 90 个不同测试案例，初轮失败项均已解决；不是一次 90 项全套运行。
修改范围的 Ruff 检查通过，未运行全仓库 lint 或无关测试。

选定文件：test_stage_composition、test_stage_tool_contract、test_tool_profiles、test_tool_registration、test_runtime_status、test_capabilities、test_v6_runtime_capabilities、test_job_governance、test_job_tool_contract、test_extension_async_handlers、test_run_isaac_sim_windows、test_run_isaac_sim_supervised_windows；新增 test_workflow_configuration、test_workflow_transactions。

## 真实宿主

- Isaac `6.2.0-rc.14`，PhysX，MCP 扩展 `0.7.0`，端点 `127.0.0.1:8876`。
- 独立 headless SimulationApp，禁用设置持久化，使用验收目录独立日志；未打开 Bauma 或任何正式资产。
- 能力查询确认 sany.granular_mpm 与 bauma.save_to_source 均 disabled。
- 初次启动等待 RTX shader 编译时发生只读查询超时；日志明确显示正在编译，没有盲重发写操作。编译结束后查询恢复。

`scripts/verify_workflow_6_2_live.py` 的七组检查全部通过：

1. 版本、实例身份、源码位置和外部插件禁用状态。
2. 预览不写入 → 使用 plan_id 应用 → root/指定 sublayer 多层修改 → 撤销；Session 保持原样，属性来源正确。
3. 预览之后发生编辑，旧计划被 STALE_PLAN 拒绝。
4. 批处理第二项故意失败，第一项已修改的 root 与其他触及层恢复，逐层文本与修改前相同。
5. 属性级快照恢复，新增的临时属性正确移除。
6. 场景组合查询分页、truncated 与 next_offset 正确。
7. 只在验收目录内保存和重开 USD，Stage 身份改变、旧计划失效。

真实 stdio MCP 客户端完成 initialize、tools/list、tools/call。`core,scene,physics` 组合实际注册 80 个工具，没有 request_mpm_rebuild；服务端与扩展均为 0.7.0。
本轮为非视觉的编辑/事务/传输检查，没有播放时间线或开展画面、物理精度、性能测试。

## 清理与证据

验收结束返回空匿名 Stage、timeline stopped；隔离宿主正常关闭（进程退出码 0）。
正式场景、用户配置与外部插件源码均未改变。仅保留本仓库 test_outputs/workflow-6.2 中的 scratch 文件和证据，不入 Git：

- live-report.json：七组宿主检查、实例与运行版本。
- stdio-report.json：真实客户端版本、领域和工具计数。
- kit.log、host-console.log、live-console.txt。

日志没有相关未处理 Error；包含官方 API 弃用提示、空 URL 警告，以及切换 Stage 时 tensor view 失效提示。未执行物理步进。
当前聊天的已缓存旧客户端曾显示 0.6.0 / 129 工具；独立新进程已确认 0.7.0，重启 Codex 刷新缓存，不把旧客户端读数当作新版验收结果。

## 用户要求再次复测：2026-11-12 12:42—12:44

基线 `17b022f`，仍仅 MCP；外部插件禁用，正式场景未打开。

- 一次完整运行上述 90 个离线案例：89 passed / 1 failed。
- 失败项为 supervisor 的假宿主测试使用本机默认 8876，恰逢真实隔离宿主启动。状态文件明确返回 `external_runtime_detected / healthy_runtime_already_listening`，属于测试端口未隔离，不是启动器错误。
- 测试夹具改为为每次调用保留独立临时端口，并显式传入 `-Port`；假启动器不监听该端口。真实宿主仍运行时定点复跑 supervisor 两项：2 passed。90 项覆盖中的失败项已消除，不重复运行其余已通过的 89 项。
- 同范围 Ruff 通过；本轮只改测试夹具，不改 MCP 功能代码。
- 新实例的七组 live 工作流再次全部通过。
- 新建 stdio 客户端再次完成 initialize / tools/list / tools/call，80 个 core+scene+physics 工具，客户端和扩展均 0.7.0。
- Kit 日志没有 Error 级记录；返回空且 stopped 的 Stage 后，隔离宿主正常退出，退出码 0。

本轮原始证据位于 `test_outputs/workflow-6.2-rerun-20261112-124224/`，包含 offline.txt/xml、supervisor-isolated.txt/xml、live-report.json、stdio-report.json 与宿主日志。不包含外部插件测试或性能验证。
