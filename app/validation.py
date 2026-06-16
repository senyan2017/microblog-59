from flask import request


class ValidationError(Exception):
    """Raised when an incoming request body fails validation.

    A single application error handler turns this into a readable 400 JSON
    response, so individual views can declare their requirements with the
    helpers below instead of each rebuilding the same null / field / format
    checks (and the matching error payload) by hand.
    """

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def get_json_data():
    """Return the request body parsed as a non-empty JSON object.

    Uses ``silent=True`` so a wrong ``Content-Type`` or a malformed body
    never raises (which would surface as a 500); instead a ``ValidationError``
    is raised when the body is missing, malformed, or not a JSON object.
    """
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data:
        raise ValidationError(
            'Invalid request: Content-Type must be application/json and the '
            'body must contain a non-empty JSON object')
    return data


def require_string(data, field, required=True, allow_blank=False):
    """Validate that ``field`` in ``data`` is a non-empty string.

    - ``required=False`` accepts a missing field and returns ``None`` (a
      present field is still validated), which suits partial updates.
    - ``allow_blank=True`` only rejects the empty string, allowing values
      that are whitespace (e.g. passwords); by default whitespace-only
      values are rejected too.

    Returns the original value on success and raises ``ValidationError``
    otherwise.
    """
    if field not in data:
        if required:
            raise ValidationError(f'the {field} field is required')
        return None
    value = data[field]
    if not isinstance(value, str):
        raise ValidationError(f'the {field} field must be a non-empty string')
    is_empty = (value == '') if allow_blank else (not value.strip())
    if is_empty:
        raise ValidationError(f'the {field} field must be a non-empty string')
    return value
