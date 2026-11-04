from decimal import Decimal

import pytest

from mdflow.parameter_space import SEED_MAX, SEED_MIN, assign_identities, expand
from mdflow.plan import make_plan
from mdflow.schemas import ScanConfig

FP = {"timestep_fs": "2", "stages": []}


def _ids(points, base="a" * 64, fp=FP, version="0.1.0"):
    return assign_identities(points, base_project_sha256=base, protocol_fingerprint=fp, builder_version=version)


def test_single_parameter_scan():
    pts = expand(ScanConfig(temperature_K=[280, 300, 320, 340], pressure_bar=[1], replicas=1))
    assert [(p.temperature_K, p.pressure_bar, p.replica) for p in pts] == [
        (Decimal(t), Decimal(1), 1) for t in (280, 300, 320, 340)
    ]


def test_two_parameter_scan_order():
    pts = expand(ScanConfig(temperature_K=[280, 300], pressure_bar=[1, 10], replicas=1))
    assert [(int(p.temperature_K), int(p.pressure_bar)) for p in pts] == [(280, 1), (280, 10), (300, 1), (300, 10)]


def test_replicas():
    pts = expand(ScanConfig(temperature_K=[300], pressure_bar=[1], replicas=4))
    assert [p.replica for p in pts] == [1, 2, 3, 4]


def test_36_job_acceptance_space_complete():
    pts = expand(ScanConfig(temperature_K=[280, 300, 320, 340], pressure_bar=[1, 10, 50], replicas=3))
    assert len(pts) == 36
    combos = {(int(p.temperature_K), int(p.pressure_bar), p.replica) for p in pts}
    assert combos == {(t, p, r) for t in (280, 300, 320, 340) for p in (1, 10, 50) for r in (1, 2, 3)}


def test_job_ids_and_seeds_unique_stable_and_in_range():
    pts = expand(ScanConfig(temperature_K=[280, 300, 320, 340], pressure_bar=[1, 10, 50], replicas=3))
    a, b = _ids(pts), _ids(pts)
    assert [(j.job_id, j.random_seed) for j in a] == [(j.job_id, j.random_seed) for j in b]
    assert len({j.job_id for j in a}) == 36
    assert len({j.random_seed for j in a}) == 36
    assert all(SEED_MIN <= j.random_seed <= SEED_MAX for j in a)
    assert [j.sequence_id for j in a][:3] == ["job_0001", "job_0002", "job_0003"]


def test_replicas_get_different_seeds():
    pts = expand(ScanConfig(temperature_K=[300], pressure_bar=[1], replicas=5))
    seeds = [j.random_seed for j in _ids(pts)]
    assert len(set(seeds)) == 5


def test_identity_depends_on_science_not_on_order_or_name():
    pts = expand(ScanConfig(temperature_K=[300, 320], pressure_bar=[1], replicas=1))
    rev = expand(ScanConfig(temperature_K=[320, 300], pressure_bar=[1], replicas=1))
    by_t = {j.point.temperature_K: j.job_id for j in _ids(pts)}
    by_t_rev = {j.point.temperature_K: j.job_id for j in _ids(rev)}
    assert by_t == by_t_rev  # job id does not depend on list order / sequence number
    # but does depend on base project, protocol and builder version
    base_ids = {j.job_id for j in _ids(pts)}
    assert base_ids.isdisjoint({j.job_id for j in _ids(pts, base="b" * 64)})
    assert base_ids.isdisjoint({j.job_id for j in _ids(pts, fp={"timestep_fs": "1", "stages": []})})
    assert base_ids.isdisjoint({j.job_id for j in _ids(pts, version="0.2.0")})


def test_project_name_does_not_change_identity(write_config):
    a = make_plan(write_config("a.yaml", project="first"))
    b = make_plan(write_config("b.yaml", project="renamed"))
    assert [j.identity.job_id for j in a.jobs] == [j.identity.job_id for j in b.jobs]
    assert [j.spec.random_seed for j in a.jobs] == [j.spec.random_seed for j in b.jobs]


def test_int_and_float_values_are_the_same_job():
    a = _ids(expand(ScanConfig(temperature_K=[300], pressure_bar=[1], replicas=1)))
    b = _ids(expand(ScanConfig(temperature_K=[300.0], pressure_bar=[1.0], replicas=1)))
    assert a[0].job_id == b[0].job_id


@pytest.mark.parametrize("n, first", [(1, "job_0001"), (9999, "job_0001"), (10000, "job_00001")])
def test_sequence_id_width(n, first):
    from mdflow.parameter_space import ScanPoint

    pts = [ScanPoint(Decimal(300), Decimal(1), r) for r in range(1, n + 1)]
    ids = _ids(pts)
    assert ids[0].sequence_id == first
    assert len({j.random_seed for j in ids}) == n
