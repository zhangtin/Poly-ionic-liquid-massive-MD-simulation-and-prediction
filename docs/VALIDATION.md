# 验证报告（V0.1）

日期：2026-11-03 · 开发环境：Ubuntu 24.04，Python 3.13.18，PyYAML 6.0.3，pydantic 2.13.5，Jinja2 3.1.6，pytest 9.1.1，bash 5.2.21。

## 1. 验证层级

| 状态 | 含义 | V0.1 中是否会被赋予 |
|---|---|---|
| `CONFIG_VALIDATED` | 配置、基准工程、模板、拓扑依赖、范围、输出路径均通过检查 | 是（`plan` / `validate`） |
| `STATIC_VALIDATED` | 生成的任务包完整、校验和一致、MDP 映射正确、脚本语法正确 | 是（`build` 写入 `job.json` / `manifest.csv`） |
| `GROMPP_VALIDATED` | `gmx grompp` 接受所有阶段 | **否**——V0.1 代码从不赋予 |
| `RUN_VALIDATED` | 最小 `mdrun` 成功 | **否** |

`STATIC_VALIDATED` ≠ GROMACS 接受 ≠ 物理正确。

## 2. GROMACS 可用性

- 开发环境未安装 GROMACS；`apt` 软件源与 conda 源在该环境中不可达。
- 曾尝试从 GitHub 获取 GROMACS 2025.5 源码并本地编译，编译步骤被开发环境的安全策略拒绝（不允许编译执行外部代码）。
- 因此：**基准工程与生成的任务包均未经 `grompp` 或 `mdrun` 验证**。本报告中没有任何结论依赖 GROMACS 实际运行。
- 已提供可选集成测试 `tests/test_gromacs_integration.py`（检测到 `gmx` 时自动运行，见 §5）。

## 3. 自动化测试结果

命令：`python -m pytest -q -rs`

```
118 passed, 2 skipped
SKIPPED tests/test_gromacs_integration.py: GROMACS (gmx) not installed  (×2)
```

| 文件 | 用例数 | 覆盖内容 |
|---|---|---|
| `test_simulation_spec.py` | 14 | 时长→步数精确换算（含 0.7 ns / 2 fs 这一浮点截断陷阱）、非整数步数报错、单位格式化 |
| `test_config.py` | 28 | 空列表、非法温度/压力、字符串/布尔冒充数字、未知字段、缺失字段、重复 YAML 键、重复扫描值（含 300 与 300.0）、超出模型范围、步长过大、缺失基准工程、问题汇总报告 |
| `test_parameter_space.py` | 12 | 单参数/双参数扫描、多 Replica、36 任务完整性、Job ID 稳定唯一、种子可复现且互不相同且在合法范围、身份不受项目名/列表顺序影响、序号位宽 |
| `test_gromacs_adapter.py` | 31 | 各阶段变量作用域、渲染后 MDP 取值、9 类错误模板（写死温度、NVT 开压浴、NPT 关压浴、checkpoint 阶段重新生成速度、缺 ld-seed、写死种子、无恒温器、非各向同性、EM 用 md）、未知/缺失变量、语法错误、未替换标记、缺失模板、拓扑闭包、缺失/绝对/越界/尖括号 include、include 循环、运行脚本结构与 `bash -n` |
| `test_build.py` | 21 | 36 任务验收、重复构建逐字节一致、拒绝覆盖已有结果、`--overwrite` 只替换 mdflow 输出、非法输出路径、缺失结构/拓扑依赖/模板、基准工程被改动、损坏的 `.gro`、文件名冲突、构建中途失败不留残留、事后篡改检测、清单漂移检测、无主机绝对路径 |
| `test_cli.py` | 7 | 三个命令的输出与退出码、`plan` 不写文件、`validate` 复核已有构建 |
| `test_run_script_mock.py` | 5 | 用**模拟的** `gmx` 运行生成的 `run.sh`：调用顺序与参数、checkpoint 传递、从任意目录启动、`MDRUN_ARGS` 为空/非空、错误退出码传递（失败后不再执行后续阶段）、版本过低与找不到 `gmx` 的处理 |
| `test_gromacs_integration.py` | 2 | **跳过**（无 GROMACS） |

模拟 `gmx` 只检查输入文件存在并写出占位输出，**不解析 MDP、不计算任何物理量**，它验证的是脚本逻辑，不是 GROMACS 兼容性。

