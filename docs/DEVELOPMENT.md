# Development

## Environment

```bash
python3 -m venv .venv && source .venv/bin/activate     # Python >= 3.11
pip install -e ".[dev]"
```

Runtime dependencies are only PyYAML, pydantic ≥ 2 and Jinja2; tests need pytest. `subprocess` is used only for `bash -n` syntax checks and the optional GROMACS integration tests, never to run simulations.

## Project layout

```text
md-automation/
├── README.md  CHANGELOG.md  pyproject.toml
├── configs/scan.example.yaml          # 36-job acceptance configuration
├── examples/base_gromacs/             # SPC/E water base project (provenance in docs/EXAMPLE_SOURCE.md)
│   ├── base_project.yaml  conf.gro  topol.top  SHA256SUMS  README.md
│   ├── mdp/{em,nvt,npt,production}.mdp.j2
│   ├── oplsaa.ff/                     # 4 upstream force-field files (unmodified)
│   ├── upstream/spc216.gro            # original upstream structure (kept for provenance)
│   ├── LICENSES/                      # GROMACS LGPL-2.1
│   └── tools/{make_conf.py, fetch_upstream.sh}
├── generated_jobs/                    # acceptance output of mdflow build (can be deleted and regenerated)
├── src/mdflow/
│   ├── __init__.py          version
│   ├── errors.py            Issue / MdflowError
│   ├── schemas.py           Pydantic models
│   ├── config.py            YAML loading, path resolution
│   ├── parameter_space.py   Parameter Space Engine
│   ├── simulation_spec.py   Simulation Specification
│   ├── template_renderer.py strict Jinja2 rendering
│   ├── gromacs_adapter.py   GROMACS Adapter
│   ├── validator.py         static checks
│   ├── plan.py              config → validated Plan
│   ├── package_writer.py    Job Package Builder
│   └── cli.py               mdflow plan / build / validate
├── tests/                             # pytest
└── docs/
```

Compared with the layout suggested in §11 of the work order, `errors.py` (a common issue type) and `plan.py` (chains the layers together for all three CLI commands) were added.

## Tests

```bash
python -m pytest -q                 # all unit/build tests; integration tests auto-skip without GROMACS
python -m pytest -m gromacs -v      # GROMACS integration tests only (needs gmx or MDFLOW_GMX)
```

All tests use a copy of the base project inside `tmp_path` (`tests/conftest.py`), so they can break it freely without affecting the repository. Regular tests need no GPU, HPC or long MD runs; the whole suite takes about 15 seconds.

## Modifying the base project

1. Edit the files;
2. Regenerate the checksums in `examples/base_gromacs/`:
   ```bash
   find . -type f ! -name SHA256SUMS ! -path '*/__pycache__/*' | sed 's|^\./||' | sort | xargs sha256sum > SHA256SUMS
   ```
3. Run `mdflow validate configs/scan.example.yaml`.

Note: any change to the descriptor, structure, topology closure or templates changes the base-project hash and therefore every job ID and seed (by design). `README.md`, `tools/`, `upstream/` and `LICENSES/` are not part of the identity hash.

## Coding conventions

- Physical-quantity fields carry a unit suffix (`temperature_K`, `timestep_fs`, `duration_ns`) and use `Decimal` internally.
- Check functions return `list[Issue]`; collect as many issues as possible before raising `MdflowError`.
- GROMACS-specific content belongs only in `gromacs_adapter.py`.
- Generated files must be deterministic: no timestamps, host names or absolute paths (these go only into `build_report.json`).

## Extension suggestions

- **New scan variables** (e.g. other scalar MDP parameters): `ScanConfig` → `ScanPoint` / `SimulationSpec` → `identity_document` → `gromacs_adapter.ALLOWED_VARS`, `stage_context`, `check_rendered_mdp`. Variables that change structure/composition belong to the V0.3 System Builder and should not be implemented through templates.
- **A grompp validation command**: if needed later, add `mdflow check-grompp`, which runs `grompp` for each job and upgrades the `job.json` status to `GROMPP_VALIDATED`; note that it needs the previous stage's output, so stages other than EM can only be validated during an actual run.
- **Execution management (V0.4)**: use `manifest.csv` as the job queue, and verify via `job.json.files` that inputs have not been tampered with before submitting.
