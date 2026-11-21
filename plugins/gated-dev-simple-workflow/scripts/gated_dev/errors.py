"""Exceptions of the gated-dev scripts."""


class LaunchError(Exception):
    """A launcher failure; the message is what the CLI prints."""


class FlowError(Exception):
    """A /ticket-flow failure (unreadable state, lock held); the message is what the CLI prints."""
