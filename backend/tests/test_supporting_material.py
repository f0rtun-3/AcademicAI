"""Optional supporting material on assignments and projects.

The product rule these protect: an assignment or project is COMPLETE without an
attachment. Everything here that concerns publishing asserts the absence of a
requirement, not the presence of a feature.

The security rules are the same ones every other official write obeys — a rep
of that community writes, a member of that community reads, and nobody else
gets either.
"""
import io

import pytest

from academicai.services import attachment_storage

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def upload(actor, event_id, data=PDF, name="COS202_Assignment1.pdf",
           content_type="application/pdf"):
    return actor.post(
        f"/api/events/{event_id}/attachments",
        data={"file": (io.BytesIO(data), name, content_type)},
        content_type="multipart/form-data",
    )


# ── The attachment is optional ─────────────────────────────────────────────

def test_assignment_publishes_with_no_attachment(client, academic_community):
    """Case 1 of the brief: typed only. The core guarantee."""
    setup = academic_community()
    resp = setup.rep.post("/api/events", json={
        "title": "Assignment 1 - Functions",
        "event_type": "ASSIGNMENT",
        "description": "Write a Python program that demonstrates the use of functions.",
        "course_id": setup.courses["COS202"],
        "event_date": "2026-09-28", "event_time": "23:59",
    })
    assert resp.status_code == 201, resp.get_json()
    event = resp.get_json()["event"]
    assert event["description"].startswith("Write a Python program")
    # Absence is a normal, complete state - not an empty slot to be filled.
    assert event["attachments"] == []


def test_project_publishes_with_no_attachment(client, academic_community):
    setup = academic_community()
    resp = setup.rep.post("/api/events", json={
        "title": "Group Project - Library System",
        "event_type": "PROJECT",
        "description": "Build and document a small library system.",
        "course_id": setup.courses["COS202"], "event_date": "2026-10-30",
    })
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["event"]["event_type"] == "PROJECT"
    assert resp.get_json()["event"]["attachments"] == []


def test_event_with_neither_description_nor_attachment_is_still_valid(
        client, academic_community):
    """The pre-existing shape. Nothing about this feature may make it invalid."""
    setup = academic_community()
    resp = setup.rep.post("/api/events", json={
        "title": "Quiz", "event_type": "QUIZ", "event_date": "2026-09-30"})
    assert resp.status_code == 201
    assert resp.get_json()["event"]["description"] is None
    assert resp.get_json()["event"]["attachments"] == []


# ── Typed + attachment, and attachment-led ─────────────────────────────────

def test_rep_attaches_material_to_an_existing_assignment(client, academic_community):
    """Case 3: structured record AND the original paper, side by side."""
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]

    resp = upload(setup.rep, event_id)
    assert resp.status_code == 201, resp.get_json()
    attachment = resp.get_json()["attachment"]
    assert attachment["filename"] == "COS202_Assignment1.pdf"
    assert attachment["content_type"] == "application/pdf"
    assert attachment["byte_size"] == len(PDF)
    # The storage key must never reach a client.
    assert "storage_key" not in attachment
    assert "path" not in attachment

    # The structured record is untouched: the file did not replace it.
    detail = setup.rep.get(f"/api/events/{event_id}").get_json()["event"]
    assert detail["title"] == "COS202 Assignment"
    assert [a["filename"] for a in detail["attachments"]] == ["COS202_Assignment1.pdf"]


def test_attachment_appears_in_the_event_list_in_one_query(client, academic_community):
    setup = academic_community()
    upload(setup.rep, setup.cos202_assignment["id"])
    events = setup.members[1].get("/api/events").get_json()["events"]
    withm = [e for e in events if e["attachments"]]
    assert len(withm) == 1
    assert withm[0]["id"] == setup.cos202_assignment["id"]


# ── Reading ────────────────────────────────────────────────────────────────

def test_member_can_download_the_original(client, academic_community):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]
    attachment_id = upload(setup.rep, event_id).get_json()["attachment"]["id"]

    resp = setup.members[1].get(
        f"/api/events/{event_id}/attachments/{attachment_id}")
    assert resp.status_code == 200
    assert resp.data == PDF
    # Nothing renders in-page, so stored bytes cannot execute in our origin.
    assert "attachment;" in resp.headers["Content-Disposition"]
    assert 'filename="COS202_Assignment1.pdf"' in resp.headers["Content-Disposition"]
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in resp.headers["Cache-Control"]


