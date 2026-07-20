from decimal import Decimal as D

import pytest

from app.domain.envelope import CGEnvelope, EnvelopeRow, LimitStatus
from app.domain.exceptions import InvalidInputError
from app.domain.fuel_allocation import (
    FuelInputMode,
    FuelRangeStatus,
    FuelTankSpec,
    classify_cg_range,
    compute_fixed_allocation,
    compute_fuel_allocation,
    detect_mode,
)


def two_tanks():
    return [
        FuelTankSpec(station_id="main", name="Main Fuel", usable_capacity_gal=D("40"), arm_in=D("48"), density_lb_per_gal=D("6")),
        FuelTankSpec(station_id="aux", name="Aux Fuel", usable_capacity_gal=D("20"), arm_in=D("20"), density_lb_per_gal=D("6")),
    ]


def same_arm_tanks():
    return [
        FuelTankSpec(station_id="left", name="Left Tank", usable_capacity_gal=D("25"), arm_in=D("48"), density_lb_per_gal=D("6")),
        FuelTankSpec(station_id="right", name="Right Tank", usable_capacity_gal=D("25"), arm_in=D("48"), density_lb_per_gal=D("6")),
    ]


def test_detect_mode_single_tank_is_single_arm():
    assert detect_mode([two_tanks()[0]]) == FuelInputMode.SINGLE_ARM


def test_detect_mode_same_arm_tanks_is_single_arm():
    assert detect_mode(same_arm_tanks()) == FuelInputMode.SINGLE_ARM


def test_detect_mode_different_arms_is_unknown_split():
    assert detect_mode(two_tanks()) == FuelInputMode.UNKNOWN_SPLIT_RANGE


def test_single_arm_tanks_produce_exact_moment_regardless_of_split():
    result = compute_fuel_allocation(same_arm_tanks(), D("30"))
    assert result.mode == FuelInputMode.SINGLE_ARM
    assert result.is_exact
    assert result.min_moment_lb_in == result.max_moment_lb_in
    # 30 gal * 6 lb/gal * 48 in = 8640 lb-in, regardless of which tank holds it
    assert result.min_moment_lb_in == D("8640")


def test_full_fuel_in_multi_tank_group_is_exact():
    """At full usable capacity every tank is full, so the split is forced -- exact CG."""
    tanks = two_tanks()
    total = D("60")  # 40 + 20, both tanks completely full
    result = compute_fuel_allocation(tanks, total)
    assert result.is_exact
    expected_moment = D("40") * D("6") * D("48") + D("20") * D("6") * D("20")
    assert result.min_moment_lb_in == expected_moment
    assert result.max_moment_lb_in == expected_moment


def test_partial_total_fuel_unknown_split_min_moment():
    """20 gal split between a 48in and a 20in tank -- minimum moment fills the low-ARM
    (aux, 20in) tank first."""
    tanks = two_tanks()
    result = compute_fuel_allocation(tanks, D("20"))
    # min: fill aux (arm 20) first -- but aux capacity is 20, so all 20 gal fits in aux alone
    expected_min = D("20") * D("6") * D("20")
    assert result.min_moment_lb_in == expected_min


def test_partial_total_fuel_unknown_split_max_moment():
    """Same 20 gal -- maximum moment fills the high-ARM (main, 48in) tank first."""
    tanks = two_tanks()
    result = compute_fuel_allocation(tanks, D("20"))
    expected_max = D("20") * D("6") * D("48")
    assert result.max_moment_lb_in == expected_max
    assert result.min_moment_lb_in < result.max_moment_lb_in


def test_total_fuel_above_capacity_rejected():
    with pytest.raises(InvalidInputError):
        compute_fuel_allocation(two_tanks(), D("61"))


def test_mixed_density_in_one_group_rejected():
    tanks = [
        FuelTankSpec(station_id="main", name="Main", usable_capacity_gal=D("40"), arm_in=D("48"), density_lb_per_gal=D("6")),
        FuelTankSpec(station_id="aux", name="Aux", usable_capacity_gal=D("20"), arm_in=D("20"), density_lb_per_gal=D("6.02")),
    ]
    with pytest.raises(InvalidInputError):
        compute_fuel_allocation(tanks, D("10"))


def test_negative_total_fuel_rejected():
    with pytest.raises(InvalidInputError):
        compute_fuel_allocation(two_tanks(), D("-5"))


def test_fixed_allocation_follows_only_the_configured_rule():
    tanks = [
        FuelTankSpec(
            station_id="main", name="Main", usable_capacity_gal=D("40"), arm_in=D("48"),
            density_lb_per_gal=D("6"), allocation_order=1, fixed_full_quantity_gal=D("40"),
        ),
        FuelTankSpec(
            station_id="aux", name="Aux", usable_capacity_gal=D("20"), arm_in=D("20"),
            density_lb_per_gal=D("6"), allocation_order=2, fixed_full_quantity_gal=D("20"),
        ),
    ]
    # main fills first per allocation_order regardless of ARM
    allocation = compute_fixed_allocation(tanks, D("30"))
    assert allocation.gallons_by_station["main"] == D("30")
    assert allocation.gallons_by_station["aux"] == D("0")
    assert allocation.total_moment_lb_in == D("30") * D("6") * D("48")


# --- CG range classification -------------------------------------------------

def envelope():
    return CGEnvelope([EnvelopeRow(D("2200"), D("35.0"), D("47.3")), EnvelopeRow(D("2550"), D("41.0"), D("47.3"))])


def test_cg_range_entirely_within_envelope():
    # at 2400 lb the interpolated envelope is ~38.43-47.3 in
    status, fwd, aft = classify_cg_range(envelope(), D("2400"), D("40.0"), D("42.0"))
    assert status == FuelRangeStatus.WITHIN_ALL
    assert fwd.status == LimitStatus.WITHIN
    assert aft.status == LimitStatus.WITHIN


def test_cg_range_entirely_forward_of_envelope():
    status, fwd, aft = classify_cg_range(envelope(), D("2400"), D("30.0"), D("32.0"))
    assert status == FuelRangeStatus.OUT_ALL


def test_cg_range_entirely_aft_of_envelope():
    status, fwd, aft = classify_cg_range(envelope(), D("2400"), D("50.0"), D("52.0"))
    assert status == FuelRangeStatus.OUT_ALL


def test_cg_range_partly_inside_partly_outside_requires_exact_split():
    # at 2400 lb the interpolated envelope is ~38.43-47.3 in: 40.0 is within, 48.0 is outside (aft)
    status, fwd, aft = classify_cg_range(envelope(), D("2400"), D("40.0"), D("48.0"))
    assert status == FuelRangeStatus.EXACT_SPLIT_REQUIRED


def test_cg_range_no_envelope_returns_none():
    status, fwd, aft = classify_cg_range(None, D("2400"), D("38.0"), D("40.0"))
    assert status is None
    assert fwd is None
    assert aft is None
