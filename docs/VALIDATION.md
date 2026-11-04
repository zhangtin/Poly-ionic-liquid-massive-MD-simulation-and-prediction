# Validation Report (V0.1)

Date: 2026-11-03 · Development environment: Ubuntu 24.04, Python 3.13.18, PyYAML 6.0.3, pydantic 2.13.5, Jinja2 3.1.6, pytest 9.1.1, bash 5.2.21.

## 1. Validation levels

| Status | Meaning | Assigned by V0.1? |
|---|---|---|
| `CONFIG_VALIDATED` | Config, base project, templates, topology dependencies, ranges and output path all pass | Yes (`plan` / `validate`) |
| `STATIC_VALIDATED` | Generated packages are complete, checksums consistent, MDP mapping correct, script syntax correct | Yes (`build` writes it to `job.json` / `manifest.csv`) |
| `GROMPP_VALIDATED` | `gmx grompp` accepts every stage | **No** — V0.1 code never assigns it |
| `RUN_VALIDATED` | A minimal `mdrun` succeeded | **No** |

`STATIC_VALIDATED` ≠ accepted by GROMACS ≠ physically correct.

## 2. GROMACS availability

- GROMACS was not installed in the development environment; the `apt` repositories and conda channels were unreachable from it.
- Fetching the GROMACS 2025.5 source from GitHub and compiling it locally was attempted; the compile step was refused by the development environment's security policy (compiling and executing external code is not allowed).
- Therefore: **neither the base project nor the generated job packages have been validated with `grompp` or `mdrun`.** No conclusion in this report depends on actually running GROMACS.
- An optional integration test, `tests/test_gromacs_integration.py`, is provided (it runs automatically when `gmx` is found; see §5).

## 3. Automated test results

Command: `python -m pytest -q -rs`

```
118 passed, 2 skipped
SKIPPED tests/test_gromacs_integration.py: GROMACS (gmx) not installed  (×2)
```

| File | Cases | Coverage |
|---|---|---|
| `test_simulation_spec.py` | 14 | Exact duration → step conversion (including the 0.7 ns / 2 fs floating-point truncation trap), non-integer step errors, unit formatting |
| `test_config.py` | 28 | Empty lists, illegal temperatures/pressures, strings/booleans posing as numbers, unknown fields, missing fields, duplicate YAML keys, duplicate scan values (including 300 vs 300.0), out-of-model range, timestep too large, missing base project, aggregated issue reporting |
| `test_parameter_space.py` | 12 | Single- and two-parameter scans, multiple replicas, completeness of the 36-job space, stable unique job IDs, reproducible distinct in-range seeds, identity independent of project name/list order, sequence-number width |
| `test_gromacs_adapter.py` | 31 | Per-stage variable scoping, rendered MDP values, 9 kinds of broken templates (hard-coded temperature, barostat in NVT, no barostat in NPT, regenerating velocities in a checkpoint stage, missing ld-seed, hard-coded seed, no thermostat, non-isotropic coupling, EM with md), unknown/missing variables, syntax errors, unrendered markup, missing template, topology closure, missing/absolute/escaping/angle-bracket includes, include cycles, run-script structure and `bash -n` |
| `test_build.py` | 21 | 36-job acceptance, byte-identical rebuild, refusing to overwrite existing results, `--overwrite` only replacing mdflow output, invalid output paths, missing structure/topology dependency/template, modified base project, corrupt `.gro`, file-name conflicts, no leftovers after a mid-build failure, post-build tampering detection, manifest drift detection, no host absolute paths |
| `test_cli.py` | 7 | Output and exit codes of the three commands, `plan` writes nothing, `validate` re-checks an existing build |
| `test_run_script_mock.py` | 5 | Runs the generated `run.sh` against a **mock** `gmx`: call order and arguments, checkpoint hand-over, starting from any directory, empty/non-empty `MDRUN_ARGS`, error exit-code propagation (no later stage runs after a failure), handling of too-old and missing `gmx` |
| `test_gromacs_integration.py` | 2 | **Skipped** (no GROMACS) |

