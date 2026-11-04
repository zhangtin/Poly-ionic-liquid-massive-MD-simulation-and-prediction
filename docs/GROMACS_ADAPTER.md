# GROMACS Adapter

所有 GROMACS 专有逻辑位于 `src/mdflow/gromacs_adapter.py`。

## 1. 机制：Base-project-driven Template Generation

基准工程提供 4 个 Jinja2 MDP 模板。mdflow **只**替换声明过的变量（见 CONFIGURATION.md §3），模板中其他所有科学参数（截断、静电方法、耦合常数、输出频率……）原样保留。

渲染使用 `StrictUndefined`，并在渲染前后做四项检查：

1. 模板引用了不被允许的变量 → `TEMPLATE_UNKNOWN_VARIABLE`（例如 EM 模板引用 `temperature_K`，或 NVT 模板引用 `pressure_bar`）；
2. 模板没有引用必需变量 → `TEMPLATE_MISSING_VARIABLE`（否则扫描值会被悄悄忽略）；
3. 渲染时缺值 → `TEMPLATE_UNDEFINED_VARIABLE`；
4. 输出中残留 `{{ }}`、`{% %}`、`{# #}` → `TEMPLATE_UNRENDERED`。

## 2. 参数映射

| 通用规格（`SimulationSpec`） | 模板变量 | 示例 MDP 键 |
|---|---|---|
| `temperature_K` | `temperature_K` | `ref-t`、`gen-temp` |
| `pressure_bar` | `pressure_bar` | `ref-p` |
| `protocol.timestep_fs` / 1000 | `dt_ps` | `dt` |
| `StageSpec.steps` | `nsteps` | `nsteps` |
| `random_seed` | `random_seed` | `gen-seed`、`ld-seed` |

### 渲染后的映射一致性检查（`check_rendered_mdp`）

模板只是文本，变量写错键名或写成注释时 Jinja2 无法发现。因此渲染后会把 MDP 解析出来（键名大小写不敏感、`-`/`_` 等价、重复键报错），逐阶段核对：

| 阶段 | 检查 |
|---|---|
| 全部 | `nsteps` = 该阶段步数 |
| EM | `integrator` ∈ {steep, cg, l-bfgs} |
| 动力学阶段 | `integrator` ∈ {md, md-vv, md-vv-avek, sd, bd}；`dt` = 步长；有恒温器（或 sd/bd 积分器）且 `ref-t` = 扫描温度；仅一个 `tc-grps` |
| NVT | `pcoupl = no` |
| NPT | `pcoupl ≠ no` |
| 启用压浴的阶段 | `pcoupltype = isotropic`；`ref-p` = 扫描压力（单值） |
| NPT、Production | 不允许 `gen-vel = yes`（会丢弃 checkpoint 中的速度） |
| `gen-vel = yes` | `gen-temp` = 扫描温度；必须设置 `gen-seed` |
| 随机性耦合/积分器（V-rescale、Andersen、C-rescale、sd、bd） | 必须设置 `ld-seed`（否则 GROMACS 自选随机种子，结果不可复现） |
| 任何出现的 `gen-seed`/`ld-seed` | 必须等于该任务的 `random_seed`（防止模板写死相同种子） |

Production 的系综**继承自基准工程**：mdflow 从渲染后的 `pcoupl` 判定（示例工程为 NPT）并写入 `job.json`。

V0.1 不支持多温控组、各向异性/半各向同性压浴扫描，遇到时报 `MDP_UNSUPPORTED`。

## 3. 示例工程的 MDP 协议

由本项目编写（参数依据 GROMACS 参考手册的 mdp 选项说明），未经 GROMACS 实际运行验证：

| | EM | NVT | NPT | Production |
|---|---|---|---|---|
| integrator | steep (emtol 1000, emstep 0.01) | md | md | md |
| 起始 | `conf.gro` | `em.gro`，`gen-vel=yes` | `nvt.gro` + `nvt.cpt`，`continuation=yes` | `npt.gro` + `npt.cpt`，`continuation=yes` |
| 恒温器 | — | V-rescale, τ_T = 0.1 ps | V-rescale, 0.1 ps | V-rescale, 0.1 ps |
| 压浴 | — | 无 | C-rescale isotropic, τ_P = 2 ps, κ = 4.5×10⁻⁵ bar⁻¹ | 同 NPT |
| 种子 | — | `gen-seed`, `ld-seed` | `ld-seed` | `ld-seed` |

共同设置：Verlet 截断方案，PME，rcoulomb = rvdw = 1.0 nm，DispCorr = EnerPres，`constraints = h-bonds`（纯 SPC/E 水由 `spce.itp` 中的 SETTLE 约束，该选项对本体系无实际作用）。C-rescale 需要 GROMACS ≥ 2021。

