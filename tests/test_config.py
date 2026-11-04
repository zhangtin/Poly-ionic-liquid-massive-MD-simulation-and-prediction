"""YAML loading and schema validation."""
from pathlib import Path

import pytest

from mdflow.config import load_base_project, load_config
from mdflow.errors import MdflowError
from mdflow.plan import make_plan


def _codes(fn, *a, **kw):
    with pytest.raises(MdflowError) as exc:
        fn(*a, **kw)
    return exc.value


def test_valid_config_resolves_paths_relative_to_file(write_config, tmp_path):
    cfg = load_config(write_config())
    assert cfg.base_project_dir == (tmp_path / "base").resolve()
    assert cfg.output_dir == (tmp_path / "out").resolve()
    assert len(cfg.sha256) == 64


@pytest.mark.parametrize(
    "override, where",
    [
        ({"scan": {"temperature_K": []}}, "scan.temperature_K"),  # empty list
        ({"scan": {"pressure_bar": []}}, "scan.pressure_bar"),
        ({"scan": {"temperature_K": [-10]}}, "scan.temperature_K.0"),  # illegal temperature
        ({"scan": {"temperature_K": [0]}}, "scan.temperature_K.0"),
        ({"scan": {"pressure_bar": [-1]}}, "scan.pressure_bar.0"),  # illegal pressure
        ({"scan": {"temperature_K": ["300"]}}, "scan.temperature_K.0"),  # string, not silently cast
        ({"scan": {"temperature_K": [True]}}, "scan.temperature_K.0"),
        ({"scan": {"replicas": 0}}, "scan.replicas"),
        ({"scan": {"replicas": 2.5}}, "scan.replicas"),
        ({"simulation": {"timestep_fs": 0}}, "simulation.timestep_fs"),
        ({"simulation": {"em_steps": 0}}, "simulation.em_steps"),
        ({"simulation": {"production_ns": -1.0}}, "simulation.production_ns"),
        ({"project": "bad name/with slash"}, "project"),
        ({"output": {"directory": ""}}, "output.directory"),
        ({"extra_key": 1}, "extra_key"),
        ({"scan": {"temprature_K": [300]}}, "scan.temprature_K"),  # typo -> unknown key
    ],
)
def test_schema_errors(write_config, override, where):
    err = _codes(load_config, write_config(**override))
    assert "SCHEMA_ERROR" in err.codes
    assert where in {i.where for i in err.issues}


def test_missing_section(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("project: x\nbase_project: base\n")
    err = _codes(load_config, p)
    assert {i.where for i in err.issues} >= {"scan", "simulation", "output"}


def test_duplicate_yaml_key_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("project: a\nproject: b\n")
    assert _codes(load_config, p).codes == {"YAML_DUPLICATE_KEY"}


def test_invalid_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("scan: [1, 2\n")
    assert _codes(load_config, p).codes == {"YAML_PARSE_ERROR"}


def test_missing_config_file(tmp_path):
    assert _codes(load_config, tmp_path / "nope.yaml").codes == {"FILE_NOT_FOUND"}


def test_missing_base_project(write_config):
    err = _codes(make_plan, write_config(base_project="does_not_exist"))
    assert err.codes == {"BASE_PROJECT_MISSING"}


def test_missing_base_descriptor(base_dir: Path):
    (base_dir / "base_project.yaml").unlink()
    assert _codes(load_base_project, base_dir).codes == {"BASE_DESCRIPTOR_MISSING"}


def test_duplicate_scan_values_rejected(write_config):
    # 300 and 300.0 are the same temperature; must be an error, not silently merged
    err = _codes(make_plan, write_config(scan={"temperature_K": [280, 300, 300.0]}))
    assert err.codes == {"DUPLICATE_VALUE"}


def test_out_of_model_range(write_config):
    err = _codes(make_plan, write_config(scan={"temperature_K": [250, 300], "pressure_bar": [1, 5000]}))
    assert err.codes == {"TEMPERATURE_OUT_OF_RANGE", "PRESSURE_OUT_OF_RANGE"}


def test_timestep_above_model_limit(write_config):
    err = _codes(make_plan, write_config(simulation={"timestep_fs": 4.0}))
    assert err.codes == {"TIMESTEP_TOO_LARGE"}


def test_non_integer_steps_in_plan(write_config):
    err = _codes(make_plan, write_config(simulation={"timestep_fs": 1.5}))
    assert err.codes == {"NON_INTEGER_STEPS"}


def test_all_issues_reported_together(write_config):
    err = _codes(
        make_plan,
        write_config(scan={"temperature_K": [300, 300], "pressure_bar": [2000]}, simulation={"timestep_fs": 1.5}),
    )
    assert err.codes == {"DUPLICATE_VALUE", "PRESSURE_OUT_OF_RANGE", "NON_INTEGER_STEPS"}
