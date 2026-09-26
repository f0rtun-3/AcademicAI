"""Seed data for the institutional email-domain registry.

This module holds no imports from the rest of the application so it can be
called during schema initialisation.

THE REGISTRY IS DELIBERATELY SMALL. Only universities whose student email
domain has actually been confirmed appear here. Adding a university means
adding a row, not relaxing a rule: there is no pattern-based acceptance such as
"anything ending in .edu.ng", because a .edu.ng domain belonging to one
university is not evidence about another.
"""

# (university name, domain, domain_type)
#
# domain_type records what kind of address the domain issues:
#   STUDENT        - a dedicated student sub-domain
#   INSTITUTIONAL  - a shared domain used by students and staff alike
UNIVERSITY_EMAIL_DOMAINS = (
    ("Babcock University", "student.babcock.edu.ng", "STUDENT"),
    ("University of Ibadan", "stu.ui.edu.ng", "STUDENT"),
    ("University of Lagos", "unilag.edu.ng", "INSTITUTIONAL"),
    ("Covenant University", "stu.cu.edu.ng", "STUDENT"),
)


def normalize_domain(value):
    """Lowercase, trimmed, with any leading '@' or scheme noise removed."""
    if not isinstance(value, str):
        return ""
    domain = value.strip().lower().lstrip("@").rstrip(".")
    return domain


def is_seeded(conn):
    """Whether every registry domain is already present.

    Checked first so a normal start performs NO writes. That keeps start-up
    read-only once the registry exists, which matters because a write at boot
    can fail against a database another process is holding a lock on.
    """
    wanted = {normalize_domain(d) for _name, d, _type in UNIVERSITY_EMAIL_DOMAINS}
    rows = conn.execute("SELECT domain FROM university_email_domains").fetchall()
    present = {row[0] if isinstance(row, tuple) else row["domain"] for row in rows}
    return wanted <= present


def seed(conn, now):
    """Insert any missing registry rows.

    Idempotent and non-destructive: existing universities are matched by name
    and reused, so an established database keeps its ids, users, communities
    and any domains an operator added by hand. Deactivated domains are left
    deactivated - re-enabling one is an operator decision, not a side effect
    of a restart.
    """
    if is_seeded(conn):
        return False
    for name, domain, domain_type in UNIVERSITY_EMAIL_DOMAINS:
        row = conn.execute("SELECT id FROM universities WHERE name = ?", (name,)).fetchone()
        if row is None:
            cur = conn.execute(
                "INSERT INTO universities (name, created_at) VALUES (?, ?)", (name, now))
            university_id = cur.lastrowid
        else:
            university_id = row["id"] if not isinstance(row, tuple) else row[0]
        conn.execute(
            """INSERT OR IGNORE INTO university_email_domains
               (university_id, domain, domain_type, active, created_at)
               VALUES (?, ?, ?, 1, ?)""",
            (university_id, normalize_domain(domain), domain_type, now),
        )
    return True
