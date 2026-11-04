from decimal import Decimal

import pytest

from mdflow.errors import MdflowError
from mdflow.schemas import SimulationConfig
from mdflow.simulation_spec import Protocol, fmt_decimal, json_number, steps_from_duration, to_decimal


@pytest.mark.parametrize(
    "duration_ns, timestep_fs, steps",
    [
        ("20", "2", 10_000_000),  # spec example
        ("1", "2", 500_000),
        ("5", "2", 2_500_000),
        ("0.1", "2", 50_000),
        ("0.7", "2", 350_000),  # 0.7 / 0.002 == 349.99999999999994 in binary floating point
        ("1", "0.5", 2_000_000),
        ("0.0002", "2", 100),
    ],
)
def test_steps_from_duration_exact(duration_ns, timestep_fs, steps):
    assert steps_from_duration(Decimal(duration_ns), Decimal(timestep_fs)) == steps


def test_float_inputs_converted_without_binary_error():
    # 0.7 ns at 0.002 ps: naive float arithmetic truncates to 349 steps;
    # the Decimal path must give the exact count.
    assert int(0.7 / 0.002) == 349
    assert steps_from_duration(to_decimal(0.7), to_decimal(2.0)) == 350_000


@pytest.mark.parametrize("duration_ns, timestep_fs", [("1", "1.5"), ("0.0000001", "2"), ("0.001", "0.3")])
def test_non_integer_steps_rejected(duration_ns, timestep_fs):
    with pytest.raises(ValueError, match="not an integer multiple"):
        steps_from_duration(Decimal(duration_ns), Decimal(timestep_fs))


def test_protocol_reports_non_integer_steps_per_field():
    sim = SimulationConfig(timestep_fs=1.5, em_steps=100, nvt_ns=1.0, npt_ns=0.0015, production_ns=2.0)
    with pytest.raises(MdflowError) as exc:
        Protocol.from_config(sim)
    assert exc.value.codes == {"NON_INTEGER_STEPS"}
    wheres = {i.where for i in exc.value.issues}
    assert wheres == {"simulation.nvt_ns", "simulation.production_ns"}


def test_protocol_stages_and_units():
    sim = SimulationConfig(timestep_fs=2.0, em_steps=50000, nvt_ns=1.0, npt_ns=5.0, production_ns=20.0)
    proto = Protocol.from_config(sim)
    assert proto.timestep_ps == Decimal("0.002")
    names = [(s.name, s.steps, s.ensemble) for s in proto.stages()]
    assert names == [
        ("em", 50000, None),
        ("nvt", 500_000, "NVT"),
        ("npt", 2_500_000, "NPT"),
        ("production", 10_000_000, None),
    ]


def test_formatting_helpers():
    assert fmt_decimal(to_decimal(300.0)) == "300"
    assert fmt_decimal(to_decimal(300)) == "300"
    assert fmt_decimal(Decimal("0.0020")) == "0.002"
    assert fmt_decimal(to_decimal(1e-5)) == "0.00001"
    assert json_number(Decimal("300")) == 300 and isinstance(json_number(Decimal("300")), int)
    assert json_number(Decimal("300.5")) == 300.5
    with pytest.raises(TypeError):
        to_decimal(True)
