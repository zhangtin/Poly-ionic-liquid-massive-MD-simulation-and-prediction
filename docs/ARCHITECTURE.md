# 架构

## 1. 四层结构

```text
            scan.yaml                    base_project.yaml + 文件
                │                                   │
        config.py / schemas.py  ←──────────────────┘   （加载 + Schema 检查）
                │
                ▼
┌───────────────────────────────┐
│ Parameter Space Engine        │  parameter_space.py
│  笛卡尔积 · 重复检查 · Replica │
│  Job ID · 随机种子             │
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ Simulation Specification      │  simulation_spec.py
│  带单位的物理量 (Decimal)      │
│  Protocol / StageSpec / 步数  │
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ GROMACS Adapter               │  gromacs_adapter.py (+ template_renderer.py)
│  变量映射 · MDP 渲染与检查     │
│  #include 解析 · run.sh       │
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ Job Package Builder           │  package_writer.py
│  任务目录 · 复制依赖 · job.json│
│  manifest · 原子化发布         │
└───────────────────────────────┘

横切：validator.py（静态检查）、plan.py（把以上串成一个已验证的 Plan）、cli.py
```

## 2. 模块职责

| 模块 | 职责 | 不负责 |
|---|---|---|
| `schemas.py` | Pydantic 模型：字段、类型、正值、无未知字段 | 跨字段/文件系统检查 |
| `config.py` | YAML 解析（含重复键检测）、路径解析、基准工程描述文件加载 | 业务规则 |
| `parameter_space.py` | 展开扫描空间、拒绝重复值、Replica 编号、Job ID、种子 | 任何 GROMACS 文件 |
| `simulation_spec.py` | 与引擎无关的模拟定义；单位换算；时长→步数（精确整除检查） | GROMACS 字段名 |
| `template_renderer.py` | 严格 Jinja2 渲染（未知变量、必需变量、未定义变量、残留标记） | MDP 语义 |
| `gromacs_adapter.py` | 规格→MDP 变量映射；MDP 解析与映射一致性检查；拓扑 `#include` 解析；`.gro` 检查；`run.sh` 生成 | 写文件 |
| `package_writer.py` | 暂存目录构建、复制、写 MDP/脚本/元数据/清单、发布、覆盖保护、事后复核 | 参数展开 |
| `validator.py` | 基准工程、范围、输出路径、任务包、元数据、清单的静态检查 | 运行 GROMACS |
| `plan.py` | 收集全部配置级问题后一次性报告；产出 `Plan` | — |
| `cli.py` | `plan` / `build` / `validate` | `run` / `submit` / `analyze`（V0.1 不实现） |

依赖方向单向：`parameter_space` 与 `simulation_spec` 不导入 `gromacs_adapter`。GROMACS 专有知识（字段名、`-`/`_` 等价、`grompp` 的 include 搜索顺序、随机种子键、命令行）全部集中在 `gromacs_adapter.py`。

## 3. 数据流（`mdflow build`）

1. `load_config` → `ScanFile`；`load_base_project` → `BaseProjectDescriptor`。
2. `check_base_project`：结构文件、拓扑 include 闭包、模板变量、文件名冲突、`SHA256SUMS`。
3. `Protocol.from_config`：时长→步数，非整数即报错。
4. `expand`：T × P × replica，重复值即报错。
5. `check_scan_limits`、`check_output_path`。以上 2–5 的问题**汇总后一次性**抛出。
6. `base_project_sha256` + `Protocol.fingerprint` + 参数 + builder 版本 → Job ID 与种子。
7. 在 `.<output>.mdflow-staging-*` 中逐个写任务包：复制依赖 → 渲染 MDP → 生成 `run.sh` → 静态检查 → 写 `job.json`。
8. 写 `manifest.csv` 并核对；对比基准工程构建前后的全目录哈希；写 `build_report.json`。
9. 全部通过后 `os.replace` 到最终目录。任何失败都会删除暂存目录，不留下半成品。

## 4. 身份与确定性

- **Job ID** = `sha256(canonical_json(identity))[:16]`，`identity` 包含：builder 版本、基准工程内容哈希（描述文件 + 结构 + 拓扑闭包 + 模板）、协议指纹（时间步长、各阶段步数）、温度、压力、Replica 编号。完整 `identity` 写入 `job.json`，可独立重算。
- 项目名、输出路径、列表顺序**不**进入身份：改名或调整列表顺序不改变任务的科学身份。
- `job_0001` 这样的顺序编号只为便于阅读，不是科学身份。
- 生成时间、主机、绝对路径只写入 `build_report.json`。

## 5. 扩展原则（面向 V0.2+）

- 新的扫描变量：在 `ScanConfig` 与 `SimulationSpec` 中以“带单位的字段”加入，再在 `gromacs_adapter.ALLOWED_VARS / stage_context / check_rendered_mdp` 中映射。参数空间引擎无需了解 GROMACS。
- V0.2（配置管理）可用 Python 生成 MDP 取代模板：只需替换 `render_stages` 的实现，`job.json`、身份和打包逻辑不变。
- V0.4（执行管理）应读取 `manifest.csv` / `job.json`，而不是重新推导参数；`ValidationStatus` 已预留 `GROMPP_VALIDATED`、`RUN_VALIDATED`。
- 多引擎支持：新增与 `gromacs_adapter.py` 平行的适配器，复用 `Plan`。
