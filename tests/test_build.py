"""Job Package Builder: 36-job acceptance build, determinism, safety checks."""
import csv
import json
import os
from pathlib import Path

import pytest
import yaml

from mdflow.errors import MdflowError
from mdflow.package_writer import build, snapshot_tree, verify_output
from mdflow.plan import make_plan
from mdflow.validator import ValidationStatus, sha256_file

from conftest import tree_digest


def _build(cfg_path, **kw):
    plan = make_plan(cfg_path, for_build=True, overwrite=kw.get("overwrite", False))
    return plan, build(plan, **kw)


def test_acceptance_36_jobs(write_config, base_dir, tmp_path):
    before = snapshot_tree(base_dir)
    plan, res = _build(write_config())
    out = res.output_dir
    assert res.n_jobs == 36

    # every package exists and is complete
    jobs = sorted(p for p in out.iterdir() if p.is_dir())
    assert [p.name for p in jobs] == [f"job_{i:04d}" for i in range(1, 37)]
    for jd in jobs:
        names = {p.relative_to(jd).as_posix() for p in jd.rglob("*") if p.is_file()}
        assert names == {
            "conf.gro", "topol.top", "em.mdp", "nvt.mdp", "npt.mdp", "production.mdp", "run.sh", "job.json",
            "oplsaa.ff/forcefield.itp", "oplsaa.ff/ffnonbonded.itp", "oplsaa.ff/ffbonded.itp", "oplsaa.ff/spce.itp",
        }
        assert os.access(jd / "run.sh", os.X_OK)
        # scientific inputs are byte-identical copies of the base project
        for rel in ("conf.gro", "topol.top", "oplsaa.ff/ffbonded.itp"):
            assert sha256_file(jd / rel) == sha256_file(base_dir / rel)

    # manifest: complete, unique, consistent with job.json
    rows = list(csv.DictReader((out / "manifest.csv").open()))
    assert len(rows) == 36
    combos = {(r["temperature_K"], r["pressure_bar"], r["replica"]) for r in rows}
    assert combos == {(t, p, r) for t in ("280", "300", "320", "340") for p in ("1", "10", "50") for r in ("1", "2", "3")}
    assert len({r["job_id"] for r in rows}) == 36
    assert len({r["random_seed"] for r in rows}) == 36
    for r in rows:
        meta = json.loads((out / r["directory"] / "job.json").read_text())
        assert meta["job_id"] == r["job_id"]
        assert meta["experiment_id"] == "water_scan_001"
        assert meta["random_seed"] == int(r["random_seed"])
        assert meta["parameters"] == {
            "temperature_K": int(r["temperature_K"]), "pressure_bar": int(r["pressure_bar"]), "replica": int(r["replica"]),
        }
        assert meta["validation_status"] == r["validation_status"] == "STATIC_VALIDATED"
        assert [s["steps"] for s in meta["protocol"]["stages"]] == [50000, 500000, 2500000, 10000000]
        nvt = (out / r["directory"] / "nvt.mdp").read_text()
        assert f"gen-seed                = {r['random_seed']}\n" in nvt
        assert f"ref-t                   = {r['temperature_K']}\n" in nvt
        npt = (out / r["directory"] / "npt.mdp").read_text()
        assert f"ref-p                   = {r['pressure_bar']}\n" in npt

    report = json.loads((out / "build_report.json").read_text())
    assert report["n_jobs"] == 36 and report["validation_status"] == "STATIC_VALIDATED"
    assert report["gromacs_validation"].startswith("NOT_PERFORMED")

    # base project untouched, no staging debris
    assert snapshot_tree(base_dir) == before
    assert not [p for p in tmp_path.iterdir() if "staging" in p.name or "mdflow-old" in p.name]
    # the build passes a full re-verification
    assert verify_output(plan) == []


def test_rebuild_is_deterministic(write_config, tmp_path):
    _build(write_config("a.yaml", output={"directory": "out_a"}))
    _build(write_config("b.yaml", output={"directory": "out_b"}))
    a = tree_digest(tmp_path / "out_a", exclude={"build_report.json"})
    b = tree_digest(tmp_path / "out_b", exclude={"build_report.json"})
    assert a.keys() == b.keys() and a == b


def test_existing_output_is_not_overwritten(write_config, tmp_path):
    cfg = write_config()
    _build(cfg)
    marker = tmp_path / "out" / "job_0001" / "em.edr"
    marker.write_text("results from a real run")
    with pytest.raises(MdflowError) as exc:
        _build(cfg)
    assert exc.value.codes == {"OUTPUT_EXISTS"}
    assert marker.read_text() == "results from a real run"


def test_overwrite_only_replaces_previous_mdflow_builds(write_config, tmp_path):
    cfg = write_config()
    _build(cfg)
    _build(cfg, overwrite=True)  # allowed: previous mdflow build
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "thesis.tex").write_text("precious")
    with pytest.raises(MdflowError) as exc:
        _build(write_config("f.yaml", output={"directory": "foreign"}), overwrite=True)
    assert exc.value.codes == {"OUTPUT_NOT_MDFLOW"}
    assert (foreign / "thesis.tex").read_text() == "precious"


