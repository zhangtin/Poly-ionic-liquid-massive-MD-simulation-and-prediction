# 配置说明

mdflow 使用两种 YAML 文件：

1. **扫描配置**（用户编写，例如 `configs/scan.example.yaml`）。
2. **基准工程描述文件** `base_project.yaml`（位于基准工程根目录）。

两者均以严格模式校验：未知字段、类型错误（包括用字符串或布尔值代替数字）、`NaN/inf`、重复的 YAML 键都会报错。**mdflow 从不默默修正输入。**

## 1. 扫描配置

所有相对路径以**该 YAML 文件所在目录**为基准解析，与当前工作目录无关。

| 字段 | 类型 | 单位 | 约束 | 说明 |
|---|---|---|---|---|
| `project` | str | — | `^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$` | 实验名称，写入 `job.json.experiment_id`；**不**影响 Job ID |
| `base_project` | str | — | 必须是含 `base_project.yaml` 的目录 | 基准工程路径 |
| `scan.temperature_K` | list[number] | K | 非空；每个值 > 0；不得重复；须在基准工程 `limits.temperature_K` 内 | 恒温器参考温度（及 NVT 初速度温度） |
| `scan.pressure_bar` | list[number] | bar | 非空；每个值 > 0；不得重复；须在 `limits.pressure_bar` 内 | 各向同性压浴参考压力 |
| `scan.replicas` | int | — | 1–1000 | 每个 (T, P) 的独立副本数 |
| `simulation.timestep_fs` | number | fs | > 0；≤ `limits.max_timestep_fs` | 积分步长（EM 除外的所有阶段） |
| `simulation.em_steps` | int | 步 | ≥ 1 | 能量最小化最大步数（不做时间换算） |
| `simulation.nvt_ns` | number | ns | > 0；必须是步长的整数倍 | NVT 平衡时长 |
| `simulation.npt_ns` | number | ns | 同上 | NPT 平衡时长 |
| `simulation.production_ns` | number | ns | 同上 | 生产阶段时长 |
| `output.directory` | str | — | 见下文 | 输出目录 |

### 1.1 数值规则

- 整数与浮点等价：`300` 与 `300.0` 是同一温度，因此 `[300, 300.0]` 报 `DUPLICATE_VALUE`。
- 步数 = 时长(ns) × 10⁶ / 步长(fs)，以十进制精确计算（`Decimal`），**不能整除即报错** `NON_INTEGER_STEPS`，不会四舍五入。例：20 ns / 2 fs = 10 000 000 步；1 ns / 1.5 fs → 报错。
- MDP 中写入规范化数值：`300.0` → `300`，2 fs → `dt = 0.002`。

### 1.2 输出目录规则

| 情况 | 结果 |
|---|---|
| 不存在 | 创建 |
| 存在且为空 | 使用 |
| 存在且非空 | `OUTPUT_EXISTS`（`build` 拒绝） |
| 非空 + `--overwrite` + 含 mdflow 的 `build_report.json` | 新构建成功后替换旧目录 |
| 非空 + `--overwrite` + 不是 mdflow 构建 | `OUTPUT_NOT_MDFLOW`，拒绝 |
| 与基准工程目录互相包含，或包含配置文件，或是普通文件，或无写权限 | `OUTPUT_PATH_INVALID` |

### 1.3 示例

```yaml
project: water_scan_001
base_project: "../examples/base_gromacs"
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

单参数扫描：把另一个列表写成单元素即可，如 `pressure_bar: [1]`。

## 2. 基准工程描述文件 `base_project.yaml`

| 字段 | 说明 |
|---|---|
| `name` | 基准工程名称（同 `project` 规则） |
| `description` | 可选说明 |
| `structure` | 初始结构文件，V0.1 仅支持 `.gro`，位于基准工程根目录 |
| `topology` | 主拓扑文件，位于根目录；其 `#include` 闭包会被打包 |
| `templates.em/nvt/npt/production` | 各阶段 Jinja2 MDP 模板（相对路径，须在基准工程内） |
| `gromacs.min_version` | 运行所需最低 GROMACS 主版本（如 `"2021"`），写入 `run.sh` 并在运行时检查 |
| `gromacs.developed_against` | 可选，开发时参照的版本 |
| `limits.temperature_K` | `[min, max]`，扫描温度必须在此范围内 |
| `limits.pressure_bar` | `[min, max]` |
| `limits.max_timestep_fs` | 最大允许步长 |