def test_a_student_cannot_add_or_remove_official_material(client, academic_community):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]
    attachment_id = upload(setup.rep, event_id).get_json()["attachment"]["id"]
    student = setup.members[1]

    assert upload(student, event_id).status_code == 403
    assert student.delete(
        f"/api/events/{event_id}/attachments/{attachment_id}").status_code == 403
    # Still there, unchanged.
    detail = student.get(f"/api/events/{event_id}").get_json()["event"]
    assert len(detail["attachments"]) == 1


def test_another_community_cannot_reach_the_material(client, academic_community):
    """Scoped through the event, so a guessed id is a 404 and not a leak."""
    mine = academic_community()
    event_id = mine.cos202_assignment["id"]
    # Upload BEFORE the second community is built: that fixture advances the
    # clock past this rep's session expiry, which would otherwise show up as a
    # 401 here and look like an authorisation bug in the feature.
    attachment_id = upload(mine.rep, event_id).get_json()["attachment"]["id"]
    theirs = academic_community(level="300")

    resp = theirs.rep.get(f"/api/events/{event_id}/attachments/{attachment_id}")
    assert resp.status_code == 404
    assert "not found" in resp.get_json()["message"].lower()


def test_attachment_id_from_another_event_is_not_reachable(client, academic_community):
    setup = academic_community()
    attachment_id = upload(
        setup.rep, setup.cos202_assignment["id"]).get_json()["attachment"]["id"]
    other_event = setup.heritage_event["id"]
    resp = setup.rep.get(f"/api/events/{other_event}/attachments/{attachment_id}")
    assert resp.status_code == 404


# ── Removal ────────────────────────────────────────────────────────────────

def test_rep_removes_material_and_the_bytes_go(client, academic_community, app):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]
    attachment_id = upload(setup.rep, event_id).get_json()["attachment"]["id"]

    assert setup.rep.delete(
        f"/api/events/{event_id}/attachments/{attachment_id}").status_code == 200
    detail = setup.rep.get(f"/api/events/{event_id}").get_json()["event"]
    assert detail["attachments"] == []
    # The record still holds the event; only the material went.
    assert detail["title"] == "COS202 Assignment"
    # A second download is a 404, not a stale file.
    assert setup.rep.get(
        f"/api/events/{event_id}/attachments/{attachment_id}").status_code == 404


def test_removal_is_recorded_in_the_community_history(client, academic_community):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]
    attachment_id = upload(setup.rep, event_id).get_json()["attachment"]["id"]
    setup.rep.delete(f"/api/events/{event_id}/attachments/{attachment_id}")

    changes = setup.rep.get("/api/community/changes").get_json()["changes"]
    kinds = [c["change_type"] for c in changes]
    assert "MATERIAL_ATTACHED" in kinds
    assert "MATERIAL_REMOVED" in kinds


# ── File handling ──────────────────────────────────────────────────────────

def test_declared_type_must_match_the_bytes(client, academic_community):
    """A script renamed to .pdf is refused: the claim is not evidence."""
    setup = academic_community()
    resp = upload(setup.rep, setup.cos202_assignment["id"],
                  data=b"#!/bin/sh\nrm -rf /\n", name="evil.pdf",
                  content_type="application/pdf")
    assert resp.status_code == 400
    assert "do not match" in resp.get_json()["message"]


def test_unsupported_type_is_refused(client, academic_community):
    setup = academic_community()
    resp = upload(setup.rep, setup.cos202_assignment["id"],
                  data=b"MZ\x90\x00", name="thing.exe",
                  content_type="application/x-msdownload")
    assert resp.status_code == 400
    assert "not supported" in resp.get_json()["message"]


def test_oversized_file_is_refused_and_leaves_nothing_behind(
        client, academic_community, app):
    setup = academic_community()
    app.config["MAX_ATTACHMENT_BYTES"] = 1024
    big = b"%PDF-1.4\n" + b"0" * 4096
    resp = upload(setup.rep, setup.cos202_assignment["id"], data=big)
    assert resp.status_code == 400
    assert "larger than" in resp.get_json()["message"]
    assert setup.rep.get(
        f"/api/events/{setup.cos202_assignment['id']}").get_json()["event"]["attachments"] == []


def test_storage_key_is_generated_not_taken_from_the_filename(
        client, academic_community, app):
    """A filename is user input and never becomes a path."""
    setup = academic_community()
    resp = upload(setup.rep, setup.cos202_assignment["id"],
                  name="../../../../etc/passwd.pdf")
    assert resp.status_code == 201
    # The traversal is stripped for display...
    assert resp.get_json()["attachment"]["filename"] == "passwd.pdf"
    # ...and the bytes live under a generated key, in the upload root only.
    import os
    root = app.config["UPLOAD_DIR"]
    stored = [f for _, _, files in os.walk(root) for f in files]
    assert len(stored) == 1
    assert "passwd" not in stored[0]
    assert stored[0].endswith(".pdf")