def test_empty_existing_output_dir_is_fine(write_config, tmp_path):
    (tmp_path / "out").mkdir()
    _, res = _build(write_config())
    assert res.n_jobs == 36


@pytest.mark.parametrize(
    "directory",
    ["base", "base/generated", ".", "scan.yaml"],
)
def test_invalid_output_paths(write_config, directory):
    cfg = write_config(output={"directory": directory})
    with pytest.raises(MdflowError) as exc:
        make_plan(cfg, for_build=True)
    assert "OUTPUT_PATH_INVALID" in exc.value.codes


def test_missing_structure(write_config, base_dir):
    (base_dir / "conf.gro").unlink()
    with pytest.raises(MdflowError) as exc:
        make_plan(write_config())
    assert "STRUCTURE_MISSING" in exc.value.codes


def test_missing_topology_dependency_blocks_build(write_config, base_dir, tmp_path):
    (base_dir / "oplsaa.ff" / "spce.itp").unlink()
    with pytest.raises(MdflowError) as exc:
        make_plan(write_config(), for_build=True)
    assert "DEPENDENCY_MISSING" in exc.value.codes
    assert not (tmp_path / "out").exists()


def test_missing_template_blocks_plan(write_config, base_dir):
    (base_dir / "mdp" / "production.mdp.j2").unlink()
    with pytest.raises(MdflowError) as exc:
        make_plan(write_config())
    assert "TEMPLATE_MISSING" in exc.value.codes


def test_modified_base_project_detected_by_checksums(write_config, base_dir):
    gro = base_dir / "conf.gro"
    gro.write_text(gro.read_text().replace("0.230", "0.231", 1))
    with pytest.raises(MdflowError) as exc:
        make_plan(write_config())
    assert exc.value.codes == {"BASE_PROJECT_MODIFIED"}


def test_corrupt_structure_detected(write_config, base_dir):
    (base_dir / "SHA256SUMS").unlink()
    gro = base_dir / "conf.gro"
    lines = gro.read_text().splitlines()
    gro.write_text("\n".join(lines[:-5] + lines[-1:]) + "\n")
    with pytest.raises(MdflowError) as exc:
        make_plan(write_config())
    assert exc.value.codes == {"STRUCTURE_INVALID"}


def test_filename_conflict_with_generated_files(write_config, base_dir):
    (base_dir / "SHA256SUMS").unlink()
    (base_dir / "run.sh").write_text("#!/bin/sh\n")
    desc = yaml.safe_load((base_dir / "base_project.yaml").read_text())
    desc["structure"] = "run.sh"
    (base_dir / "base_project.yaml").write_text(yaml.safe_dump(desc))
    with pytest.raises(MdflowError) as exc:
        make_plan(write_config())
    assert "FILENAME_CONFLICT" in exc.value.codes


def test_failed_build_leaves_nothing(write_config, base_dir, tmp_path, monkeypatch):
    plan = make_plan(write_config(), for_build=True)
    import mdflow.package_writer as pw

    real = pw.check_job_dir
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 20:
            from mdflow.errors import Issue
            return [Issue("INJECTED", "simulated failure")]
        return real(*a, **kw)

    monkeypatch.setattr(pw, "check_job_dir", flaky)
    with pytest.raises(MdflowError):
        build(plan)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["base", "scan.yaml"]


def test_verify_output_detects_tampering(write_config, tmp_path):
    cfg = write_config()
    plan, res = _build(cfg)
    mdp = res.output_dir / "job_0005" / "npt.mdp"
    mdp.write_text(mdp.read_text().replace("ref-p                   = 10", "ref-p = 20"))
    (res.output_dir / "job_0009" / "oplsaa.ff" / "spce.itp").unlink()
    codes = {i.code for i in verify_output(plan)}
    assert {"MDP_MAPPING_MISMATCH", "PACKAGE_MODIFIED", "PACKAGE_INCOMPLETE"} <= codes


def test_verify_output_detects_manifest_drift(write_config):
    plan, res = _build(write_config())
    m = res.output_dir / "manifest.csv"
    lines = m.read_text().splitlines()
    m.write_text("\n".join(lines[:-1]) + "\n")
    codes = {i.code for i in verify_output(plan)}
    assert "MANIFEST_MISMATCH" in codes


def test_job_package_runs_from_any_cwd_and_has_no_host_paths(write_config, tmp_path):
    _, res = _build(write_config())
    for jd in res.output_dir.iterdir():
        if jd.is_dir():
            text = (jd / "run.sh").read_text() + (jd / "job.json").read_text()
            assert str(tmp_path) not in text
            assert str(Path.home()) + "/" not in text


def test_job_ids_and_seeds_stable_across_builds(write_config):
    _, a = _build(write_config("a.yaml", output={"directory": "a"}))
    _, b = _build(write_config("b.yaml", output={"directory": "b"}))
    assert (a.output_dir / "manifest.csv").read_text() == (b.output_dir / "manifest.csv").read_text()


def test_status_values():
    assert {s.value for s in ValidationStatus} == {
        "CONFIG_VALIDATED", "STATIC_VALIDATED", "GROMPP_VALIDATED", "RUN_VALIDATED",
    }
