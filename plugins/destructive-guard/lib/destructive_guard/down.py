"""Why there is no Jev answer, or why the hook skipped Jev (the Lean model's `Down`)."""

from enum import StrEnum


class Down(StrEnum):
    """Why there is no Jev answer, or why the hook skipped Jev. Each one is shown as a warning."""

    TIMEOUT = "timeout"
    HTTP = "http"
    NETWORK = "network"
    MALFORMED = "malformed"
    ENV_REFERENCE = "envReference"
    BAD_INPUT = "badInput"
    PYTHON_MISSING = "pythonMissing"
    INTERNAL_ERROR = "internalError"

    @property
    def jev_unavailable(self) -> bool:
        """Jev is configured but did not give a usable answer (the model's `Down.jevUnavailable`)."""
        return self in (Down.TIMEOUT, Down.HTTP, Down.NETWORK, Down.MALFORMED)

    @property
    def plugin_fault(self) -> bool:
        """The plugin itself failed (D12): asks with a warning."""
        return self in (Down.BAD_INPUT, Down.PYTHON_MISSING, Down.INTERNAL_ERROR)

    @property
    def asks(self) -> bool:
        return self.jev_unavailable or self.plugin_fault
