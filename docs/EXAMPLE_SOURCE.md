# Example Project Provenance

## 1. Selection and search

The work order asks for a simple liquid-water system, preferably from official GROMACS sources. Candidates considered:

| Candidate | Decision |
|---|---|
| `share/top/spc216.gro` shipped with the GROMACS distribution (216 pre-equilibrated SPC waters) and the `oplsaa.ff` force field | **Adopted.** Official source, distributed with GROMACS under LGPL-2.1, redistributable; this is the default solvent box used by `gmx solvate` |
| MDP files from public tutorials (e.g. J. Lemkul's GROMACS Tutorials) | **Not adopted.** No explicit redistribution license could be found |
| A complete official "liquid water EM/NVT/NPT/MD" example project | No ready-made official project including all MDP files was found |

Therefore, following the fallback in §4.2 of the work order: **structure and force field are taken unmodified from the official distribution; the topology and MDP templates were written by this project**, and the origin of each file is stated below. This project is not an official GROMACS example project.

## 2. Upstream source

- Project: GROMACS (https://www.gromacs.org)
- Repository: https://github.com/gromacs/gromacs (official GitHub mirror; the primary repository is https://gitlab.com/gromacs/gromacs)
- Version: tag `v2025.5`, commit `70126eecad7830d2062cdc7b0c1b180b92c98c2a`
- Retrieved: 2026-11-03
- Method: `git clone --depth 1 --branch v2025.5`. `examples/base_gromacs/tools/fetch_upstream.sh` re-fetches the files with a sparse checkout and verifies them (this script was actually run in the development environment; all 6 files verified OK).

## 3. License

GROMACS is released under the **GNU LGPL v2.1 (or any later version)**, and the force-field and structure data under `share/top` are distributed with it. This project includes the unmodified `COPYING` text at `examples/base_gromacs/LICENSES/GROMACS-COPYING-LGPL-2.1.txt`. All copied files are unmodified and keep their original header comments (including the OPLS-AA literature references).

When publishing results, users should cite, as is customary, GROMACS, OPLS-AA (see the header of `oplsaa.ff/forcefield.itp`), and the SPC/E water model (H. J. C. Berendsen, J. R. Grigera, T. P. Straatsma, *J. Phys. Chem.* **91**, 6269 (1987)).

## 4. Per-file provenance and checksums

### 4.1 Upstream files (byte-for-byte copies, unmodified)

| Path in this project | Upstream path | SHA-256 |
|---|---|---|
| `oplsaa.ff/forcefield.itp` | `share/top/oplsaa.ff/forcefield.itp` | `6eb8f0d08684e1ac6f525bb323eae75ed197b2980ddfde975a24ca1a8c931d06` |
| `oplsaa.ff/ffnonbonded.itp` | `share/top/oplsaa.ff/ffnonbonded.itp` | `fdf072dac9900c039b58e21323ce621b2112dc86c46a4b5e49e1398ae5d3b9f0` |
| `oplsaa.ff/ffbonded.itp` | `share/top/oplsaa.ff/ffbonded.itp` | `145e6924f52fae7e93108fa3d674f31a53aea10c80b13dd89abf0b011adfd4fa` |
| `oplsaa.ff/spce.itp` | `share/top/oplsaa.ff/spce.itp` | `e733446e1c7bcf42e21ba2ff84cc57d8d603210218faa5203b3f078026d80682` |
| `upstream/spc216.gro` | `share/top/spc216.gro` | `dcb2c65552058a5083fddc5a4bb3187b1eac6c46e3acf038643ec2ec9f147620` |
| `LICENSES/GROMACS-COPYING-LGPL-2.1.txt` | `COPYING` | `b634ab5640e258563c536e658cad87080553df6f34f62269a21d554844e58bfe` |

Only the 4 force-field files the topology actually needs were copied, not the whole `oplsaa.ff` directory (which also contains amino-acid databases and other files this system does not need).

### 4.2 Files created or derived by this project

| File | Description |
|---|---|
| `conf.gro` | **Derived.** `tools/make_conf.py` tiles `spc216.gro` (1.86206 nm box) 2×2×2 by translation along the three axes, giving 1728 water molecules in a 3.72412 nm cubic box. Coordinates are only shifted by whole box lengths; no molecule is removed or perturbed; residues/atoms are renumbered; the title line records the origin. Reason: a single 216-water box is smaller than twice the 1.0 nm cut-off and cannot be used directly. Post-generation checks: minimum periodic O–O distance 0.251 nm, density 1.0008 g/cm³ (using 18.015 g/mol). |
| `topol.top` | Newly written. `#include`s OPLS-AA and `spce.itp`; `SOL 1728`. |
| `mdp/em.mdp.j2`, `nvt.mdp.j2`, `npt.mdp.j2`, `production.mdp.j2` | Newly written Jinja2 templates; the protocol is described in `docs/GROMACS_ADAPTER.md` §3. Parameters follow common practice and were chosen according to the mdp option descriptions in the GROMACS reference manual; **not validated with grompp/mdrun**. |
| `base_project.yaml` | mdflow base-project descriptor, including the project-chosen applicability range (273.15–373.15 K, 1–1000 bar, ≤ 2 fs). |
| `tools/make_conf.py`, `tools/fetch_upstream.sh` | Helper scripts. |
| `SHA256SUMS`, `README.md` | Integrity reference and description. |

Note: `spc216.gro` itself is a configuration equilibrated with the SPC model. SPC/E has the same geometry as SPC (O–H 0.1 nm, H–O–H 109.47°) and differs only in its charges, so it is usable as a starting configuration for SPC/E, but it must go through EM and equilibration.

## 5. GROMACS version compatibility

- The force-field and structure files come from GROMACS 2025.5; their format has been stable in versions since 2018.
- The MDP files use the C-rescale barostat (introduced in GROMACS 2021), so `base_project.yaml` specifies `min_version: "2021"` and `run.sh` checks the major version at run time.
- **Not actually run on any GROMACS version** (no GROMACS in the development environment; see VALIDATION.md).

## 6. Run-validation status

| Item | Status |
|---|---|
| File structure, dependency closure, `.gro` format, checksums | Done (static) |
| `gmx grompp` preprocessing | **Not done** |
| Minimal `mdrun` run | **Not done** |
