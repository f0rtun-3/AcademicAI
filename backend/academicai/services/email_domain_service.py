"""Institutional email-domain validation (identity Gate 1).

WHAT THIS ESTABLISHES
---------------------
That a registrant's email address sits on a domain approved for the university
they selected. With email verification, which proves they control the account,
this shows control of an email account on an approved institution domain. It
does NOT prove current enrolment, and nothing here grants membership or
authority.

HOW IT COMPARES
---------------
The domain is the exact string after the single '@', lowercased. Comparison is
an equality test against the registry - never a suffix or substring test, so
`student.babcock.edu.ng.attacker.com` does not match
`student.babcock.edu.ng`. There is no pattern rule such as accepting any
`.edu.ng` address: one university's domain says nothing about another's.

THE REGISTRY IS BACKEND STATE
-----------------------------
Approved domains live in the database. A client sends a university name and an
email and nothing else; it cannot supply, extend, or influence the registry.
"""
import logging
from ..db.connection import query_all, query_one
from ..db.reference_data import normalize_domain
from ..errors import ValidationError


log = logging.getLogger("academicai.email_domain")


def extract_domain(email):
    """The domain of an already-normalised email address.

    Expects the single-'@' form that normalize_email guarantees.
    """
    if not isinstance(email, str) or email.count("@") != 1:
        raise ValidationError("A valid email address is required.")
    domain = normalize_domain(email.rsplit("@", 1)[1])
    if not domain or "." not in domain:
        raise ValidationError("A valid email address is required.")
    return domain


def supported_universities(conn=None):
    """Universities that have at least one active approved domain."""
    rows = query_all(
        """SELECT u.id, u.name, d.domain, d.domain_type
           FROM universities u
           JOIN university_email_domains d ON d.university_id = u.id
           WHERE d.active = 1
           ORDER BY u.name, d.domain""",
        conn=conn,
    )
    grouped = {}
    for row in rows:
        entry = grouped.setdefault(row["name"], {"id": row["id"], "name": row["name"],
                                                 "domains": []})
        entry["domains"].append({"domain": row["domain"], "domain_type": row["domain_type"]})
    return list(grouped.values())


def active_domains_for_university(university_name, conn=None):
    """Active approved domains for a university, matched by name."""
    name = (university_name or "").strip()
    if not name:
        return []
    rows = query_all(
        """SELECT d.domain FROM university_email_domains d
           JOIN universities u ON u.id = d.university_id
           WHERE u.name = ? AND d.active = 1
           ORDER BY d.domain""",
        (name,), conn=conn,
    )
    return [r["domain"] for r in rows]


def university_for_domain(domain, conn=None):
    """The university that owns an active domain, or None.

    Domains are unique registry-wide, so this is unambiguous.
    """
    return query_one(
        """SELECT u.id, u.name FROM university_email_domains d
           JOIN universities u ON u.id = d.university_id
           WHERE d.domain = ? AND d.active = 1""",
        (normalize_domain(domain),), conn=conn,
    )


def _domain_check_relaxed():
    """True only when the flag is on AND this is not production.

    The environment test is deliberately re-done here rather than trusted from
    startup. This function is the security control; it must be safe on its own,
    not merely safe because something else checked earlier.
    """
    from flask import current_app
    try:
        config = current_app.config
    except RuntimeError:       # no app context: never relax
        return False
    if config.get("ENV") == "production":
        return False
    return bool(config.get("ALLOW_ANY_EMAIL_DOMAIN"))


def assert_domain_matches_university(university_name, email, conn=None):
    """Reject unless `email`'s domain is approved for `university_name`.

    Raises ValidationError. Returns the matched domain on success.

    This is the security control. The frontend may check the same thing for
    convenience, but this call is what decides.
    """
    name = (university_name or "").strip()
    if not name:
        raise ValidationError("University is required.")

    domain = extract_domain(email)

    if _domain_check_relaxed():
        # Development only, and never silently: an open gate that leaves no
        # trace is one nobody notices is open.
        log.warning(
            "institutional domain check BYPASSED for %s "
            "(ACADEMICAI_ALLOW_ANY_EMAIL_DOMAIN is on; development only)", domain)
        return domain
    approved = active_domains_for_university(name, conn=conn)

    if not approved:
        # Either an unknown university, or one whose domains are all inactive.
        # Both are refused: without an approved domain there is nothing to check.
        raise ValidationError(
            "AcademicAI does not yet support that university. "
            "Only universities with a confirmed student email domain can be used.",
            details={"university": name,
                     "supported_universities": [u["name"] for u in
                                                supported_universities(conn=conn)]},
        )

    if domain in approved:
        return domain

    # The domain may be valid - for a different institution. Say that the
    # selection and the address disagree, without confirming anything about
    # any existing account.
    owner = university_for_domain(domain, conn=conn)
    details = {"university": name, "approved_domains": approved}
    if owner is not None and owner["name"] != name:
        details["domain_belongs_to_another_university"] = True
    raise ValidationError(
        "The email address must use an approved student email domain for the "
        "selected university.",
        details=details,
    )
