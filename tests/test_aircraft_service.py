from decimal import Decimal as D

from app.services.aircraft_service import (
    AircraftRevisionDraft,
    empty_cg_from_moment,
    empty_moment_from_cg,
    useful_load_warning,
)


def test_empty_cg_to_empty_moment_conversion():
    weight = D("1500")
    cg = D("39.0")
    moment = empty_moment_from_cg(weight, cg)
    assert moment == D("58500.0")


def test_empty_moment_to_empty_cg_conversion():
    weight = D("1500")
    moment = D("58500")
    cg = empty_cg_from_moment(weight, moment)
    assert cg == D("39")


def _draft(known_useful_load_lb):
    return AircraftRevisionDraft(
        basic_empty_weight_lb=D("1500"),
        basic_empty_moment_lb_in=D("58500"),
        basic_empty_cg_in=D("39.0"),
        max_takeoff_weight_lb=D("2550"),
        stations=[],
        envelope_rows=[],
        known_useful_load_lb=known_useful_load_lb,
    )


def test_useful_load_matches_within_tolerance_no_warning():
    # calculated useful load = 2550 - 1500 = 1050
    draft = _draft(D("1048"))
    assert useful_load_warning(draft) is None


def test_useful_load_consistency_warning_when_mismatched():
    draft = _draft(D("1000"))  # off by 50 lb, exceeds 5 lb tolerance
    warning = useful_load_warning(draft)
    assert warning is not None
    assert "1050" in warning


def test_no_useful_load_provided_no_warning():
    draft = _draft(None)
    assert useful_load_warning(draft) is None
