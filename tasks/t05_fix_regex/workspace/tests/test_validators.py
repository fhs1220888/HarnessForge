from validators import validate_email


def test_valid_emails():
    assert validate_email("a.b@example.com")
    assert validate_email("user+tag@mail.example.org")
    assert validate_email("x_1@sub.domain.co")


def test_invalid_emails():
    assert not validate_email("no-at-sign.com")
    assert not validate_email("user@nodot")
    assert not validate_email("user@example.com extra words")
    assert not validate_email("@example.com")
