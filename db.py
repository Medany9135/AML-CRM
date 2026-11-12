"""SQLite storage for the AML CRM prototype. The database is one file, aml_crm.db."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from risk import next_review_date, required_documents, score_customer
from ubo import analyse

DB_PATH = Path(__file__).with_name("aml_crm.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_type TEXT NOT NULL,          -- Individual or Company
    full_name TEXT NOT NULL,
    date_of_birth TEXT,                   -- or date of incorporation
    nationality TEXT,                     -- or country of incorporation
    residence_country TEXT,               -- or country of operations
    id_number TEXT,                       -- Emirates ID, passport or licence no.
    id_expiry TEXT,
    activity TEXT,                        -- occupation or business activity
    source_of_funds TEXT,
    expected_monthly_volume REAL,
    pep INTEGER DEFAULT 0,
    cash_intensive INTEGER DEFAULT 0,
    channel TEXT,
    risk_score INTEGER,
    risk_rating TEXT,
    risk_reasons TEXT,                    -- JSON list
    kyc_status TEXT DEFAULT 'Pending',    -- Pending, Approved, Rejected, Under review
    next_review TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    doc_type TEXT NOT NULL,
    received INTEGER DEFAULT 0,
    UNIQUE(customer_id, doc_type)
);
CREATE TABLE IF NOT EXISTS owners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),  -- the company customer
    parent_owner_id INTEGER REFERENCES owners(id),          -- empty = owns the customer directly
    name TEXT NOT NULL,
    owner_type TEXT NOT NULL,                               -- Individual or Company
    nationality TEXT,                                       -- or country of incorporation
    pct REAL DEFAULT 0,                                     -- shareholding in the parent
    role TEXT DEFAULT 'Shareholder',                        -- Shareholder, Director, Senior manager
    pep INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user TEXT,
    entity TEXT,
    entity_id INTEGER,
    action TEXT,
    details TEXT
);
"""


