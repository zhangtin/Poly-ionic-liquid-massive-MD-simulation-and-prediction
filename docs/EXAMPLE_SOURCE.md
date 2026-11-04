# 示例工程来源说明

## 1. 选型与搜索过程

工作指令要求优先使用 GROMACS 官方来源的简单液态水体系。检索与取舍：

| 候选 | 结论 |
|---|---|
| GROMACS 发行版自带的 `share/top/spc216.gro`（216 个已平衡 SPC 水分子）及 `oplsaa.ff` 力场 | **采用**。官方来源，随 GROMACS 以 LGPL-2.1 分发，可再分发；`gmx solvate` 的默认溶剂盒即此文件 |
| 公开教程（如 J. Lemkul 的 GROMACS Tutorials）中的 MDP 文件 | **未采用**。未找到明确的再分发许可证 |
| 完整的官方“液态水 EM/NVT/NPT/MD”示例工程 | 未找到附带全部 MDP 的官方现成工程 |

因此按工作指令 §4.2 的备选方案：**结构与力场取自官方发行版（未修改），拓扑与 MDP 模板由本项目自行编写**，并在下文逐文件标明来源。本工程不是 GROMACS 官方示例工程。

## 2. 上游来源

- 项目：GROMACS（https://www.gromacs.org）
- 仓库：https://github.com/gromacs/gromacs（官方 GitHub 镜像，主仓库为 https://gitlab.com/gromacs/gromacs）
- 版本：tag `v2025.5`，commit `70126eecad7830d2062cdc7b0c1b180b92c98c2a`
- 获取日期：2026-11-03
- 获取方式：`git clone --depth 1 --branch v2025.5`；可用 `examples/base_gromacs/tools/fetch_upstream.sh` 以稀疏检出方式重新获取并校验（该脚本已在开发环境中实际运行，6 个文件校验全部 OK）。

## 3. 许可证

GROMACS 以 **GNU LGPL v2.1（或更高版本）** 发布，`share/top` 下的力场与结构数据随之分发。本项目在 `examples/base_gromacs/LICENSES/GROMACS-COPYING-LGPL-2.1.txt` 中附上未经修改的 `COPYING` 原文。被复制的文件均未修改，保留原有文件头注释（包括 OPLS-AA 的文献引用）。

使用者在发表结果时应按惯例引用 GROMACS、OPLS-AA（见 `oplsaa.ff/forcefield.itp` 文件头）以及 SPC/E 水模型（H. J. C. Berendsen, J. R. Grigera, T. P. Straatsma, *J. Phys. Chem.* **91**, 6269 (1987)）。

## 4. 逐文件来源与校验和

### 4.1 上游文件（逐字节复制，未修改）

| 本项目路径 | 上游路径 | SHA-256 |
|---|---|---|
| `oplsaa.ff/forcefield.itp` | `share/top/oplsaa.ff/forcefield.itp` | `6eb8f0d08684e1ac6f525bb323eae75ed197b2980ddfde975a24ca1a8c931d06` |
| `oplsaa.ff/ffnonbonded.itp` | `share/top/oplsaa.ff/ffnonbonded.itp` | `fdf072dac9900c039b58e21323ce621b2112dc86c46a4b5e49e1398ae5d3b9f0` |
| `oplsaa.ff/ffbonded.itp` | `share/top/oplsaa.ff/ffbonded.itp` | `145e6924f52fae7e93108fa3d674f31a53aea10c80b13dd89abf0b011adfd4fa` |
| `oplsaa.ff/spce.itp` | `share/top/oplsaa.ff/spce.itp` | `e733446e1c7bcf42e21ba2ff84cc57d8d603210218faa5203b3f078026d80682` |
| `upstream/spc216.gro` | `share/top/spc216.gro` | `dcb2c65552058a5083fddc5a4bb3187b1eac6c46e3acf038643ec2ec9f147620` |
| `LICENSES/GROMACS-COPYING-LGPL-2.1.txt` | `COPYING` | `b634ab5640e258563c536e658cad87080553df6f34f62269a21d554844e58bfe` |

只复制了拓扑实际需要的 4 个力场文件，而不是整个 `oplsaa.ff` 目录（后者含氨基酸数据库等本体系不需要的文件）。

### 4.2 本项目创建或派生的文件

| 文件 | 说明 |
|---|---|
| `conf.gro` | **派生**。`tools/make_conf.py` 将 `spc216.gro`（1.86206 nm 盒）沿三个方向平移复制 2×2×2，得到 1728 个水分子、3.72412 nm 立方盒；坐标仅做整盒平移，未删除或扰动任何分子，残基/原子重新编号，标题行注明来源。原因：单个 216 水盒边长小于 2×1.0 nm 截断半径，不能直接使用。生成后检查：周期性最小 O–O 距离 0.251 nm，密度 1.0008 g/cm³（按 18.015 g/mol 计算）。 |
| `topol.top` | 新写。`#include` OPLS-AA 与 `spce.itp`，`SOL 1728`。 |
| `mdp/em.mdp.j2`, `nvt.mdp.j2`, `npt.mdp.j2`, `production.mdp.j2` | 新写的 Jinja2 模板，协议见 `docs/GROMACS_ADAPTER.md` §3。参数为常见做法，依据 GROMACS 参考手册的 mdp 选项说明选取，**未经 grompp/mdrun 验证**。 |
| `base_project.yaml` | mdflow 基准工程描述文件，含项目自定的适用范围（273.15–373.15 K、1–1000 bar、≤ 2 fs）。 |
| `tools/make_conf.py`, `tools/fetch_upstream.sh` | 辅助脚本。 |
| `SHA256SUMS`, `README.md` | 完整性参考与说明。 |

说明：`spc216.gro` 本身是 SPC 模型下平衡的构型；SPC/E 与 SPC 几何相同（O–H 0.1 nm，H–O–H 109.47°），只是电荷不同，因此可作为 SPC/E 的起始构型，但需要经过 EM 与平衡阶段。

## 5. GROMACS 版本兼容性

- 力场与结构文件取自 GROMACS 2025.5，格式在 2018 年以来的版本中是稳定的。
- MDP 使用 C-rescale 压浴（GROMACS 2021 引入），因此 `base_project.yaml` 规定 `min_version: "2021"`，`run.sh` 在运行时检查主版本号。
- **未在任何 GROMACS 版本上实际运行验证**（开发环境无 GROMACS，见 VALIDATION.md）。

## 6. 运行验证状态

| 项目 | 状态 |
|---|---|
| 文件结构、依赖闭包、`.gro` 格式、校验和 | 已完成（静态） |
| `gmx grompp` 预处理 | **未完成** |
| 最小 `mdrun` 运行 | **未完成** |
