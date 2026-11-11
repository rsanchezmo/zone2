"""What a service raises when it can't do what was asked, with a message fit to show the user.
The API answers each with its HTTP status (`app.py`); the agent's tools turn it into a retry."""


class ServiceError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(ServiceError):
    pass


class Invalid(ServiceError):
    pass


class Conflict(ServiceError):
    pass


class UpstreamUnavailable(ServiceError):
    """An outside service (Garmin Connect) can't be reached or signed in to."""


class UpstreamFailed(ServiceError):
    """An outside service answered the call with an error."""
