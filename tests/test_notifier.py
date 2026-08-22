import pytest

from agents import notifier


_ALERTS = [
    {"symbol": "NVDA", "type": "price_target_hit", "message": "NVDA hit its target price: $142 >= $140"},
    {"symbol": "AAPL", "type": "big_move", "message": "AAPL is up 6.1% today ($210)"},
]


def test_render_alert_email_single():
    subject, text, html = notifier.render_alert_email("Mindy", [_ALERTS[0]])
    assert "1 new stock alert" in subject and "NVDA" in subject
    assert "more" not in subject                 # no "+N more" for a single alert
    assert "Hi Mindy" in text and "target price" in text
    assert "<strong>NVDA</strong>" in html


def test_render_alert_email_batch():
    subject, text, html = notifier.render_alert_email("", _ALERTS)
    assert "2 new stock alerts" in subject and "+1 more" in subject
    assert "Hi there" in text                    # empty name falls back
    assert text.count("\n") > 3 and "AAPL" in text and "NVDA" in text
    assert html.count("<li") == 2


def test_render_alert_email_empty_raises():
    with pytest.raises(ValueError):
        notifier.render_alert_email("x", [])


def test_email_configured(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    assert notifier.email_configured() is False
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM", "bot@example.com")
    assert notifier.email_configured() is True


def test_send_email_noop_when_unconfigured(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM", raising=False)
    assert notifier.send_email("me@example.com", "s", "body") is False


class _FakeSMTP:
    """Records what a send did, as a context manager like smtplib.SMTP."""
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port
        self.tls = False
        self.login_args = None
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, pw):
        self.login_args = (user, pw)

    def send_message(self, msg):
        self.sent = msg


def test_send_email_sends_via_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bot@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "bot@example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "1")
    _FakeSMTP.instances = []
    monkeypatch.setattr(notifier.smtplib, "SMTP", _FakeSMTP)

    ok = notifier.send_email("me@example.com", "Subj", "text body", "<b>html</b>")
    assert ok is True
    inst = _FakeSMTP.instances[-1]
    assert inst.host == "smtp.example.com" and inst.port == 587
    assert inst.tls is True
    assert inst.login_args == ("bot@example.com", "secret")
    assert inst.sent["To"] == "me@example.com" and inst.sent["Subject"] == "Subj"
    assert inst.sent["From"] == "bot@example.com"
