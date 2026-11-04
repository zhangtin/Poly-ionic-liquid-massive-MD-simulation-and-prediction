# MD Automation Platform — V0.1: GROMACS Script Builder

> **Python owns the workflow. GROMACS owns the numerical simulation.**

Starting from a YAML parameter-scan configuration and a fixed GROMACS base project, `mdflow` generates one **complete, self-contained, reproducible** GROMACS job package per (temperature, pressure, replica) combination: per-stage MDP files, structure and topology dependencies, a Bash run script, a random seed, and metadata.

V0.1 **only generates and statically validates** job packages. It does not run simulations, schedule HPC jobs, or analyze results.

## Installation

Requires Python ≥ 3.11.

```bash
cd md-automation
pip install -e .            # dependencies: PyYAML, pydantic>=2, Jinja2
pip install -e ".[dev]"     # also installs pytest
```

Running the generated job packages requires GROMACS ≥ 2021 (`mdflow` itself does not need GROMACS).

## Quick start

```bash
mdflow plan     configs/scan.example.yaml   # validate the config and list the 36 jobs; writes nothing
mdflow build    configs/scan.example.yaml   # generate generated_jobs/
mdflow validate configs/scan.example.yaml   # check config/base project/templates/dependencies; re-check an existing build
```

Running a single job (on a machine with GROMACS):

```bash
bash generated_jobs/job_0001/run.sh
GMX=gmx_mpi MDRUN_ARGS="-ntomp 8 -pin on" bash generated_jobs/job_0001/run.sh
```

## Example configuration

```yaml
project: water_scan_001
base_project: "../examples/base_gromacs"   # relative paths are resolved against this YAML file's directory
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

4 × 3 × 3 = 36 jobs. All fields are described in [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

## Output

```text
generated_jobs/
├── manifest.csv          # one row per job
├── build_report.json     # build time, host, config hash, ... (the only non-deterministic file)
├── job_0001/
│   ├── conf.gro  topol.top  oplsaa.ff/   # byte-for-byte copies from the base project (only files the topology actually #includes)
│   ├── em.mdp  nvt.mdp  npt.mdp  production.mdp
│   ├── run.sh            # EM → NVT → NPT → Production
│   └── job.json          # parameters, seed, step counts, file SHA-256s, validation status
└── ...
```

Rebuilding from the same input produces byte-identical files, except `build_report.json`.

## Documentation

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Four-layer architecture, module boundaries, data flow, extension principles |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | YAML fields, units, limits, error codes |
| [docs/GROMACS_ADAPTER.md](docs/GROMACS_ADAPTER.md) | Parameter mapping, MDP template mechanism, run-script rules, replica independence |
| [docs/EXAMPLE_SOURCE.md](docs/EXAMPLE_SOURCE.md) | Example project provenance, license, checksums, modification record |
| [docs/VALIDATION.md](docs/VALIDATION.md) | Test method, actual results, what was not validated |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Development environment, project layout, tests, extension suggestions |
| [CHANGELOG.md](CHANGELOG.md) | V0.1 contents and known limitations |

## Important notes

- `STATIC_VALIDATED` means a job package is **complete and internally consistent**. It does **not** mean GROMACS `grompp` has accepted it, nor that the physical model is correct.
- The V0.1 development environment had **no GROMACS**. The generated job packages have **not** been validated with `grompp` or `mdrun`; see [docs/VALIDATION.md](docs/VALIDATION.md).
- The example scan conditions exist to test the Script Builder; they are not validated research conditions.
