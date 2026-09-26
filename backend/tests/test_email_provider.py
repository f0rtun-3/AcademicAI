"""The Resend backend, checked against a stub that speaks its protocol.

WHAT THIS CAN AND CANNOT PROVE
------------------------------
It proves the request AcademicAI puts on the wire is the one Resend documents:
the URL, the bearer token, the JSON shape, both body parts, and that the
outcome is read from the RESPONSE rather than assumed. It also proves the
failure paths - a refusal and an unreachable host - are reported as failures
instead of being swallowed.

It cannot prove Resend accepts the message, that a domain is verified, or that
anything lands in an inbox. Only sending to a real account does that, and no
test should be read as a substitute for having done so.

The stub is a real socket on localhost, not a mock of urllib: mocking the
transport would leave the one thing worth testing - that a correct HTTP
request is produced - unexercised.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from academicai.services import email_service


class _Stub(BaseHTTPRequestHandler):
    received = []
    status = 200
    payload = {"id": "stub-message-id"}

    def do_POST(self):  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        type(self).received.append({
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "body": json.loads(raw),
        })
        body = json.dumps(type(self).payload).encode("utf-8")
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the test output clean
        pass


@pytest.fixture
def stub():
    _Stub.received = []
    _Stub.status = 200
    _Stub.payload = {"id": "stub-message-id"}
    server = HTTPServer(("127.0.0.1", 0), _Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield _Stub, f"http://{host}:{port}/emails"
    server.shutdown()
    server.server_close()


def configure(app, url, **extra):
    app.config.update({
        "EMAIL_BACKEND": "resend",
        "RESEND_API_URL": url,
        "RESEND_API_KEY": "re_test_key",
        "EMAIL_FROM": "AcademicAI <onboarding@resend.dev>",
        **extra,
    })


def test_the_request_matches_what_the_provider_expects(app, stub):
    handler, url = stub
    with app.app_context():
        configure(app, url)
        result = email_service.send(
            "student@student.babcock.edu.ng", "482917 is your code",
            "Your verification code is:\n\n    482917\n", html="<p>482917</p>")

    assert len(handler.received) == 1
    request = handler.received[0]
    assert request["authorization"] == "Bearer re_test_key"
    assert request["content_type"] == "application/json"
    assert request["body"] == {
        "from": "AcademicAI <onboarding@resend.dev>",
        "to": ["student@student.babcock.edu.ng"],
        "subject": "482917 is your code",
        "text": "Your verification code is:\n\n    482917\n",
        "html": "<p>482917</p>",
    }
    # The outcome is READ FROM THE RESPONSE, including the provider's own id,
    # which is what makes a missing email traceable in their dashboard.
    assert result.delivered is True
    assert result.backend == "resend"
    assert result.provider_message_id == "stub-message-id"


def test_a_message_without_html_omits_the_field(app, stub):
    handler, url = stub
    with app.app_context():
        configure(app, url)
        email_service.send("someone@example.com", "s", "b")
    assert "html" not in handler.received[0]["body"]


def test_a_refusal_is_a_failure_and_says_why(app, stub):
    """The provider's own sentence is the useful part of the error."""
    handler, url = stub
    handler.status = 422
    handler.payload = {"message": "The domain is not verified."}
    with app.app_context():
        configure(app, url)
        with pytest.raises(email_service.EmailDeliveryError) as excinfo:
            email_service.send("someone@example.com", "s", "b")
    assert "422" in str(excinfo.value)
    assert "The domain is not verified." in str(excinfo.value)


def test_an_unreachable_provider_is_a_failure(app):
    """Nothing listening: the send must raise, never quietly succeed."""
    with app.app_context():
        # Port 1 on localhost refuses connections.
        configure(app, "http://127.0.0.1:1/emails")
        with pytest.raises(email_service.EmailDeliveryError) as excinfo:
            email_service.send("someone@example.com", "s", "b")
    assert "Could not reach Resend" in str(excinfo.value)


def test_a_missing_api_key_names_the_variable(app):
    with app.app_context():
        configure(app, "http://127.0.0.1:1/emails", RESEND_API_KEY=None)
        with pytest.raises(email_service.EmailDeliveryError) as excinfo:
            email_service.send("someone@example.com", "s", "b")
    assert "ACADEMICAI_RESEND_API_KEY" in str(excinfo.value)


def test_a_delivered_notification_is_recorded_as_sent(app, stub, client,
                                                     academic_community):
    """The other half of the truthfulness rule.

    Elsewhere the suite proves a simulated backend is never recorded as SENT.
    This proves the converse: when a provider really does accept the message,
    SENT is exactly what the outbox says.
    """
    from academicai.db.connection import query_all
    from academicai.services import notification_service

    handler, url = stub
    setup = academic_community(size=5, seed_events=False)
    resp = setup.rep.post("/api/community/announcements",
                          json={"title": "Provider probe", "body": "body"})
    assert resp.status_code == 201

    with app.app_context():
        configure(app, url)
        result = notification_service.dispatch_pending()
        # Scoped to THIS announcement: building the fixture community already
        # dispatched messages under the memory backend, and those are
        # correctly SIMULATED. Only the rows this test sent are in question.
        statuses = {r["status"] for r in query_all(
            "SELECT DISTINCT status FROM notifications WHERE subject LIKE ?",
            ("%Provider probe%",))}

    assert result["sent"] > 0
    assert result["simulated"] == 0
    assert statuses == {"SENT"}
    assert len(handler.received) == result["sent"]
