# GROMACS Adapter

All GROMACS-specific logic lives in `src/mdflow/gromacs_adapter.py`.

## 1. Mechanism: base-project-driven template generation

The base project provides four Jinja2 MDP templates. mdflow replaces **only** the declared variables (see CONFIGURATION.md §3); every other scientific parameter in the templates (cut-offs, electrostatics method, coupling constants, output frequencies, ...) is kept as-is.

Rendering uses `StrictUndefined`, with four checks before and after rendering:

1. The template references a variable it is not allowed to use → `TEMPLATE_UNKNOWN_VARIABLE` (e.g. the EM template references `temperature_K`, or the NVT template references `pressure_bar`);
2. The template does not reference a required variable → `TEMPLATE_MISSING_VARIABLE` (otherwise a scanned value would be silently ignored);
3. A value is missing at render time → `TEMPLATE_UNDEFINED_VARIABLE`;
4. `{{ }}`, `{% %}` or `{# #}` remains in the output → `TEMPLATE_UNRENDERED`.

## 2. Parameter mapping

| Generic spec (`SimulationSpec`) | Template variable | Example MDP keys |
|---|---|---|
| `temperature_K` | `temperature_K` | `ref-t`, `gen-temp` |
| `pressure_bar` | `pressure_bar` | `ref-p` |
| `protocol.timestep_fs` / 1000 | `dt_ps` | `dt` |
| `StageSpec.steps` | `nsteps` | `nsteps` |
| `random_seed` | `random_seed` | `gen-seed`, `ld-seed` |

### Post-render mapping consistency check (`check_rendered_mdp`)

Templates are just text; Jinja2 cannot tell if a variable was put under the wrong key or inside a comment. So after rendering, the MDP is parsed (keys case-insensitive, `-`/`_` equivalent, duplicate keys rejected) and checked stage by stage:

| Stage | Check |
|---|---|
| All | `nsteps` = the stage's step count |
| EM | `integrator` ∈ {steep, cg, l-bfgs} |
| Dynamics stages | `integrator` ∈ {md, md-vv, md-vv-avek, sd, bd}; `dt` = timestep; a thermostat (or sd/bd integrator) is present and `ref-t` = scan temperature; exactly one `tc-grps` |
| NVT | `pcoupl = no` |
| NPT | `pcoupl ≠ no` |
| Stages with pressure coupling | `pcoupltype = isotropic`; `ref-p` = scan pressure (single value) |
| NPT, Production | `gen-vel = yes` is not allowed (it would discard the velocities from the checkpoint) |
| `gen-vel = yes` | `gen-temp` = scan temperature; `gen-seed` must be set |
| Stochastic coupling/integrators (V-rescale, Andersen, C-rescale, sd, bd) | `ld-seed` must be set (otherwise GROMACS picks a random seed and results are not reproducible) |
| Any `gen-seed`/`ld-seed` present | Must equal the job's `random_seed` (prevents templates from hard-coding the same seed) |

The production ensemble is **inherited from the base project**: mdflow determines it from the rendered `pcoupl` (NPT for the example project) and records it in `job.json`.

V0.1 does not support multiple temperature-coupling groups or anisotropic/semi-isotropic pressure scans; these raise `MDP_UNSUPPORTED`.

## 3. MDP protocol of the example project

Written by this project (parameters chosen according to the mdp option descriptions in the GROMACS reference manual); **not validated by running GROMACS**:

| | EM | NVT | NPT | Production |
|---|---|---|---|---|
| integrator | steep (emtol 1000, emstep 0.01) | md | md | md |
| Start from | `conf.gro` | `em.gro`, `gen-vel=yes` | `nvt.gro` + `nvt.cpt`, `continuation=yes` | `npt.gro` + `npt.cpt`, `continuation=yes` |
| Thermostat | — | V-rescale, τ_T = 0.1 ps | V-rescale, 0.1 ps | V-rescale, 0.1 ps |
| Barostat | — | none | C-rescale isotropic, τ_P = 2 ps, κ = 4.5×10⁻⁵ bar⁻¹ | same as NPT |
| Seeds | — | `gen-seed`, `ld-seed` | `ld-seed` | `ld-seed` |

Common settings: Verlet cut-off scheme, PME, rcoulomb = rvdw = 1.0 nm, DispCorr = EnerPres, `constraints = h-bonds` (pure SPC/E water is constrained by SETTLE from `spce.itp`, so this option has no effect for this system). C-rescale requires GROMACS ≥ 2021.