def test_stored_file_is_not_executable(client, academic_community, app):
    import os
    import stat
    setup = academic_community()
    upload(setup.rep, setup.cos202_assignment["id"])
    root = app.config["UPLOAD_DIR"]
    paths = [os.path.join(d, f) for d, _, files in os.walk(root) for f in files]
    assert paths
    mode = os.stat(paths[0]).st_mode
    assert not mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_photo_of_a_handout_is_accepted(client, academic_community):
    """The common case: the lecturer put it on the board and someone
    photographed it."""
    setup = academic_community()
    resp = upload(setup.rep, setup.cos202_assignment["id"],
                  data=PNG, name="board.png", content_type="image/png")
    assert resp.status_code == 201
    assert resp.get_json()["attachment"]["content_type"] == "image/png"


def test_per_event_ceiling(client, academic_community, app):
    setup = academic_community()
    app.config["MAX_ATTACHMENTS_PER_EVENT"] = 2
    event_id = setup.cos202_assignment["id"]
    assert upload(setup.rep, event_id).status_code == 201
    assert upload(setup.rep, event_id).status_code == 201
    resp = upload(setup.rep, event_id)
    assert resp.status_code == 400
    assert "Remove one" in resp.get_json()["message"]


def test_cancelled_event_material_is_frozen(client, academic_community):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]
    setup.rep.post(f"/api/events/{event_id}/cancel")
    resp = upload(setup.rep, event_id)
    assert resp.status_code == 409


def test_upload_without_a_file_is_a_clear_refusal(client, academic_community):
    setup = academic_community()
    resp = setup.rep.post(
        f"/api/events/{setup.cos202_assignment['id']}/attachments",
        data={}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert "Choose a file" in resp.get_json()["message"]


# ── The description field ──────────────────────────────────────────────────

def test_description_is_editable_and_clearable(client, academic_community):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]
    version = setup.rep.get(f"/api/events/{event_id}").get_json()["event"]["version"]

    resp = setup.rep.put(f"/api/events/{event_id}",
                         json={"description": "Question 3 only.",
                               "expected_version": version})
    assert resp.status_code == 200
    assert resp.get_json()["event"]["description"] == "Question 3 only."

    version = resp.get_json()["event"]["version"]
    resp = setup.rep.put(f"/api/events/{event_id}",
                         json={"description": "", "expected_version": version})
    # Clearing is a legitimate edit, not a validation error.
    assert resp.status_code == 200
    assert resp.get_json()["event"]["description"] is None


def test_description_is_bounded(client, academic_community):
    setup = academic_community()
    resp = setup.rep.post("/api/events", json={
        "title": "Assignment", "event_type": "ASSIGNMENT",
        "description": "x" * 5000, "event_date": "2026-09-30"})
    assert resp.status_code == 400
    assert "4000" in resp.get_json()["message"]


def test_student_cannot_edit_the_description(client, academic_community):
    setup = academic_community()
    event_id = setup.cos202_assignment["id"]
    resp = setup.members[1].put(f"/api/events/{event_id}",
                                json={"description": "I changed this."})
    assert resp.status_code == 403


# ── Storage unit checks ────────────────────────────────────────────────────

@pytest.mark.parametrize("declared,head,ok", [
    ("application/pdf", b"%PDF-1.7 rest", True),
    ("application/pdf", b"<?php echo 1; ?>", False),
    ("image/png", b"\x89PNG\r\n\x1a\n...", True),
    ("image/jpeg", b"\xff\xd8\xff\xe0", True),
    ("image/jpg", b"\xff\xd8\xff\xe0", True),          # browsers send this
    ("image/webp", b"RIFF\x00\x00\x00\x00WEBPVP8 ", True),
    ("image/webp", b"RIFF\x00\x00\x00\x00AVI LIST", False),
    ("text/plain", "instructions".encode("utf-8"), True),
    ("text/plain", b"\xff\xfe\x00\x01", False),
    ("application/x-sh", b"#!/bin/sh", False),
])
def test_signature_validation(declared, head, ok):
    from academicai.errors import ValidationError
    if ok:
        assert attachment_storage.validate_type(declared, head)
    else:
        with pytest.raises(ValidationError):
            attachment_storage.validate_type(declared, head)


def test_generated_keys_are_unique_and_carry_our_extension():
    keys = {attachment_storage.new_storage_key("application/pdf") for _ in range(200)}
    assert len(keys) == 200
    assert all(k.endswith(".pdf") for k in keys)