The mock `gmx` only checks that input files exist and writes placeholder outputs; it **does not parse MDP files or compute anything physical**. It validates the script logic, not GROMACS compatibility.

Python 3.11: a 3.11 interpreter was available but its dependencies could not be installed (no access to PyPI), so only `python3.11 -m compileall` was performed (all sources and tests compile); the test suite was actually run on 3.13 only.

## 4. 36-job acceptance (`configs/scan.example.yaml`)

```bash
mdflow build configs/scan.example.yaml      # exit 0
mdflow validate configs/scan.example.yaml   # exit 0
```

| Acceptance item (work order §17) | Result | Evidence |
|---|---|---|
| 1 All job packages generated | Pass | 36 directories, `generation_status = COMPLETE` |
| 2 Correct job count | Pass | 4 × 3 × 3 = 36 |
| 3 No missing parameter combination | Pass | `test_acceptance_36_jobs` compares all 36 (T, P, r) |
| 4 Job IDs unique and stable | Pass | 36 distinct IDs; `manifest.csv` identical across two independent builds |
| 5 Replica seeds reproducible | Pass | As above; 36 mutually distinct seeds |
| 6 MDP variables correctly filled | Pass | Mapping consistency checks + tests checking `ref-t`/`ref-p`/`gen-seed` one by one |
| 7 Correct step counts | Pass | EM 50 000 (max steps), NVT 500 000, NPT 2 500 000, Production 10 000 000 |
| 8 Complete shell script structure | Pass | Structure checks, `bash -n`, full run with mock `gmx` |
| 9 Complete topology and structure dependencies | Pass | Every job contains `conf.gro`, `topol.top` and 4 `oplsaa.ff` files with SHA-256 identical to the base project |
| 10 Correct job metadata | Pass | `job.json` consistent with the manifest and file hashes |
| 11 Correct manifest | Pass | `check_manifest` |
| 12 Base project unmodified | Pass | Whole-tree hash identical before and after build; `sha256sum -c SHA256SUMS` passes |
| 13 Identical scientific inputs on rebuild | Pass | `diff -r` of two builds (excluding `build_report.json`) shows no difference |
| 14 Automated tests pass | Pass | 118 passed, 2 skipped |
| 15 Example source and license fully recorded | Pass | EXAMPLE_SOURCE.md; upstream verification script run successfully |
| 16 Documentation consistent with code | Manually checked | — |
| GROMACS preprocessing and short run | **Not done** | No GROMACS |

Example (job_0001): T = 280 K, P = 1 bar, replica 1, job_id `ecc041ef0767d020`, seed 2005588573. Base-project hash `67956e715703cadfc0592973f87d909ea3adf4bb93992906eadc9f9ae961a12f`.

## 5. Completing GROMACS validation (on a machine with GROMACS ≥ 2021)

```bash
pip install -e ".[dev]"
python -m pytest -m gromacs -v          # or MDFLOW_GMX=/path/to/gmx python -m pytest -m gromacs
```

What the tests do: build one job with a tiny protocol (50 EM steps, 100 MD steps per dynamics stage), then (1) run `grompp` on the EM stage and require no WARNING; (2) run the full `run.sh` and check that `.gro` files for all four stages are produced. You can also simply run `bash generated_jobs/job_0001/run.sh` (the full 20 ns production stage is slow).

We recommend doing this before using the job packages for any real computation. If grompp emits NOTEs/WARNINGs, fix the base-project templates rather than adding `-maxwarn`.

## 6. Not validated

- Whether grompp accepts every MDP option and value in the templates (e.g. default-value behavior across GROMACS versions).
- Physical soundness of the protocol: whether equilibration is long enough, SPC/E behavior at 280–340 K / 1–50 bar, suitability of `tau-t`/`tau-p`.
- EM convergence for SPC/E of the initial structure obtained by tiling `spc216.gro` (an SPC-equilibrated configuration).
- The actual degree of decorrelation between replicas.
- Run-script behavior on Windows and macOS (bash 3.2); running the tests on Python 3.11/3.12.
