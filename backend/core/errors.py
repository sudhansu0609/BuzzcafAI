"""Exception types the workflow engine classifies on.

Failures used to be categorised by searching the exception's message text for
words like "timeout" or "not found". That misclassified our own bugs -- a
NameError mentioning a variable called `connection` read as retryable, and a
genuine NameError was reported to the user as a blocking workflow state.

Raise these instead, and let anything unexpected fall through as BLOCKING so it
surfaces as the bug it is.
"""


class StudioError(Exception):
    """Base class for errors the engine is expected to handle."""


class ApprovalRequired(StudioError):
    """A step cannot proceed until a human approves or supplies feedback."""


class AssetMissing(StudioError):
    """A required input asset has not been produced yet.

    Recoverable: re-running the earlier step that produces it should fix this.
    """


class LLMUnavailable(StudioError):
    """No configured LLM provider could be reached.

    Raised instead of returning canned text outside development environments --
    see backend/dev/fixtures.py.
    """
