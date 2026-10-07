"""Optimization-safe expectations for native unittest test cases."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class Capture:
    """Expose the expected exception caught by an expectation context.

    Attributes:
        exception: Caught exception, or None before an exception is observed.
    """

    exception: BaseException | None = None


def ensure(condition: bool, message: str = "") -> None:
    """Require a condition even when Python optimization is enabled.

    Args:
        condition: Whether the expectation is satisfied.
        message: Optional diagnostic for a failed expectation.

    Raises:
        AssertionError: If the condition is false.
    """
    if not condition:
        diagnostic = message or "test expectation failed"
        raise AssertionError(diagnostic)


def ensure_equal(actual: object, expected: object) -> None:
    """Require equality without relying on Python assert statements.

    Args:
        actual: Observed value.
        expected: Required value.

    Raises:
        AssertionError: If the values differ.
    """
    ensure(actual == expected, f"expected {expected!r}, got {actual!r}")


@contextmanager
def expect_error(
    error_type: type[BaseException] | tuple[type[BaseException], ...],
    pattern: str | None = None,
) -> Iterator[Capture]:
    """Require an expected exception and optionally match its diagnostic.

    Unexpected exception types propagate unchanged. The capture is populated
    before checking the diagnostic so a failed match retains the evidence.

    Args:
        error_type: Expected exception class or tuple of exception classes.
        pattern: Optional regular expression searched within the diagnostic.

    Yields:
        Capture: Holder for the caught exception.

    Raises:
        AssertionError: If no expected exception occurs or its text mismatches.
    """
    capture = Capture()
    try:
        yield capture
    except error_type as exception:
        capture.exception = exception
        if pattern is not None:
            ensure(
                re.search(pattern, str(exception)) is not None,
                f"pattern {pattern!r} did not match {str(exception)!r}",
            )
    else:
        expected_types = error_type if isinstance(error_type, tuple) else (error_type,)
        names = ", ".join(expected.__name__ for expected in expected_types)
        diagnostic = f"expected exception: {names or '(empty exception tuple)'}"
        raise AssertionError(diagnostic)