示例工程的取值见 `examples/base_gromacs/base_project.yaml`：273.15–373.15 K、1–1000 bar、≤ 2 fs。这些是**项目为测试体系选定的保守界限**，不是对 SPC/E 物理适用性的声明。

可选的 `SHA256SUMS`（`sha256sum` 格式）若存在，`plan/validate/build` 会逐一校验，不一致报 `BASE_PROJECT_MODIFIED`。

## 3. 模板变量

| 变量 | 含义 | 示例 | 允许出现的阶段 | 必须出现的阶段 |
|---|---|---|---|---|
| `nsteps` | 该阶段步数 | `500000` | 全部 | 全部 |
| `dt_ps` | 步长（ps） | `0.002` | nvt, npt, production | nvt, npt, production |
| `temperature_K` | 扫描温度 | `300` | nvt, npt, production | nvt, npt, production |
| `pressure_bar` | 扫描压力 | `10` | npt, production | npt；production 若 `pcoupl ≠ no` 则渲染后检查 `ref-p` |
| `random_seed` | 任务种子 | `2005588573` | nvt, npt, production | 否（但见 GROMACS_ADAPTER.md §4 的种子检查） |

## 4. 错误代码

| 类别 | 代码 |
|---|---|
| 文件/YAML | `FILE_NOT_FOUND` `NOT_A_FILE` `FILE_UNREADABLE` `YAML_PARSE_ERROR` `YAML_DUPLICATE_KEY` `SCHEMA_ERROR` |
| 扫描/协议 | `DUPLICATE_VALUE` `NON_INTEGER_STEPS` `TEMPERATURE_OUT_OF_RANGE` `PRESSURE_OUT_OF_RANGE` `TIMESTEP_TOO_LARGE` |
| 基准工程 | `BASE_PROJECT_MISSING` `BASE_DESCRIPTOR_MISSING` `BASE_PROJECT_MODIFIED` `SHA256SUMS_INVALID` `STRUCTURE_MISSING` `STRUCTURE_INVALID` `STRUCTURE_UNREADABLE` `STRUCTURE_UNSUPPORTED` `FILENAME_CONFLICT` |
| 拓扑依赖 | `DEPENDENCY_MISSING` `DEPENDENCY_ABSOLUTE` `DEPENDENCY_OUTSIDE_BASE` `DEPENDENCY_UNSUPPORTED` `DEPENDENCY_UNREADABLE` |
| 模板 | `TEMPLATE_MISSING` `TEMPLATE_UNREADABLE` `TEMPLATE_OUTSIDE_BASE` `TEMPLATE_SYNTAX_ERROR` `TEMPLATE_UNKNOWN_VARIABLE` `TEMPLATE_MISSING_VARIABLE` `TEMPLATE_UNDEFINED_VARIABLE` `TEMPLATE_UNRENDERED` |
| MDP 映射 | `MDP_SYNTAX_ERROR` `MDP_DUPLICATE_KEY` `MDP_MISSING_KEY` `MDP_BAD_VALUE` `MDP_MAPPING_MISMATCH` `MDP_WRONG_INTEGRATOR` `MDP_NO_THERMOSTAT` `MDP_ENSEMBLE_MISMATCH` `MDP_UNSUPPORTED` `MDP_DISCARDS_STATE` `MDP_UNSEEDED` |
| 输出/任务包 | `OUTPUT_EXISTS` `OUTPUT_NOT_MDFLOW` `OUTPUT_PATH_INVALID` `PACKAGE_INCOMPLETE` `PACKAGE_MISSING` `PACKAGE_MODIFIED` `SCRIPT_INVALID` `SCRIPT_SYNTAX_ERROR` `SCRIPT_ABSOLUTE_PATH` `BAD_FILENAME` `BAD_GMX_VERSION` `METADATA_INVALID` `METADATA_MISMATCH` `MANIFEST_MISSING` `MANIFEST_INVALID` `MANIFEST_MISMATCH` `JOB_ID_COLLISION` |

CLI 退出码：0 成功；1 存在上述任一问题；2 命令行用法错误。
