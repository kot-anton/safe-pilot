class DomainError(Exception):
    """Base class for all domain-level errors."""


class InvalidEnvelopeError(DomainError):
    """CG envelope definition is invalid (unsorted, too few rows, bad limits, etc.)."""


class InvalidStationError(DomainError):
    """Station configuration is invalid."""


class InvalidInputError(DomainError):
    """User-supplied flight input is invalid (negative weight, over-capacity fuel, etc.)."""


class InconsistentAircraftDataError(DomainError):
    """Empty weight / moment / CG figures do not agree with each other."""
