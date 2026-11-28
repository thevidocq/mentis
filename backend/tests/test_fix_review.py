"""Regression tests for the independent code review of the 0.6.2 fixes (docs/security/review-v0.6.2.md, V-1..V-8)."""

import json

import pytest

from app.core import db as db_module
from app.services import answer as answering
from app.services import mail
from app.services.answer_check import judge, level1, units, values

P = {1: "Isolate WS01 with Defender. Call Laura Bianchi at +39 085 444 5566.",
     2: "Open the ticket. Escalate to Tier 2 within 15 minutes. Run Get-Process on WS01."}
CITS = [{"n": 1}, {"n": 2}]


# --- F1: an uncited factual line right before a code block / table is no longer flagged ----------

@pytest.mark.parametrize("tail", ["```\nGet-Process\n```", "| Host | Action |\n|---|---|\n| WS01 | isolate [1] |"])
def test_uncited_line_before_code_or_table_is_flagged(tail):
    answer = f"Isolate WS01 with Defender [1].\n\nWipe the domain controller and reset krbtgt twice now.\n\n{tail}"
    kinds = [(i["kind"], i["text"]) for i in level1(answer, CITS, P)]
    # a31f1e6 flagged it ("uncited"); HEAD marks it intro (it "heads" the next block) and skips it.
    assert ("uncited", "Wipe the domain controller and reset krbtgt twice now") in kinds, kinds


# --- F2: false positives of the new value kinds on correct paraphrases ----------------------------

CORRECT = [
    ("Open portal.acme.com [1].", "Open https://portal.acme.com/login"),          # domain vs url
    ("The mail domain is acme.it [1].", "Write to soc@acme.it"),                    # domain vs email
    ("Escalate in 2 to 4 hours [1].", "Escalate within 2-4 hours"),               # ok (control)
    ("Escalate between 2 and 4 hours [1].", "Escalate within 2-4 hours"),         # number vs range
    ("Escalate in 2 to 4 hours [1].", "Escalate between 2 and 4 hours"),          # range vs number
    ("Check Event ID 4625 [1].", "Look for Security event 4625"),                 # event vs number
    ("Allow port 3389 on 10.0.0.5 [1].", "RDP runs at 10.0.0.5:3389"),            # port vs ip:port
    ("Released on 15 March 2024 [1].", "Released 2024-03-15"),                    # numbers vs date
    ("Count 1,000 events [1].", "Count 1000 events"),                             # 1,000 vs 1000
    ("Office hours are 9 to 17 [1].", "Office hours 09:00-17:00"),                 # numbers vs times
    ("**Step 1 - Isolate** [1]\n\n- Isolate WS01 [1]", "Isolate WS01"),            # structural number
]


@pytest.mark.parametrize("ans,src", CORRECT)
def test_correct_paraphrase_has_no_value_issue(ans, src):
    issues = [i for i in level1(ans, [{"n": 1}], {1: src}) if i["kind"] == "value"]
    assert not issues, [(i["text"], i.get("value_kind")) for i in issues]


# --- F3: "80/443" is not a value at all (false negative) -------------------------------------------

def test_slash_separated_ports_are_compared():
    issues = values.check("Allow ports 8080/8443", {1: "Allow ports 80/443"}, ["Allow ports 80/443"])
    assert issues, "8080/8443 vs 80/443 passes unflagged: no value is extracted from 'N/M'"


# --- F4: judge reads digits of a quoted statement as statement numbers -----------------------------

def test_verdict_keyed_by_statement_text_flags_wrong_statements(monkeypatch):
    us = units.split("A [1].\n\nB [1].\n\nC [1].\n\nEscalate within 2 to 4 hours [1].\n\nE [1].")
    from app.services import llm

    reply = {"unsupported": [{"statement": "Escalate within 2 to 4 hours", "reason": "not in passage"}]}
    monkeypatch.setattr(llm, "call_provider", lambda *a, **k: llm.LLMReply(json.dumps(reply), 1, 1, "stop")
                        if hasattr(llm, "LLMReply") else type("R", (), {"text": json.dumps(reply), "input_tokens": 1,
                                                                      "output_tokens": 1, "stop": "stop"})())
    v = judge.judge({"name": "x", "model": "gpt"}, us, {1: "x"})
    flagged = sorted(us[x["unit"]].raw for x in v.unsupported)
    # Expected: unreadable (no statement number) -> LLMError, or only the 4th statement.
    assert flagged in ([], ["Escalate within 2 to 4 hours"]), flagged


# --- F5: link filter removes ordinary technology names -----------------------------------------------

@pytest.mark.parametrize("text", ["Read the ASP.NET/IIS logs.", "Check the Node.js/npm cache.",
                                  "See config.yaml/backup."])
def test_link_filter_keeps_plain_names(text):
    assert answering._safe_links(text, set(), []) == text


def test_smtp_password_not_kept_on_security_downgrade(super_admin):
    db = next(db_module.get_db())
    mail.save_smtp(db, {"host": "smtp.acme.example", "port": 465, "security": "ssl", "username": "u",
                        "from_address": "a@acme.example", "password": "S3cret!"})
    # Same host, TLS turned off and port moved: the stored password would go in clear text.
    cfg = mail.save_smtp(db, {"host": "smtp.acme.example", "port": 25, "security": "none"})
    db.close()
    assert not cfg.get("password_enc"), "password kept after security 'ssl' -> 'none' (sent unencrypted)"

def test_four_eyes_applies_to_scheduled_link_versions(super_admin):
    """A version fetched by the scheduled link check has uploaded_by=None (link_sources.sync with
    user_id=None), so the admin who set the link URL (Document.created_by) approves it alone."""
    from app.models import Document, DocumentVersion, Tenant, User
    from app.models.document import Approval, VersionStatus
    from app.services import versions

    db = next(db_module.get_db())
    owner = db.query(User).first()
    t = Tenant(name="FourEyes", slug="foureyes", settings={"require_approval": True, "approval_by_another": True})
    db.add(t)
    db.flush()
    doc = Document(tenant_id=t.id, name="Linked", name_key="linked", created_by=owner.id, source_url="https://x.example/p")
    db.add(doc)
    db.flush()
    v = DocumentVersion(document_id=doc.id, tenant_id=t.id, version=1, original_filename="p.html", file_type="html",
                        size_bytes=1, sha256="0" * 64, storage_key="k", status=VersionStatus.READY,
                        approval=Approval.PENDING, uploaded_by=None)  # as link_sources.sync(user_id=None)
    db.add(v)
    db.commit()
    try:
        versions.approve(db, v, owner.id)
        refused = False
    except versions.VersionError:
        refused = True
    except Exception:  # noqa: BLE001 - e.g. the vector index in tests: approval logic already passed
        refused = False
    db.rollback()
    db.close()
    assert refused, "the link owner approved a version of their own link alone"