## 4. 随机种子与 Replica 独立性

- 种子 = `sha256("mdflow-seed-v1|<attempt>|" + identity)` 取 64 位后映射到 [1, 2³¹−1]（`gen-seed` 为 32 位整型，`ld-seed` 为 64 位，−1 表示让 GROMACS 自选，因此避开）。全扫描内种子保证互不相同；万一碰撞，按任务顺序确定性地递增 `attempt` 重算，相同输入仍得到相同种子。
- **Replica 编号本身不产生任何随机性。** 在示例工程中，Replica 之间的差异来自：
  1. NVT 阶段 `gen-vel = yes, gen-seed = <seed>`：不同的 Maxwell–Boltzmann 初速度；
  2. 所有动力学阶段 `ld-seed = <seed>`：V-rescale 恒温器和 C-rescale 压浴的随机项不同。
- **局限**：所有 Replica 使用相同的初始坐标（`conf.gro`），EM 阶段是确定性的，因此各 Replica 在 NVT 开始前完全相同。不同 Replica 的统计独立性依赖于初速度和随机耦合在平衡阶段中使轨迹去相关；mdflow 不评估这一点。
- 若某个基准工程不启用任何随机初始化或随机耦合，则不同种子**不会**产生不同轨迹，不能据此声称 Replica 独立。mdflow 会对“启用了随机性却未设种子”报错，但不会强制要求基准协议包含随机性。
- 另外，GROMACS 在多线程/GPU 下的浮点归约顺序可能导致相同输入的轨迹逐位不同；mdflow 保证的是**输入**可复现，不是轨迹逐位可复现。

## 5. 拓扑依赖（`#include`）

`resolve_topology_includes` 模拟 GROMACS 预处理器（`src/gromacs/gmxpreprocess/gmxcpp.cpp`）的行为：带引号的 include 相对于**包含它的文件所在目录**查找。例：`topol.top` 中的 `"oplsaa.ff/forcefield.itp"`，以及 `forcefield.itp` 中的 `"ffnonbonded.itp"`（解析为 `oplsaa.ff/ffnonbonded.itp`）。

GROMACS 找不到时会继续搜索 `-I` 路径和安装库（GMXLIB / `share/top`）；mdflow **刻意不这样做**——任务包必须自包含，否则在另一台机器（不同 GROMACS 版本）上会悄悄用到不同的力场文件。因此：

| 情况 | 代码 |
|---|---|
| 在基准工程内找不到 | `DEPENDENCY_MISSING` |
| 绝对路径 | `DEPENDENCY_ABSOLUTE` |
| 路径跳出基准工程（`../`） | `DEPENDENCY_OUTSIDE_BASE` |
| `#include <...>` 等其他语法 | `DEPENDENCY_UNSUPPORTED` |

`#ifdef` 分支内的 include 也视为必需（保守做法，活动分支只有 grompp 运行时才知道）。仅 include 闭包中的文件会被复制（示例中只复制 `oplsaa.ff` 的 4 个文件），保持原相对路径。

## 6. 运行脚本 `run.sh`

生成规则（对应工作指令 §10）：

1. `#!/usr/bin/env bash` + `set -euo pipefail`，任何命令失败立即以其退出码终止；
2. `cd "$(dirname "${BASH_SOURCE[0]}")"`：不依赖调用者的工作目录；
3. 只使用任务目录内的相对文件名，无构建主机绝对路径（构建时检查 `SCRIPT_ABSOLUTE_PATH`）；
4. 不使用 `-maxwarn`；
5. 依次 `grompp`/`mdrun`：EM → NVT（`-c em.gro`）→ NPT（`-c nvt.gro -t nvt.cpt`）→ Production（`-c npt.gro -t npt.cpt`）；checkpoint 传递坐标、速度与耦合状态；
6. `grompp -po <stage>_mdout.mdp`，避免各阶段相互覆盖 `mdout.mdp`；
7. 运行前检查 `GMX` 是否存在（不存在退出 127）及主版本 ≥ `min_version`（否则退出 1）；
8. 环境变量：`GMX`（默认 `gmx`）、`MDRUN_ARGS`（附加给每次 `mdrun`，如 `"-ntomp 8 -pin on"`）。空 `MDRUN_ARGS` 采用 `${arr[@]+"${arr[@]}"}` 写法，以避免旧版 bash（如 macOS 自带 3.2）在 `set -u` 下报错（仅在 bash 5 上实测）。

V0.1 只生成脚本，不执行。脚本在构建时经过 `bash -n` 语法检查。
