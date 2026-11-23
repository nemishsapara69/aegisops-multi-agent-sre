from app.security.pii_redactor import redact


def test_redacts_email_ip_key():
    text = "User a.b@corp.com hit 10.0.0.5 using sk-abc123def456ghi789"
    clean, counts = redact(text)
    assert "a.b@corp.com" not in clean
    assert "10.0.0.5" not in clean
    assert "sk-abc123def456ghi789" not in clean
    assert counts["EMAIL"] == 1
    assert counts["IPV4"] == 1
    assert counts["API_KEY"] == 1


def test_redacts_groq_style_key():
    clean, counts = redact("leaked gsk_abcdefghijklmnop1234 in logs")
    assert "gsk_abcdefghijklmnop1234" not in clean


def test_clean_text_unchanged():
    clean, counts = redact("Database latency is high on payments service")
    assert clean == "Database latency is high on payments service"
    assert counts == {}

def test_connection_string_password_is_redacted():
    clean, counts = redact("url postgresql://aegis:aegis_dev_password@db:5432/aegisops failed")
    assert "aegis_dev_password" not in clean
    assert counts["CONN_STRING"] == 1


def test_password_assignment_is_redacted():
    clean, counts = redact("login used password=Tr0ub4dor3xyz for admin")
    assert "Tr0ub4dor3xyz" not in clean and "for admin" in clean


def test_urls_without_credentials_are_untouched():
    text = "see https://example.com:8080/health"
    assert redact(text) == (text, {})    