@contextmanager
def connect():
    """Open the database, commit on success, and always close it.

    Closing matters on Windows, which cannot delete or replace a file that is still open.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def log(conn, entity: str, entity_id: int, action: str, details: str = "", user: str = "analyst"):
    conn.execute(
        "INSERT INTO audit_log (ts, user, entity, entity_id, action, details) VALUES (?,?,?,?,?,?)",
        (datetime.now().isoformat(timespec="seconds"), user, entity, entity_id, action, details),
    )


def _owners(conn, cid) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM owners WHERE customer_id=? ORDER BY id", (cid,))]


def _sanction_hits(conn, cid) -> int:
    try:
        return conn.execute("SELECT COUNT(*) FROM screening_alerts WHERE customer_id=? AND status='True match'",
                            (cid,)).fetchone()[0]
    except sqlite3.OperationalError:   # screening table not created yet
        return 0


def _str_filed(conn, cid) -> bool:
    try:
        return conn.execute("SELECT COUNT(*) FROM cases WHERE customer_id=? AND status='STR filed'",
                            (cid,)).fetchone()[0] > 0
    except sqlite3.OperationalError:   # cases table not created yet
        return False


def _apply_risk(c: dict, reviewed_on: date | None = None, owners: list[dict] | None = None,
                sanction_hits: int = 0, str_filed: bool = False) -> dict:
    ownership = analyse(owners or []) if c.get("customer_type") == "Company" else None
    score, rating, reasons = score_customer(c, ownership, sanction_hits, str_filed)
    c.update(risk_score=score, risk_rating=rating, risk_reasons=json.dumps(reasons),
             next_review=next_review_date(rating, reviewed_on).isoformat())
    return c


def _sync_documents(conn, customer_id: int, customer_type: str, rating: str):
    for doc in required_documents(customer_type, rating):
        conn.execute("INSERT OR IGNORE INTO documents (customer_id, doc_type) VALUES (?,?)",
                     (customer_id, doc))


# --- Server-side validation -------------------------------------------------------------------
# The forms already check their input, but every save also passes through these checks, so data that
# skips the form (a tampered request, an AI extraction, a script) cannot put bad values in the database.
CUSTOMER_TYPES = {"Individual", "Company"}
KYC_STATUSES = {"Pending", "Approved", "Rejected", "Under review"}
OWNER_TYPES = {"Individual", "Company"}
OWNER_ROLES = {"Shareholder", "Director", "Senior manager"}
EDITABLE_COLUMNS = {"customer_type", "full_name", "date_of_birth", "nationality", "residence_country",
                    "id_number", "id_expiry", "activity", "source_of_funds", "expected_monthly_volume",
                    "pep", "cash_intensive", "channel", "kyc_status", "created_at"}
MAX_NAME = 200
MAX_TEXT = 500


def _check_text(field: str, value, limit: int = MAX_TEXT):
    if value is not None and len(str(value)) > limit:
        raise ValueError(f"{field} is too long (limit {limit} characters).")


def _check_date(field: str, value):
    if value in (None, ""):
        return
    try:
        date.fromisoformat(str(value)[:10])
    except ValueError:
        raise ValueError(f"{field} must be a date (YYYY-MM-DD).") from None


def validate_customer(c: dict) -> dict:
    """Check a customer record before it is saved. Raises ValueError with a plain message."""
    unknown = set(c) - EDITABLE_COLUMNS - {"id", "risk_score", "risk_rating", "risk_reasons", "next_review"}
    if unknown:
        raise ValueError(f"Unknown customer field(s): {', '.join(sorted(map(str, unknown)))}")
    if c.get("customer_type") not in CUSTOMER_TYPES:
        raise ValueError("Customer type must be Individual or Company.")
    name = str(c.get("full_name") or "").strip()
    if not name:
        raise ValueError("Full name is required.")
    _check_text("Full name", name, MAX_NAME)
    for k in ("nationality", "residence_country", "id_number", "activity", "source_of_funds", "channel"):
        _check_text(k.replace("_", " ").capitalize(), c.get(k))
    for k in ("date_of_birth", "id_expiry", "created_at"):
        _check_date(k.replace("_", " ").capitalize(), c.get(k))
    try:
        volume = float(c.get("expected_monthly_volume") or 0)
    except (TypeError, ValueError):
        raise ValueError("Expected monthly volume must be a number.") from None
    if not 0 <= volume < 1e13:
        raise ValueError("Expected monthly volume must be zero or more.")
    if c.get("kyc_status") not in (None, *KYC_STATUSES):
        raise ValueError("Unknown KYC status.")
    c = dict(c, full_name=name, expected_monthly_volume=volume,
             pep=int(bool(c.get("pep"))), cash_intensive=int(bool(c.get("cash_intensive"))))
    return c


def add_customer(c: dict, user: str = "analyst") -> int:
    c = validate_customer(c)
    c.setdefault("created_at", date.today().isoformat())
    c = _apply_risk(c, date.fromisoformat(c["created_at"]))
    cols = [k for k in c if k != "id"]
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO customers ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [c[k] for k in cols],
        )
        cid = cur.lastrowid
        _sync_documents(conn, cid, c["customer_type"], c["risk_rating"])
        log(conn, "customer", cid, "created", f"Risk {c['risk_rating']} ({c['risk_score']})", user)
    return cid


def update_customer(cid: int, changes: dict, user: str = "analyst"):
    with connect() as conn:
        current = dict(conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone())
        old_rating = current["risk_rating"]
        old_review = current["next_review"]
        current.update(changes)
        current = validate_customer(current)
        current = _apply_risk(current, owners=_owners(conn, cid), sanction_hits=_sanction_hits(conn, cid),
                              str_filed=_str_filed(conn, cid))
        if current["risk_rating"] == old_rating:
            current["next_review"] = old_review  # only a rating change moves the review date
        cols = [k for k in current if k != "id"]
        conn.execute(f"UPDATE customers SET {','.join(f'{k}=?' for k in cols)} WHERE id=?",
                     [current[k] for k in cols] + [cid])
        _sync_documents(conn, cid, current["customer_type"], current["risk_rating"])
        log(conn, "customer", cid, "updated",
            f"Risk {old_rating} -> {current['risk_rating']} ({current['risk_score']})", user)


def approval_blockers(conn, cid: int) -> list[str]:
    out = []
    try:
        alerts = dict(conn.execute("SELECT status, COUNT(*) FROM screening_alerts WHERE customer_id=? "
                                   "GROUP BY status", (cid,)).fetchall())
    except sqlite3.OperationalError:   # screening table not created yet
        alerts = {}
    if alerts.get("Open"):
        out.append("there are open sanctions alerts")
    if alerts.get("True match"):
        out.append("this customer has a confirmed sanctions match")
    missing = conn.execute("SELECT COUNT(*) FROM documents WHERE customer_id=? AND received=0", (cid,)).fetchone()[0]
    if missing:
        out.append("some KYC documents are still missing")
    return out


def set_kyc_status(cid: int, status: str, note: str, user: str = "analyst"):
    if status not in KYC_STATUSES:
        raise ValueError("Unknown KYC status.")
    _check_text("Note", note, 5000)
    if user != "seed" and not str(note or "").strip():
        raise ValueError("A rationale is required for every KYC decision.")
    with connect() as conn:
        if status == "Approved" and user != "seed":
            # Same rules as the Customers page, enforced again here so no other route can skip them.
            blockers = approval_blockers(conn, cid)
            if blockers:
                raise ValueError("Cannot approve: " + "; ".join(blockers))
        conn.execute("UPDATE customers SET kyc_status=? WHERE id=?", (status, cid))
        if status == "Approved" and user != "seed":
            # An approval completes a review, so the next one is due a full cycle from today.
            rating = conn.execute("SELECT risk_rating FROM customers WHERE id=?", (cid,)).fetchone()[0]
            conn.execute("UPDATE customers SET next_review=? WHERE id=?",
                         (next_review_date(rating).isoformat(), cid))
        log(conn, "customer", cid, f"KYC status: {status}", note, user)


def set_document(cid: int, doc_type: str, received: bool, user: str = "analyst"):
    with connect() as conn:
        conn.execute("UPDATE documents SET received=? WHERE customer_id=? AND doc_type=?",
                     (int(received), cid, doc_type))
        log(conn, "customer", cid, "document " + ("received" if received else "removed"), doc_type, user)


def owners_for(cid: int) -> list[dict]:
    with connect() as conn:
        return _owners(conn, cid)


def add_owner(cid: int, owner: dict, user: str = "analyst") -> int:
    name = str(owner.get("name") or "").strip()
    if not name:
        raise ValueError("Owner name is required.")
    _check_text("Owner name", name, MAX_NAME)
    _check_text("Nationality", owner.get("nationality"))
    if owner.get("owner_type") not in OWNER_TYPES:
        raise ValueError("Owner type must be Individual or Company.")
    if owner.get("role", "Shareholder") not in OWNER_ROLES:
        raise ValueError("Unknown owner role.")
    try:
        pct = float(owner.get("pct") or 0)
    except (TypeError, ValueError):
        raise ValueError("Shareholding must be a number.") from None
    if not 0 <= pct <= 100:
        raise ValueError("Shareholding must be between 0 and 100%.")
    owner = dict(owner, name=name, pct=pct)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO owners (customer_id, parent_owner_id, name, owner_type, nationality, pct, role, pep) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cid, owner.get("parent_owner_id"), owner["name"], owner["owner_type"], owner.get("nationality"),
             owner.get("pct") or 0, owner.get("role", "Shareholder"), int(owner.get("pep") or 0)))
        log(conn, "customer", cid, "owner added",
            f"{owner['name']} ({owner['owner_type']}, {owner.get('role')}, {owner.get('pct') or 0}%)", user)
        oid = cur.lastrowid
    update_customer(cid, {}, user)   # rescore with the new structure
    return oid


def delete_owner(cid: int, owner_id: int, user: str = "analyst"):
    """Delete an owner and everything recorded underneath it."""
    with connect() as conn:
        todo, gone = [owner_id], []
        while todo:
            oid = todo.pop()
            gone.append(oid)
            todo += [r[0] for r in conn.execute("SELECT id FROM owners WHERE parent_owner_id=?", (oid,))]
        name = conn.execute("SELECT name FROM owners WHERE id=?", (owner_id,)).fetchone()[0]
        conn.executemany("DELETE FROM owners WHERE id=?", [(i,) for i in gone])
        log(conn, "customer", cid, "owner removed", f"{name} (and {len(gone) - 1} below it)", user)
    update_customer(cid, {}, user)


def owners_missing() -> bool:
    """True when there are companies but no ownership recorded yet (older databases)."""
    with connect() as conn:
        companies = conn.execute("SELECT COUNT(*) FROM customers WHERE customer_type='Company'").fetchone()[0]
        owners = conn.execute("SELECT COUNT(*) FROM owners").fetchone()[0]
        return companies > 0 and owners == 0


def customers_df() -> pd.DataFrame:
    with connect() as conn:
        return pd.read_sql_query("SELECT * FROM customers ORDER BY id", conn)


def get_customer(cid: int) -> dict:
    with connect() as conn:
        return dict(conn.execute("SELECT * FROM customers WHERE id=?", (cid,)).fetchone())


def documents_for(cid: int) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT doc_type, received FROM documents WHERE customer_id=? ORDER BY id", (cid,))]


def audit_df(entity_id: int | None = None) -> pd.DataFrame:
    with connect() as conn:
        if entity_id is None:
            return pd.read_sql_query("SELECT * FROM audit_log ORDER BY id DESC", conn)
        return pd.read_sql_query(
            "SELECT ts, user, action, details FROM audit_log WHERE entity='customer' AND entity_id=? ORDER BY id DESC",
            conn, params=(entity_id,))


def is_empty() -> bool:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0


def reset():
    DB_PATH.unlink(missing_ok=True)
