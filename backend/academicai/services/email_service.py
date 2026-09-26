"""Email delivery backends. Email is the only notification channel in MVP (spec 19).

ONE SEAM, THREE BACKENDS
------------------------
Every message in the product goes through `send()`. The backend is chosen by
configuration and nothing above this module knows which one is active.

    memory   records the message in-process. Tests read it back.
    console  prints the message. Development, so a code can be read from a log.
    resend   an HTTP POST to a transactional provider. The only one that sends.

TRUTHFULNESS
------------
`send()` returns a Result whose `delivered` flag says whether a provider
accepted the message, and callers record delivery state from that flag rather
than from the absence of an exception. This is the whole point of the rewrite:

    printing to a terminal is not delivery, and must never be recorded as SENT.

The memory and console backends therefore return delivered=False. They are not
failures - nothing went wrong, and the caller should not retry - they are
simulations, and the outbox says so.

A real provider that refuses the message raises EmailDeliveryError, which IS a
failure and is retried by the worker.
"""
import json
import logging
import threading
import urllib.error
import urllib.request

from flask import current_app

log = logging.getLogger("academicai.email")

# How this client identifies itself to the provider.
USER_AGENT = "AcademicAI/1.0 (+https://github.com/academicai)"

_lock = threading.Lock()
_outbox = []


class EmailDeliveryError(RuntimeError):
    pass


class Result:
    """What actually happened to one message.

    `delivered` is the only field callers should branch on. `provider` and
    `provider_message_id` exist so a failure can be traced in the provider's
    own dashboard, which is the first thing anyone asks for when mail goes
    missing.
    """

    __slots__ = ("delivered", "backend", "provider_message_id", "detail")

    def __init__(self, delivered, backend, provider_message_id=None, detail=None):
        self.delivered = delivered
        self.backend = backend
        self.provider_message_id = provider_message_id
        self.detail = detail

    def __repr__(self):  # pragma: no cover - debugging aid
        return (f"Result(delivered={self.delivered}, backend={self.backend!r}, "
                f"id={self.provider_message_id!r})")


def sent_messages():
    with _lock:
        return list(_outbox)


def clear():
    with _lock:
        _outbox.clear()


def _record(to, subject, body, html, backend):
    with _lock:
        _outbox.append({"to": to, "subject": subject, "body": body, "html": html,
                        "backend": backend})


def _memory_send(to, subject, body, html):
    _record(to, subject, body, html, "memory")
    return Result(delivered=False, backend="memory",
                  detail="recorded in-process; nothing was sent")


def _console_send(to, subject, body, html):
    print(f"[email] to={to} subject={subject}\n{body}\n")
    _record(to, subject, body, html, "console")
    return Result(delivered=False, backend="console",
                  detail="printed to stdout; nothing was sent")


def _resend_send(to, subject, body, html):
    """POST one message to Resend.

    Written against the HTTP API with urllib rather than the vendor SDK: the
    request is four fields of JSON and a bearer token, and the project has no
    third-party runtime dependencies beyond Flask. Swapping providers means
    another function of this shape, not a new architecture.
    """
    config = current_app.config
    api_key = config.get("RESEND_API_KEY")
    if not api_key:
        # Configuration error, not a transient one. Say which variable is
        # missing: this is the message someone reads at 2am.
        raise EmailDeliveryError(
            "ACADEMICAI_RESEND_API_KEY is not set, so no email can be sent.")

    payload = {
        "from": config["EMAIL_FROM"],
        "to": [to],
        "subject": subject,
        "text": body,
    }
    if html:
        payload["html"] = html

    request = urllib.request.Request(
        config["RESEND_API_URL"],
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json",
                 "Accept": "application/json",
                 # urllib identifies itself as "Python-urllib/3.x", which the
                 # provider's edge rejects outright (403, Cloudflare 1010)
                 # before the request ever reaches their API. Naming the
                 # application is both what fixes it and what an operator
                 # wants to see in a provider-side request log.
                 "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(
                request, timeout=config["EMAIL_TIMEOUT_SECONDS"]) as response:
            raw = response.read().decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        # The provider answered and refused. Its body says why - a rejected
        # from-address, an unverified domain, a malformed recipient - and that
        # sentence is far more useful than the status code alone.
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise EmailDeliveryError(f"Resend rejected the message ({exc.code}): {detail}")
    except urllib.error.URLError as exc:
        raise EmailDeliveryError(f"Could not reach Resend: {exc.reason}")

    if not 200 <= status < 300:  # pragma: no cover - urllib raises for these
        raise EmailDeliveryError(f"Resend returned {status}: {raw[:300]}")

    try:
        message_id = json.loads(raw).get("id")
    except ValueError:
        message_id = None
    _record(to, subject, body, html, "resend")
    log.info("email delivered to=%s subject=%s id=%s", to, subject, message_id)
    return Result(delivered=True, backend="resend", provider_message_id=message_id)


_BACKENDS = {"memory": _memory_send, "console": _console_send, "resend": _resend_send}

# Backends that put a message on the wire. Anything not listed here is a
# simulation, whatever it prints.
DELIVERING_BACKENDS = frozenset({"resend"})

_failure_hook = None


def set_failure_hook(fn):
    """Test seam: fn(to, subject, body) may raise to simulate delivery failure."""
    global _failure_hook
    _failure_hook = fn


def backend_name():
    return current_app.config.get("EMAIL_BACKEND", "console")


def is_delivering():
    """True when the configured backend actually sends mail.

    Callers use this to phrase what they tell the user. A build wired to the
    console must not say "check your inbox".
    """
    return backend_name() in DELIVERING_BACKENDS


def send(to, subject, body, html=None):
    """Send one message. Returns a Result; raises EmailDeliveryError on failure."""
    if _failure_hook is not None:
        _failure_hook(to, subject, body)
    backend = backend_name()
    handler = _BACKENDS.get(backend)
    if handler is None:
        raise EmailDeliveryError(f"Unknown email backend: {backend}")
    return handler(to, subject, body, html)
