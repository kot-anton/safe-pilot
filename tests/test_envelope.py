from decimal import Decimal as D

import pytest

from app.domain.envelope import CGEnvelope, EnvelopeRow, LimitStatus
from app.domain.exceptions import InvalidEnvelopeError


def make_envelope():
    return CGEnvelope(
        [
            EnvelopeRow(D("2200"), D("35.0"), D("47.3")),
            EnvelopeRow(D("2400"), D("37.0"), D("47.3")),
            EnvelopeRow(D("2550"), D("41.0"), D("47.3")),
        ]
    )


def test_interpolation_midpoint():
    env = make_envelope()
    forward, aft = env.limits_at(D("2300"))
    # halfway between 35.0 and 37.0
    assert forward == D("36.0")
    assert aft == D("47.3")


def test_point_exactly_on_forward_boundary_is_on_limit():
    env = make_envelope()
    result = env.check(D("2300"), D("36.0"))
    assert result.status == LimitStatus.ON_LIMIT


def test_forward_cg_violation():
    env = make_envelope()
    result = env.check(D("2300"), D("35.0"))  # forward limit at 2300 is 36.0
    assert result.status == LimitStatus.OUT_OF_LIMITS
    assert result.forward_margin_in < 0


def test_aft_cg_violation():
    env = make_envelope()
    result = env.check(D("2300"), D("47.5"))
    assert result.status == LimitStatus.OUT_OF_LIMITS
    assert result.aft_margin_in < 0


def test_within_limits():
    env = make_envelope()
    result = env.check(D("2300"), D("40.0"))
    assert result.status == LimitStatus.WITHIN
    assert result.forward_margin_in > 0
    assert result.aft_margin_in > 0


def test_weight_outside_envelope_is_out_of_limits():
    env = make_envelope()
    result = env.check(D("2600"), D("42.0"))
    assert result.status == LimitStatus.OUT_OF_LIMITS


def test_requires_at_least_two_rows():
    with pytest.raises(InvalidEnvelopeError):
        CGEnvelope([EnvelopeRow(D("2200"), D("35.0"), D("47.3"))])


def test_rejects_unsorted_or_duplicate_weights():
    with pytest.raises(InvalidEnvelopeError):
        CGEnvelope(
            [
                EnvelopeRow(D("2400"), D("37.0"), D("47.3")),
                EnvelopeRow(D("2200"), D("35.0"), D("47.3")),
            ]
        )
    with pytest.raises(InvalidEnvelopeError):
        CGEnvelope(
            [
                EnvelopeRow(D("2200"), D("35.0"), D("47.3")),
                EnvelopeRow(D("2200"), D("36.0"), D("47.3")),
            ]
        )


def test_rejects_forward_limit_greater_than_aft():
    with pytest.raises(InvalidEnvelopeError):
        CGEnvelope(
            [
                EnvelopeRow(D("2200"), D("48.0"), D("47.3")),
                EnvelopeRow(D("2400"), D("37.0"), D("47.3")),
            ]
        )


def test_check_distinguishes_weight_outside_envelope_from_cg_direction():
    env = make_envelope()
    result = env.check(D("2100"), D("40"))
    assert result.status == LimitStatus.OUT_OF_LIMITS
    assert result.weight_within_envelope is False


def test_check_marks_in_range_weight_explicitly():
    env = make_envelope()
    result = env.check(D("2300"), D("40"))
    assert result.weight_within_envelope is True
