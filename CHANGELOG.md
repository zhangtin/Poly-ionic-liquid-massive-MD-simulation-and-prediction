# Changelog

## [0.1.0] — 2026-11-03 — GROMACS Script Builder

### 新增
- `mdflow plan | build | validate` 命令行工具（`pyproject.toml` 入口 `mdflow`）。
- 严格的 YAML 配置 Schema（未知字段、错误类型、重复 YAML 键、重复扫描值均报错，不做静默修正）。
- 温度 × 压力 × Replica 的参数空间展开；基于内容哈希的稳定 Job ID；可复现且互不相同的随机种子。
- 与引擎无关的 `SimulationSpec` / `Protocol`，十进制精确的时长→步数换算，非整数步数报错。
- 基准工程驱动的 Jinja2 MDP 模板机制，按阶段限定可用变量；渲染后 MDP 映射一致性检查（温度、压力、步长、步数、系综、种子）。
- GROMACS 拓扑 `#include` 闭包解析（按 grompp 的相对路径规则，不回落到 GMXLIB），只打包所需文件。
- 每任务 `run.sh`（EM → NVT → NPT → Production，checkpoint 传递，`set -euo pipefail`，GROMACS 版本检查，无 `-maxwarn`）。
- `job.json`（参数、种子用途、协议、身份文档、文件 SHA-256、状态）、`manifest.csv`、`build_report.json`。
- 暂存目录构建 + 原子发布；拒绝覆盖已有结果；`--overwrite` 仅可替换此前的 mdflow 构建；构建前后基准工程哈希比对。
- 示例基准工程：1728 个 SPC/E 水分子（GROMACS 2025.5 `spc216.gro` 2×2×2 平移复制 + 未修改的 OPLS-AA 文件，LGPL-2.1），项目编写的拓扑与 MDP 模板；来源记录与上游校验脚本。
- 120 个 pytest 用例（118 通过，2 个 GROMACS 集成测试因环境无 GROMACS 而跳过）。
- 文档：README、ARCHITECTURE、CONFIGURATION、GROMACS_ADAPTER、EXAMPLE_SOURCE、VALIDATION、DEVELOPMENT。

### 已知限制
- **未经 GROMACS 验证**：开发环境无 GROMACS，示例工程与生成的任务包均未运行过 `grompp`/`mdrun`。
- 仅支持 `.gro` 结构、单温控组、各向同性压浴；只能扫描温度和压力。
- 固定四阶段协议（EM/NVT/NPT/Production），不能增删阶段；不支持位置限制（`-r`）。
- 所有 Replica 共用相同初始坐标，独立性仅来自初速度与随机耦合的种子。
- `#ifdef` 分支内的 include 一律视为必需。
- 基准工程中的适用范围（273.15–373.15 K、1–1000 bar、≤ 2 fs）为项目自定的保守界限，不是物理验证结果。
- 测试只在 Python 3.13 上运行；Python 3.11 仅做了编译检查。
- 生成的运行脚本只在 bash 5 上测试（使用模拟 `gmx`）。
- 不包含：模拟执行、HPC 调度、轨迹分析、数据库、Materials Studio 转换等（按工作指令 §3.2 排除）。
