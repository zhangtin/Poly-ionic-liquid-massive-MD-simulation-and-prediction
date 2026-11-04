# Configuration

mdflow uses two YAML files:

1. **Scan configuration** (written by the user, e.g. `configs/scan.example.yaml`).
2. **Base-project descriptor** `base_project.yaml` (in the base project's root directory).

Both are validated in strict mode: unknown fields, wrong types (including strings or booleans in place of numbers), `NaN/inf`, and duplicate YAML keys are all errors. **mdflow never silently corrects input.**

## 1. Scan configuration

All relative paths are resolved against **the directory containing that YAML file**, independent of the current working directory.

| Field | Type | Unit | Constraints | Description |
|---|---|---|---|---|
| `project` | str | — | `^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$` | Experiment name, written to `job.json.experiment_id`; does **not** affect job IDs |
| `base_project` | str | — | Must be a directory containing `base_project.yaml` | Path to the base project |
| `scan.temperature_K` | list[number] | K | Non-empty; each value > 0; no duplicates; within the base project's `limits.temperature_K` | Thermostat reference temperature (and NVT velocity-generation temperature) |
| `scan.pressure_bar` | list[number] | bar | Non-empty; each value > 0; no duplicates; within `limits.pressure_bar` | Isotropic barostat reference pressure |
| `scan.replicas` | int | — | 1–1000 | Number of independent replicas per (T, P) |
| `simulation.timestep_fs` | number | fs | > 0; ≤ `limits.max_timestep_fs` | Integration timestep (all stages except EM) |
| `simulation.em_steps` | int | steps | ≥ 1 | Maximum number of energy-minimization steps (no time conversion) |
| `simulation.nvt_ns` | number | ns | > 0; must be an integer multiple of the timestep | NVT equilibration length |
| `simulation.npt_ns` | number | ns | Same as above | NPT equilibration length |
| `simulation.production_ns` | number | ns | Same as above | Production length |
| `output.directory` | str | — | See below | Output directory |

### 1.1 Numeric rules

- Integers and floats are equivalent: `300` and `300.0` are the same temperature, so `[300, 300.0]` raises `DUPLICATE_VALUE`.
- Steps = duration (ns) × 10⁶ / timestep (fs), computed exactly in decimal (`Decimal`). **If it does not divide exactly, `NON_INTEGER_STEPS` is raised**; nothing is rounded. Example: 20 ns / 2 fs = 10 000 000 steps; 1 ns / 1.5 fs → error.
- Normalized values are written into the MDP files: `300.0` → `300`, 2 fs → `dt = 0.002`.

### 1.2 Output directory rules

| Situation | Result |
|---|---|
| Does not exist | Created |
| Exists and is empty | Used |
| Exists and is not empty | `OUTPUT_EXISTS` (`build` refuses) |
| Not empty + `--overwrite` + contains an mdflow `build_report.json` | Replaced after the new build succeeds |
| Not empty + `--overwrite` + not an mdflow build | `OUTPUT_NOT_MDFLOW`, refused |
| Overlaps the base project in either direction, contains the config file, is a regular file, or is not writable | `OUTPUT_PATH_INVALID` |

### 1.3 Example

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

Single-parameter scan: give the other list a single element, e.g. `pressure_bar: [1]`.

## 2. Base-project descriptor `base_project.yaml`

| Field | Description |
|---|---|
| `name` | Base project name (same rule as `project`) |
| `description` | Optional description |
| `structure` | Initial structure file in the base project root; V0.1 supports `.gro` only |
| `topology` | Main topology file in the root; its `#include` closure is packaged |
| `templates.em/nvt/npt/production` | Per-stage Jinja2 MDP templates (relative paths, must be inside the base project) |
| `gromacs.min_version` | Minimum GROMACS major version required to run (e.g. `"2021"`); written into `run.sh` and checked at run time |
| `gromacs.developed_against` | Optional; the version used as reference during development |
| `limits.temperature_K` | `[min, max]`; scanned temperatures must lie in this range |
| `limits.pressure_bar` | `[min, max]` |
| `limits.max_timestep_fs` | Largest allowed timestep |

The values for the example project are in `examples/base_gromacs/base_project.yaml`: 273.15–373.15 K, 1–1000 bar, ≤ 2 fs. These are **conservative bounds chosen by the project for a test system**, not a statement about the physical applicability of SPC/E.

If an optional `SHA256SUMS` file (in `sha256sum` format) is present, `plan/validate/build` verify every entry and raise `BASE_PROJECT_MODIFIED` on mismatch.

## 3. Template variables

| Variable | Meaning | Example | Allowed in stages | Required in stages |
|---|---|---|---|---|
| `nsteps` | Step count of the stage | `500000` | all | all |
| `dt_ps` | Timestep (ps) | `0.002` | nvt, npt, production | nvt, npt, production |
| `temperature_K` | Scan temperature | `300` | nvt, npt, production | nvt, npt, production |
| `pressure_bar` | Scan pressure | `10` | npt, production | npt; in production, `ref-p` is checked after rendering if `pcoupl ≠ no` |
| `random_seed` | Job seed | `2005588573` | nvt, npt, production | none (but see the seed checks in GROMACS_ADAPTER.md §4) |

## 4. Error codes

| Category | Codes |
|---|---|
| Files / YAML | `FILE_NOT_FOUND` `NOT_A_FILE` `FILE_UNREADABLE` `YAML_PARSE_ERROR` `YAML_DUPLICATE_KEY` `SCHEMA_ERROR` |
| Scan / protocol | `DUPLICATE_VALUE` `NON_INTEGER_STEPS` `TEMPERATURE_OUT_OF_RANGE` `PRESSURE_OUT_OF_RANGE` `TIMESTEP_TOO_LARGE` |
| Base project | `BASE_PROJECT_MISSING` `BASE_DESCRIPTOR_MISSING` `BASE_PROJECT_MODIFIED` `SHA256SUMS_INVALID` `STRUCTURE_MISSING` `STRUCTURE_INVALID` `STRUCTURE_UNREADABLE` `STRUCTURE_UNSUPPORTED` `FILENAME_CONFLICT` |
| Topology dependencies | `DEPENDENCY_MISSING` `DEPENDENCY_ABSOLUTE` `DEPENDENCY_OUTSIDE_BASE` `DEPENDENCY_UNSUPPORTED` `DEPENDENCY_UNREADABLE` |
| Templates | `TEMPLATE_MISSING` `TEMPLATE_UNREADABLE` `TEMPLATE_OUTSIDE_BASE` `TEMPLATE_SYNTAX_ERROR` `TEMPLATE_UNKNOWN_VARIABLE` `TEMPLATE_MISSING_VARIABLE` `TEMPLATE_UNDEFINED_VARIABLE` `TEMPLATE_UNRENDERED` |
| MDP mapping | `MDP_SYNTAX_ERROR` `MDP_DUPLICATE_KEY` `MDP_MISSING_KEY` `MDP_BAD_VALUE` `MDP_MAPPING_MISMATCH` `MDP_WRONG_INTEGRATOR` `MDP_NO_THERMOSTAT` `MDP_ENSEMBLE_MISMATCH` `MDP_UNSUPPORTED` `MDP_DISCARDS_STATE` `MDP_UNSEEDED` |
| Output / packages | `OUTPUT_EXISTS` `OUTPUT_NOT_MDFLOW` `OUTPUT_PATH_INVALID` `PACKAGE_INCOMPLETE` `PACKAGE_MISSING` `PACKAGE_MODIFIED` `SCRIPT_INVALID` `SCRIPT_SYNTAX_ERROR` `SCRIPT_ABSOLUTE_PATH` `BAD_FILENAME` `BAD_GMX_VERSION` `METADATA_INVALID` `METADATA_MISMATCH` `MANIFEST_MISSING` `MANIFEST_INVALID` `MANIFEST_MISMATCH` `JOB_ID_COLLISION` |

CLI exit codes: 0 success; 1 one or more of the issues above; 2 command-line usage error.
