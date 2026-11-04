# 开发说明

## 环境

```bash
python3 -m venv .venv && source .venv/bin/activate     # Python >= 3.11
pip install -e ".[dev]"
```

运行时依赖只有 PyYAML、pydantic ≥ 2、Jinja2；测试依赖 pytest。`subprocess` 仅用于 `bash -n` 语法检查与可选的 GROMACS 集成测试，不用于执行模拟。

## 项目结构

```text
md-automation/
├── README.md  CHANGELOG.md  pyproject.toml
├── configs/scan.example.yaml          # 36 任务验收配置
├── examples/base_gromacs/             # SPC/E 水基准工程（来源见 docs/EXAMPLE_SOURCE.md）
│   ├── base_project.yaml  conf.gro  topol.top  SHA256SUMS  README.md
│   ├── mdp/{em,nvt,npt,production}.mdp.j2
│   ├── oplsaa.ff/                     # 4 个上游力场文件（未修改）
│   ├── upstream/spc216.gro            # 上游原始结构（留存）
│   ├── LICENSES/                      # GROMACS LGPL-2.1
│   └── tools/{make_conf.py, fetch_upstream.sh}
├── generated_jobs/                    # mdflow build 的验收输出（可删除后重新生成）
├── src/mdflow/
│   ├── __init__.py          版本号
│   ├── errors.py            Issue / MdflowError
│   ├── schemas.py           Pydantic 模型
│   ├── config.py            YAML 加载、路径解析
│   ├── parameter_space.py   Parameter Space Engine
│   ├── simulation_spec.py   Simulation Specification
│   ├── template_renderer.py 严格 Jinja2 渲染
│   ├── gromacs_adapter.py   GROMACS Adapter
│   ├── validator.py         静态检查
│   ├── plan.py              配置 → 已验证的 Plan
│   ├── package_writer.py    Job Package Builder
│   └── cli.py               mdflow plan / build / validate
├── tests/                             # pytest
└── docs/
```

与工作指令 §11 的建议相比新增了 `errors.py`（统一的问题类型）与 `plan.py`（把各层串起来，供三个 CLI 命令共用）。

## 测试

```bash
python -m pytest -q                 # 全部单元/构建测试；无 GROMACS 时集成测试自动跳过
python -m pytest -m gromacs -v      # 仅 GROMACS 集成测试（需要 gmx 或 MDFLOW_GMX）
```

测试都在 `tmp_path` 中使用基准工程的副本（`tests/conftest.py`），可以随意破坏而不影响仓库。常规测试不依赖 GPU、HPC 或长时间 MD，全部约 15 秒。

## 修改基准工程

1. 修改文件；
2. 在 `examples/base_gromacs/` 中重新生成校验和：
   ```bash
   find . -type f ! -name SHA256SUMS ! -path '*/__pycache__/*' | sed 's|^\./||' | sort | xargs sha256sum > SHA256SUMS
   ```
3. `mdflow validate configs/scan.example.yaml`。

注意：描述文件、结构、拓扑闭包或模板的任何变化都会改变基准工程哈希，从而改变所有 Job ID 与种子（有意为之）。`README.md`、`tools/`、`upstream/`、`LICENSES/` 不参与身份哈希。

## 编码约定

- 物理量字段名带单位后缀（`temperature_K`、`timestep_fs`、`duration_ns`），内部用 `Decimal`。
- 检查函数返回 `list[Issue]`，尽量收集全部问题后再抛出 `MdflowError`。
- GROMACS 专有内容只放在 `gromacs_adapter.py`。
- 生成的文件必须确定性：不写时间戳、主机名或绝对路径（这些只进 `build_report.json`）。

## 扩展建议

- **新增扫描变量**（例如其他 MDP 标量参数）：`ScanConfig` → `ScanPoint` / `SimulationSpec` → `identity_document` → `gromacs_adapter.ALLOWED_VARS`、`stage_context`、`check_rendered_mdp`。改变结构/组成的变量属于 V0.3 System Builder，不应通过模板实现。
- **GROMPP 验证命令**：若后续版本需要，可新增 `mdflow check-grompp`，对每个任务运行 `grompp` 并把 `job.json` 状态提升为 `GROMPP_VALIDATED`；注意它需要上一阶段输出，EM 之外的阶段只能在实际运行中验证。
- **执行管理（V0.4）**：以 `manifest.csv` 为任务队列，以 `job.json.files` 校验输入未被篡改后再提交。
