# MD Automation Platform — V0.1: GROMACS Script Builder

> **Python owns the workflow. GROMACS owns the numerical simulation.**

`mdflow` 从一份 YAML 参数扫描配置出发，基于一个固定的 GROMACS 基准工程，为每组（温度、压力、Replica）自动生成一个**完整、独立、可复现**的 GROMACS 模拟任务包：各阶段 MDP、结构与拓扑依赖、Bash 运行脚本、随机种子和元数据。

V0.1 **只生成并静态验证**任务包，不执行模拟、不调度 HPC、不做分析。

## 安装

需要 Python ≥ 3.11。

```bash
cd md-automation
pip install -e .            # 依赖：PyYAML、pydantic>=2、Jinja2
pip install -e ".[dev]"     # 另含 pytest
```

运行生成的任务包需要 GROMACS ≥ 2021（`mdflow` 本身不需要 GROMACS）。

## 快速开始

```bash
mdflow plan     configs/scan.example.yaml   # 校验配置，列出 36 个任务，不写文件
mdflow build    configs/scan.example.yaml   # 生成 generated_jobs/
mdflow validate configs/scan.example.yaml   # 校验配置/基准工程/模板/依赖；若已构建则复核输出
```

运行某一个任务（需在装有 GROMACS 的机器上）：

```bash
bash generated_jobs/job_0001/run.sh
GMX=gmx_mpi MDRUN_ARGS="-ntomp 8 -pin on" bash generated_jobs/job_0001/run.sh
```

## 配置示例

```yaml
project: water_scan_001
base_project: "../examples/base_gromacs"   # 相对路径以本 YAML 文件所在目录为基准
scan:
  temperature_K: [280, 300, 320, 340]
  pressure_bar: [1, 10, 50]
  replicas: 3
simulation:
  timestep_fs: 2.0
  em_steps: 50000
  nvt_ns: 1.0
  npt_ns: 5.0
  production_ns: 20.0
output:
  directory: "../generated_jobs"
```

4 × 3 × 3 = 36 个任务。全部字段见 [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md)。

## 输出

```text
generated_jobs/
├── manifest.csv          # 每行一个任务
├── build_report.json     # 构建时间、主机、配置哈希等（唯一的非确定性文件）
├── job_0001/
│   ├── conf.gro  topol.top  oplsaa.ff/   # 从基准工程逐字节复制（仅拓扑实际 #include 的文件）
│   ├── em.mdp  nvt.mdp  npt.mdp  production.mdp
│   ├── run.sh            # EM → NVT → NPT → Production
│   └── job.json          # 参数、种子、步数、文件 SHA-256、验证状态
└── ...
```

相同输入重复构建时，除 `build_report.json` 外所有文件逐字节一致。

## 文档

| 文档 | 内容 |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 四层架构、模块边界、数据流、扩展原则 |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | YAML 字段、单位、限制、错误代码 |
| [docs/GROMACS_ADAPTER.md](docs/GROMACS_ADAPTER.md) | 参数映射、MDP 模板机制、运行脚本规则、Replica 独立性 |
| [docs/EXAMPLE_SOURCE.md](docs/EXAMPLE_SOURCE.md) | 示例工程来源、许可证、校验和、修改记录 |
| [docs/VALIDATION.md](docs/VALIDATION.md) | 测试方法、实际结果、未验证事项 |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | 开发环境、项目结构、测试、扩展建议 |
| [CHANGELOG.md](CHANGELOG.md) | V0.1 内容与已知限制 |

## 重要声明

- `STATIC_VALIDATED` 表示任务包**文件完整且内部一致**，**不**表示 GROMACS `grompp` 已接受、也不表示物理模型正确。
- V0.1 开发环境中**没有 GROMACS**，生成的任务包**尚未**经 `grompp` 或 `mdrun` 实际验证，详见 [docs/VALIDATION.md](docs/VALIDATION.md)。
- 示例扫描条件仅用于测试 Script Builder，不是经过验证的科研条件。
