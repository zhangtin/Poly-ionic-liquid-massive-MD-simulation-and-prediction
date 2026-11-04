# Architecture

## 1. Four-layer structure

```text
            scan.yaml                    base_project.yaml + files
                │                                   │
        config.py / schemas.py  ←──────────────────┘   (loading + schema checks)
                │
                ▼
┌───────────────────────────────┐
│ Parameter Space Engine        │  parameter_space.py
│  Cartesian product · dupes    │
│  replicas · job ID · seeds    │
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ Simulation Specification      │  simulation_spec.py
│  quantities with units        │
│  (Decimal) · Protocol ·       │
│  StageSpec · step counts      │
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ GROMACS Adapter               │  gromacs_adapter.py (+ template_renderer.py)
│  variable mapping · MDP       │
│  render & check · #include    │
│  resolution · run.sh          │
└───────────────┬───────────────┘
                ▼
┌───────────────────────────────┐
│ Job Package Builder           │  package_writer.py
│  job dirs · copy dependencies │
│  job.json · manifest ·        │
│  atomic publish               │
└───────────────────────────────┘

Cross-cutting: validator.py (static checks), plan.py (chains the above into one validated Plan), cli.py
```

## 2. Module responsibilities

| Module | Responsible for | Not responsible for |
|---|---|---|
| `schemas.py` | Pydantic models: fields, types, positive values, no unknown fields | Cross-field / file-system checks |
| `config.py` | YAML parsing (with duplicate-key detection), path resolution, loading the base-project descriptor | Business rules |
| `parameter_space.py` | Expanding the scan space, rejecting duplicate values, replica numbering, job IDs, seeds | Any GROMACS file |
| `simulation_spec.py` | Engine-independent simulation definition; unit conversion; duration → steps (exact-division check) | GROMACS key names |
| `template_renderer.py` | Strict Jinja2 rendering (unknown variables, required variables, undefined variables, leftover markup) | MDP semantics |
| `gromacs_adapter.py` | Spec → MDP variable mapping; MDP parsing and mapping-consistency checks; topology `#include` resolution; `.gro` check; `run.sh` generation | Writing files |
| `package_writer.py` | Staging-directory build, copying, writing MDP/script/metadata/manifest, publishing, overwrite protection, post-build re-verification | Parameter expansion |
| `validator.py` | Static checks of base project, ranges, output path, job packages, metadata, manifest | Running GROMACS |
| `plan.py` | Collects all configuration-level issues and reports them together; produces a `Plan` | — |
| `cli.py` | `plan` / `build` / `validate` | `run` / `submit` / `analyze` (not implemented in V0.1) |

Dependencies point one way only: `parameter_space` and `simulation_spec` do not import `gromacs_adapter`. All GROMACS-specific knowledge (key names, `-`/`_` equivalence, grompp's include search order, seed keys, command lines) lives in `gromacs_adapter.py`.

## 3. Data flow (`mdflow build`)

1. `load_config` → `ScanFile`; `load_base_project` → `BaseProjectDescriptor`.
2. `check_base_project`: structure file, topology include closure, template variables, file-name conflicts, `SHA256SUMS`.
3. `Protocol.from_config`: duration → steps; non-integer counts are errors.
4. `expand`: T × P × replica; duplicate values are errors.
5. `check_scan_limits`, `check_output_path`. All issues from steps 2–5 are **collected and raised together**.
6. `base_project_sha256` + `Protocol.fingerprint` + parameters + builder version → job ID and seed.
7. Each job package is written inside `.<output>.mdflow-staging-*`: copy dependencies → render MDPs → generate `run.sh` → static checks → write `job.json`.
8. Write and cross-check `manifest.csv`; compare whole-tree hashes of the base project before and after; write `build_report.json`.
9. Only when everything passes is the staging directory moved into place with `os.replace`. Any failure deletes the staging directory, leaving no partial output.

## 4. Identity and determinism

- **Job ID** = `sha256(canonical_json(identity))[:16]`, where `identity` contains: builder version, base-project content hash (descriptor + structure + topology closure + templates), protocol fingerprint (timestep, per-stage step counts), temperature, pressure, replica number. The full `identity` is written into `job.json` so the ID can be recomputed independently.
- Project name, output path, and list order are **not** part of the identity: renaming a scan or reordering its lists does not change the scientific identity of its jobs.
- Sequence numbers such as `job_0001` exist for readability only; they are not scientific identities.
- Build time, host, and absolute paths are written only into `build_report.json`.

## 5. Extension principles (towards V0.2+)

- New scan variables: add them as unit-suffixed fields in `ScanConfig` and `SimulationSpec`, then map them in `gromacs_adapter.ALLOWED_VARS / stage_context / check_rendered_mdp`. The parameter-space engine does not need to know about GROMACS.
- V0.2 (configuration management) can replace templates with MDPs generated in Python by replacing the implementation of `render_stages`; `job.json`, identity and packaging stay unchanged.
- V0.4 (execution management) should read `manifest.csv` / `job.json` rather than re-deriving parameters; `ValidationStatus` already reserves `GROMPP_VALIDATED` and `RUN_VALIDATED`.
- Multi-engine support: add an adapter parallel to `gromacs_adapter.py` and reuse `Plan`.
