import re

# BUG: rejects "+" in local part, allows missing TLD, and is not anchored.
EMAIL_RE = re.compile(r"[a-z0-9._]+@[a-z0-9-]+")


def validate_email(s: str) -> bool:
    return bool(EMAIL_RE.match(s))
