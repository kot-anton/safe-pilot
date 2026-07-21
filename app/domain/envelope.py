"""CG envelope: weight-dependent forward/aft limits with linear interpolation."""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.domain.exceptions import InvalidEnvelopeError

# Small epsilon for floating/decimal boundary comparisons only. NOT an operational safety margin.
EPSILON = Decimal("0.0001")


class LimitStatus(str, Enum):
    WITHIN = "WITHIN"
    ON_LIMIT = "ON_LIMIT"
    OUT_OF_LIMITS = "OUT_OF_LIMITS"


@dataclass(frozen=True)
class EnvelopeRow:
    weight_lb: Decimal
    forward_cg_limit_in: Decimal
    aft_cg_limit_in: Decimal


@dataclass(frozen=True)
class CGCheckResult:
    status: LimitStatus
    forward_limit_in: Decimal
    aft_limit_in: Decimal
    forward_margin_in: Decimal
    aft_margin_in: Decimal
    # False means the aircraft weight is outside the published envelope weight range.
    # The forward/aft values are then only the nearest row for diagnostic context and must
    # never be presented as valid limits at the calculated weight.
    weight_within_envelope: bool = True


class CGEnvelope:
    """Weight-dependent CG envelope. Rows must be sorted strictly by increasing weight."""

    def __init__(self, rows: list[EnvelopeRow]):
        if len(rows) < 2:
            raise InvalidEnvelopeError("CG envelope requires at least two rows")

        sorted_rows = sorted(rows, key=lambda r: r.weight_lb)
        if sorted_rows != list(rows):
            raise InvalidEnvelopeError("Envelope rows must be entered in strictly increasing weight order")

        for i in range(1, len(sorted_rows)):
            if sorted_rows[i].weight_lb <= sorted_rows[i - 1].weight_lb:
                raise InvalidEnvelopeError("Envelope weights must be strictly increasing")

        for row in sorted_rows:
            if not all(
                value.is_finite()
                for value in (row.weight_lb, row.forward_cg_limit_in, row.aft_cg_limit_in)
            ):
                raise InvalidEnvelopeError("Envelope values must be finite")
            if row.weight_lb <= 0:
                raise InvalidEnvelopeError("Envelope weight must be positive")
            if row.forward_cg_limit_in > row.aft_cg_limit_in + EPSILON:
                raise InvalidEnvelopeError("Forward CG limit must be <= aft CG limit")

        self.rows = sorted_rows

    @property
    def min_weight(self) -> Decimal:
        return self.rows[0].weight_lb

    @property
    def max_weight(self) -> Decimal:
        return self.rows[-1].weight_lb

    def limits_at(self, weight_lb: Decimal) -> tuple[Decimal, Decimal] | None:
        """Returns (forward_limit, aft_limit) at the given weight via linear interpolation.

        Returns None when weight is outside the published envelope range.
        """
        if weight_lb < self.min_weight - EPSILON or weight_lb > self.max_weight + EPSILON:
            return None

        # Clamp tiny epsilon overshoot at boundaries back onto the boundary row.
        if weight_lb <= self.min_weight:
            row = self.rows[0]
            return row.forward_cg_limit_in, row.aft_cg_limit_in
        if weight_lb >= self.max_weight:
            row = self.rows[-1]
            return row.forward_cg_limit_in, row.aft_cg_limit_in

        for i in range(1, len(self.rows)):
            lower = self.rows[i - 1]
            upper = self.rows[i]
            if lower.weight_lb <= weight_lb <= upper.weight_lb:
                span = upper.weight_lb - lower.weight_lb
                fraction = (weight_lb - lower.weight_lb) / span
                forward = lower.forward_cg_limit_in + fraction * (
                    upper.forward_cg_limit_in - lower.forward_cg_limit_in
                )
                aft = lower.aft_cg_limit_in + fraction * (upper.aft_cg_limit_in - lower.aft_cg_limit_in)
                return forward, aft

        raise AssertionError("unreachable: weight within range but no bracketing rows found")

    def check(self, weight_lb: Decimal, cg_in: Decimal) -> CGCheckResult:
        limits = self.limits_at(weight_lb)
        if limits is None:
            # Weight outside envelope: no valid CG limits to report; use nearest row for context.
            nearest = self.rows[0] if weight_lb < self.min_weight else self.rows[-1]
            return CGCheckResult(
                status=LimitStatus.OUT_OF_LIMITS,
                forward_limit_in=nearest.forward_cg_limit_in,
                aft_limit_in=nearest.aft_cg_limit_in,
                forward_margin_in=cg_in - nearest.forward_cg_limit_in,
                aft_margin_in=nearest.aft_cg_limit_in - cg_in,
                weight_within_envelope=False,
            )

        forward_limit, aft_limit = limits
        forward_margin = cg_in - forward_limit
        aft_margin = aft_limit - cg_in

        if abs(forward_margin) <= EPSILON or abs(aft_margin) <= EPSILON:
            status = LimitStatus.ON_LIMIT
        elif forward_margin < 0 or aft_margin < 0:
            status = LimitStatus.OUT_OF_LIMITS
        else:
            status = LimitStatus.WITHIN

        return CGCheckResult(
            status=status,
            forward_limit_in=forward_limit,
            aft_limit_in=aft_limit,
            forward_margin_in=forward_margin,
            aft_margin_in=aft_margin,
        )