## 4. Random seeds and replica independence

- Seed = `sha256("mdflow-seed-v1|<attempt>|" + identity)`, first 64 bits mapped onto [1, 2³¹−1] (`gen-seed` is a 32-bit integer, `ld-seed` 64-bit, and −1 means "let GROMACS choose", so it is avoided). Seeds are guaranteed to be distinct across the whole scan; in the unlikely event of a collision, `attempt` is incremented deterministically in job order, so the same input still yields the same seeds.
- **The replica number itself introduces no randomness.** In the example project, replicas differ because of:
  1. NVT stage `gen-vel = yes, gen-seed = <seed>`: different Maxwell–Boltzmann initial velocities;
  2. `ld-seed = <seed>` in every dynamics stage: different noise in the V-rescale thermostat and C-rescale barostat.
- **Limitation**: all replicas start from the same coordinates (`conf.gro`), and the EM stage is deterministic, so replicas are identical until NVT begins. Statistical independence of replicas relies on the initial velocities and stochastic coupling decorrelating the trajectories during equilibration; mdflow does not assess this.
- If a base project uses no random initialization and no stochastic coupling, different seeds will **not** produce different trajectories, and replica independence cannot be claimed on that basis. mdflow raises an error when randomness is enabled without a seed, but does not require the base protocol to contain randomness.
- In addition, the order of floating-point reductions in GROMACS with multiple threads/GPUs can make trajectories from identical inputs differ bit-wise; mdflow guarantees reproducible **inputs**, not bit-identical trajectories.

## 5. Topology dependencies (`#include`)

`resolve_topology_includes` mirrors the behavior of the GROMACS preprocessor (`src/gromacs/gmxpreprocess/gmxcpp.cpp`): a quoted include is looked up relative to **the directory of the file that contains it**. Examples: `"oplsaa.ff/forcefield.itp"` in `topol.top`, and `"ffnonbonded.itp"` in `forcefield.itp` (resolved to `oplsaa.ff/ffnonbonded.itp`).

When GROMACS cannot find a file there it goes on to search `-I` paths and the installed library (GMXLIB / `share/top`); mdflow **deliberately does not**: a job package must be self-contained, otherwise on another machine (with a different GROMACS version) different force-field files could be picked up silently. Therefore:

| Situation | Code |
|---|---|
| Not found inside the base project | `DEPENDENCY_MISSING` |
| Absolute path | `DEPENDENCY_ABSOLUTE` |
| Path escapes the base project (`../`) | `DEPENDENCY_OUTSIDE_BASE` |
| `#include <...>` or other syntax | `DEPENDENCY_UNSUPPORTED` |

Includes inside `#ifdef` branches are also treated as required (conservative; the active branch is only known when grompp runs). Only files in the include closure are copied (in the example, only 4 files from `oplsaa.ff`), preserving their relative paths.

## 6. Run script `run.sh`

Generation rules (corresponding to §10 of the work order):

1. `#!/usr/bin/env bash` + `set -euo pipefail`: any failing command aborts immediately with its exit code;
2. `cd "$(dirname "${BASH_SOURCE[0]}")"`: independent of the caller's working directory;
3. Only relative file names inside the job directory; no build-host absolute paths (checked at build time, `SCRIPT_ABSOLUTE_PATH`);
4. No `-maxwarn`;
5. `grompp`/`mdrun` in sequence: EM → NVT (`-c em.gro`) → NPT (`-c nvt.gro -t nvt.cpt`) → Production (`-c npt.gro -t npt.cpt`); checkpoints carry coordinates, velocities and coupling state;
6. `grompp -po <stage>_mdout.mdp`, so stages do not overwrite each other's `mdout.mdp`;
7. Before running, checks that `GMX` exists (exit 127 if not) and that its major version is ≥ `min_version` (exit 1 otherwise);
8. Environment variables: `GMX` (default `gmx`), `MDRUN_ARGS` (appended to every `mdrun` call, e.g. `"-ntomp 8 -pin on"`). An empty `MDRUN_ARGS` is expanded with `${arr[@]+"${arr[@]}"}` to avoid errors under `set -u` in older bash (e.g. 3.2 shipped with macOS) (tested on bash 5 only).

V0.1 only generates the scripts; it does not execute them. Scripts are syntax-checked with `bash -n` at build time.