Python 3.11：环境中有 3.11 解释器但无法安装依赖（无法访问 PyPI），只完成了 `python3.11 -m compileall`（全部源码与测试编译通过）；测试套件仅在 3.13 上实际运行。

## 4. 36 任务验收（`configs/scan.example.yaml`）

```bash
mdflow build configs/scan.example.yaml      # exit 0
mdflow validate configs/scan.example.yaml   # exit 0
```

| 验收项（工作指令 §17） | 结果 | 依据 |
|---|---|---|
| 1 所有任务包生成成功 | 通过 | 36 个目录，`generation_status = COMPLETE` |
| 2 任务数量正确 | 通过 | 4 × 3 × 3 = 36 |
| 3 参数组合无遗漏 | 通过 | `test_acceptance_36_jobs` 比对全部 36 个 (T, P, r) |
| 4 Job ID 唯一且稳定 | 通过 | 36 个不同 ID；两次独立构建 `manifest.csv` 完全相同 |
| 5 Replica 种子可复现 | 通过 | 同上；36 个种子互不相同 |
| 6 MDP 变量正确填充 | 通过 | 映射一致性检查 + 测试逐一核对 `ref-t`/`ref-p`/`gen-seed` |
| 7 模拟步数正确 | 通过 | EM 50 000（最大步数）、NVT 500 000、NPT 2 500 000、Production 10 000 000 |
| 8 Shell 脚本结构完整 | 通过 | 结构检查、`bash -n`、模拟 `gmx` 全流程 |
| 9 拓扑及结构依赖完整 | 通过 | 每个任务含 `conf.gro`、`topol.top` 及 4 个 `oplsaa.ff` 文件，SHA-256 与基准工程一致 |
| 10 Job Metadata 正确 | 通过 | `job.json` 与清单、文件哈希一致 |
| 11 Manifest 正确 | 通过 | `check_manifest` |
| 12 原始基准工程未修改 | 通过 | 构建前后全目录哈希一致；`sha256sum -c SHA256SUMS` 通过 |
| 13 相同配置重复生成科学输入一致 | 通过 | 两次构建 `diff -r`（排除 `build_report.json`）无差异 |
| 14 自动化测试通过 | 通过 | 118 passed, 2 skipped |
| 15 示例来源及许可证记录完整 | 通过 | EXAMPLE_SOURCE.md，上游校验脚本实测通过 |
| 16 文档与代码一致 | 已人工核对 | — |
| GROMACS 预处理与短时运行 | **未完成** | 无 GROMACS |

示例（job_0001）：T = 280 K，P = 1 bar，replica 1，job_id `ecc041ef0767d020`，seed 2005588573。基准工程哈希 `67956e715703cadfc0592973f87d909ea3adf4bb93992906eadc9f9ae961a12f`。

## 5. 如何补做 GROMACS 验证（在装有 GROMACS ≥ 2021 的机器上）

```bash
pip install -e ".[dev]"
python -m pytest -m gromacs -v          # 或 MDFLOW_GMX=/path/to/gmx python -m pytest -m gromacs
```

测试内容：用 50 步 EM、各 100 步 MD 的极小协议构建 1 个任务，(1) 对 EM 阶段运行 `grompp` 并要求无 WARNING；(2) 完整运行 `run.sh` 并检查四个阶段的 `.gro` 均生成。也可以直接 `bash generated_jobs/job_0001/run.sh`（完整 20 ns 生产阶段较慢）。

建议先运行这一步，再把任务包用于任何实际计算。若 grompp 给出 NOTE/WARNING，应修改基准工程模板，而不是加 `-maxwarn`。

## 6. 未验证事项

- grompp 是否接受模板中的全部 MDP 选项与取值（例如在不同 GROMACS 版本下的默认值行为）。
- 协议的物理合理性：平衡时长是否足够、280–340 K / 1–50 bar 下 SPC/E 的行为、`tau-t`/`tau-p` 是否合适。
- 由 `spc216.gro`（SPC 平衡构型）平移得到的初始结构对 SPC/E 的 EM 收敛情况。
- Replica 之间的实际去相关程度。
- 在 Windows、macOS（bash 3.2）上的运行脚本行为；Python 3.11/3.12 下的测试运行。
