# Changelog

## [0.1.0] — 2026-11-03 — GROMACS Script Builder

### Added
- `mdflow plan | build | validate` command-line tool (`pyproject.toml` entry point `mdflow`).
- Strict YAML configuration schema: unknown fields, wrong types, duplicate YAML keys and duplicate scan values are all errors; inputs are never silently corrected.
- Temperature × pressure × replica parameter-space expansion; stable content-hash job IDs; reproducible, mutually distinct random seeds.
- Engine-independent `SimulationSpec` / `Protocol`; exact decimal duration → step conversion; non-integer step counts are rejected.
- Base-project-driven Jinja2 MDP templates with per-stage allowed variables; post-render MDP mapping consistency checks (temperature, pressure, timestep, step count, ensemble, seeds).
- GROMACS topology `#include` closure resolution (following grompp's relative-path rule, with no fallback to GMXLIB); only required files are packaged.
- Per-job `run.sh` (EM → NVT → NPT → Production, checkpoint hand-over, `set -euo pipefail`, GROMACS version check, no `-maxwarn`).
- `job.json` (parameters, seed usage, protocol, identity document, file SHA-256s, status), `manifest.csv`, `build_report.json`.
- Staging-directory build with atomic publish; existing results are never overwritten; `--overwrite` can only replace a previous mdflow build; base-project hash compared before and after the build.
- Example base project: 1728 SPC/E water molecules (2×2×2 translational tiling of GROMACS 2025.5 `spc216.gro` + unmodified OPLS-AA files, LGPL-2.1), with project-written topology and MDP templates; provenance record and upstream verification script.
- 120 pytest cases (118 pass; the 2 GROMACS integration tests are skipped because no GROMACS is installed).
- Documentation: README, ARCHITECTURE, CONFIGURATION, GROMACS_ADAPTER, EXAMPLE_SOURCE, VALIDATION, DEVELOPMENT.

### Known limitations
- **Not validated with GROMACS**: the development environment had no GROMACS; neither the example project nor the generated packages have been run through `grompp`/`mdrun`.
- Only `.gro` structures, a single temperature-coupling group, and isotropic pressure coupling; only temperature and pressure can be scanned.
- Fixed four-stage protocol (EM/NVT/NPT/Production); stages cannot be added or removed; no position restraints (`-r`).
- All replicas share the same initial coordinates; independence comes only from the velocity-generation and stochastic-coupling seeds.
- Includes inside `#ifdef` blocks are always treated as required.
- The applicability limits in the base project (273.15–373.15 K, 1–1000 bar, ≤ 2 fs) are conservative bounds chosen by the project, not the result of physical validation.
- The test suite was run on Python 3.13 only; Python 3.11 was only byte-compiled.
- Generated run scripts were tested only on bash 5 (with a mock `gmx`).
- Not included: simulation execution, HPC scheduling, trajectory analysis, database, Materials Studio conversion, etc. (excluded per §3.2 of the work order).
