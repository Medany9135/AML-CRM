"""Compliance reports built from live Sanad data.

build(key, start, end) returns a report as a title plus a list of sections; each section is a heading and
either text or a table. The Reports page shows it, and exports it to Excel (one sheet per table) or to a
printable HTML file (open it in a browser and print to PDF).
"""

import html
import io
from datetime import date, timedelta

import pandas as pd

import db
import governance as gov
import sanctions
import tm

REPORTS = {
    "mlro": ("MLRO quarterly report", "Everything below in one pack, with the MLRO's conclusions.",
             "Senior management and Board"),
    "risk": ("Customer risk profile", "Risk distribution, high risk and PEP customers, EDD status.",
             "Compliance and Board"),
    "kyc": ("KYC and periodic reviews", "Pending KYC, expired IDs and licences, overdue reviews.",
            "Onboarding and compliance"),
    "sanctions": ("Sanctions screening", "Lists and update dates, alerts, decisions, FFR and PNMR.",
                  "MLRO and auditors"),
    "tm": ("Monitoring and investigations", "Alerts by rule, open alerts, investigations, STRs filed.",
           "MLRO and auditors"),
    "testing": ("Effectiveness testing", "Test results by area, findings and remediation status.",
                "Board and internal audit"),
    "policies": ("Policy register", "Policies, versions, approvals, review dates, staff attestation.",
                 "Board and inspections"),
    "ewra": ("Enterprise-wide risk assessment", "Inherent and residual risk by factor, appetite, action plan.",
             "Board and inspections"),
    "audit": ("Audit trail extract", "Who did what and when, in the period.", "Inspections"),
}


def periods(today: date | None = None) -> dict:
    t = today or date.today()
    q_start = date(t.year, 3 * ((t.month - 1) // 3) + 1, 1)
    prev_end = q_start - timedelta(days=1)
    prev_start = date(prev_end.year, 3 * ((prev_end.month - 1) // 3) + 1, 1)
    qn = lambda d: f"Q{(d.month - 1) // 3 + 1} {d.year}"   # noqa: E731
    return {
        "Last 3 months": (t - timedelta(days=91), t),
        f"This quarter ({qn(t)})": (q_start, t),
        f"Previous quarter ({qn(prev_end)})": (prev_start, prev_end),
        "Year to date": (date(t.year, 1, 1), t),
        "Last 12 months": (t - timedelta(days=365), t),
    }


def _in(series: pd.Series, start: date, end: date) -> pd.Series:
    s = series.fillna("").astype(str).str[:10]
    return (s >= start.isoformat()) & (s <= end.isoformat())


def _counts(series: pd.Series, name: str) -> pd.DataFrame:
    return series.value_counts().rename_axis(name).reset_index(name="Count")


# --- sections ---------------------------------------------------------------
def _risk(start, end):
    c = db.customers_df()
    today = date.today().isoformat()
    figures = pd.DataFrame({"Measure": ["Customers", "Companies", "Individuals", "High risk", "PEPs",
                                        "Onboarded in period"],
                            "Value": [len(c), int((c.customer_type == "Company").sum()),
                                      int((c.customer_type == "Individual").sum()),
                                      int((c.risk_rating == "High").sum()), int(c.pep.sum()),
                                      int(_in(c.created_at, start, end).sum())]})
    dist = (c.risk_rating.value_counts().reindex(["Low", "Medium", "High"], fill_value=0)
            .rename_axis("Risk rating").reset_index(name="Customers"))
    high = c[c.risk_rating == "High"][["id", "full_name", "customer_type", "risk_score", "kyc_status", "next_review"]]
    high = high.rename(columns={"id": "ID", "full_name": "Name", "customer_type": "Type", "risk_score": "Score",
                                "kyc_status": "KYC", "next_review": "Next review"})
    edd_missing = int(((c.risk_rating == "High") & (c.kyc_status != "Approved")).sum())
    return [("Customer risk: key figures", figures), ("Risk distribution", dist),
            ("High risk customers", high),
            ("Comment", f"{edd_missing} high risk customer(s) are not yet approved; EDD must be completed "
                        f"before approval. Data as at {today}.")]


def _kyc(start, end):
    c = db.customers_df()
    today = date.today().isoformat()
    cols = {"id": "ID", "full_name": "Name", "customer_type": "Type", "risk_rating": "Risk", "kyc_status": "KYC",
            "id_expiry": "ID / licence expiry", "next_review": "Next review"}
    pending = c[c.kyc_status.isin(["Pending", "Under review"])][list(cols)].rename(columns=cols)
    expired = c[c.id_expiry.notna() & (c.id_expiry < today)][list(cols)].rename(columns=cols)
    overdue = c[c.next_review < today][list(cols)].rename(columns=cols)
    figures = pd.DataFrame({"Measure": ["KYC pending or under review", "Expired IDs / licences", "Reviews overdue"],
                            "Value": [len(pending), len(expired), len(overdue)]})
    return [("KYC: key figures", figures), ("KYC status", _counts(c.kyc_status, "KYC status")),
            ("Pending KYC", pending), ("Expired IDs and licences", expired), ("Overdue periodic reviews", overdue)]


def _sanctions(start, end):
    sanctions.init()
    with db.connect() as conn:
        lists = pd.read_sql_query("SELECT list_name AS List, fetched_at AS Updated, names AS Names, status AS Status "
                                  "FROM sanctions_lists ORDER BY list_name", conn)
    a = sanctions.alerts_df()
    in_p = a[_in(a.created_at, start, end)]
    figures = pd.DataFrame({"Measure": ["Alerts raised in period", "Open alerts (all)", "False positives",
                                        "Potential matches (PNMR)", "True matches (FFR)"],
                            "Value": [len(in_p), int((a.status == "Open").sum()),
                                      int((a.status == "False positive").sum()),
                                      int(a.status.str.startswith("Potential").sum()),
                                      int((a.status == "True match").sum())]})
    detail = a[["customer", "screened_name", "matched_name", "list_name", "score", "status"]].rename(
        columns={"customer": "Customer", "screened_name": "Screened name", "matched_name": "Listed name",
                 "list_name": "List", "score": "Score", "status": "Status"})
    return [("Sanctions: key figures", figures), ("Lists loaded", lists), ("Alerts", detail)]


def _tm(start, end):
    a = tm.alerts_df()
    k = tm.cases_df()
    in_p = a[_in(a.created_at, start, end)]
    figures = pd.DataFrame({"Measure": ["Alerts raised in period", "Open alerts (all)", "Investigations opened in period",
                                        "Investigations open", "STRs filed in period"],
                            "Value": [len(in_p), int((a.status == "Open").sum()), int(_in(k.opened_at, start, end).sum()),
                                      int(k.status.isin(["Open", "Investigating"]).sum()),
                                      int(((k.status == "STR filed") & _in(k.closed_at, start, end)).sum())]})
    by_rule = (in_p.groupby(["rule", "severity"]).size().reset_index(name="Alerts")
               .rename(columns={"rule": "Rule", "severity": "Severity"}).sort_values("Alerts", ascending=False))
    inv = k[["id", "customer", "title", "priority", "status", "opened_at", "closed_at"]].rename(
        columns={"id": "#", "customer": "Customer", "title": "Title", "priority": "Priority", "status": "Status",
                 "opened_at": "Opened", "closed_at": "Closed"})
    return [("Monitoring: key figures", figures), ("Alerts by rule (period)", by_rule), ("Investigations", inv)]


def _testing(start, end):
    t = gov.tests_df()
    f = gov.findings_df()
    in_p = t[_in(t.tested_on, start, end)]
    figures = pd.DataFrame({"Measure": ["Tests in period", "Effective", "Partially effective", "Ineffective",
                                        "Open findings", "Overdue actions"],
                            "Value": [len(in_p), int((in_p.result == "Effective").sum()),
                                      int((in_p.result == "Partially effective").sum()),
                                      int((in_p.result == "Ineffective").sum()),
                                      int((f.status != "Closed").sum()), int((f.status == "Overdue").sum())]})
    tests = in_p[["tested_on", "area", "what", "sample", "passed", "result"]].rename(
        columns={"tested_on": "Tested", "area": "Area", "what": "What", "sample": "Sample", "passed": "Passed",
                 "result": "Result"})
    fnd = f[f.status != "Closed"][["finding", "area", "severity", "action", "owner", "due", "status"]].rename(
        columns={"finding": "Finding", "area": "From test", "severity": "Severity", "action": "Action",
                 "owner": "Owner", "due": "Due", "status": "Status"})
    return [("Testing: key figures", figures), ("Tests in period", tests), ("Open findings", fnd)]


def _policies(start, end):
    p = gov.policies_df()
    table = p[["name", "version", "approver", "approved_on", "next_review", "attested_pct", "status"]].rename(
        columns={"name": "Policy", "version": "Version", "approver": "Approved by", "approved_on": "Last approved",
                 "next_review": "Next review", "attested_pct": "Staff attested %", "status": "Status"})
    ctrl = pd.DataFrame(gov.policy_controls())
    return [("Policy register", table), ("Policy rules vs Sanad settings", ctrl)]


def _audit(start, end):
    a = db.audit_df()
    a = a[_in(a.ts, start, end) & (a.user != "seed")]
    return [("Audit trail", a[["ts", "user", "entity", "entity_id", "action", "details"]].rename(
        columns={"ts": "When", "user": "User", "entity": "Item", "entity_id": "ID", "action": "Action",
                 "details": "Details"}))]


def _ewra(start, end):
    import ewra
    e = ewra.current()
    if e is None:
        return [("Enterprise-wide risk assessment", "No assessment recorded yet.")]
    return ewra.report_sections(e)


def build(key: str, start: date, end: date) -> tuple[str, list]:
    title = REPORTS[key][0]
    parts = {"risk": _risk, "kyc": _kyc, "sanctions": _sanctions, "tm": _tm, "testing": _testing,
             "policies": _policies, "ewra": _ewra, "audit": _audit}
    if key != "mlro":
        return title, parts[key](start, end)
    sections = []
    for k in ["risk", "kyc", "sanctions", "tm", "testing", "policies", "ewra"]:
        secs = parts[k](start, end)
        sections += [s for s in secs if not (isinstance(s[1], pd.DataFrame) and len(s[1]) > 15)]
    return title, sections


# --- export -----------------------------------------------------------------
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(v):
    """Stop text typed into the app (a customer name, a note) from running as a formula in Excel.

    A name like =HYPERLINK("http://bad.site", "Click") would otherwise become a live formula when the
    report is opened. Text that starts with a formula character gets a leading apostrophe-style quote.
    Plain numbers and a lone "-" are left alone.
    """
    if isinstance(v, str) and len(v) > 1 and v.startswith(_FORMULA_START):
        try:
            float(v.replace(",", ""))
            return v          # a negative number written as text
        except ValueError:
            return "'" + v
    return v


def _safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_safe_cell(str(c)) for c in df.columns]
    for col in df.columns:
        if df[col].dtype == object or pd.api.types.is_string_dtype(df[col]):
            df[col] = df[col].map(_safe_cell)
    return df


def to_excel(title: str, sections: list, period: str, conclusions: str = "") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        cover = [["Report", title], ["Period", period], ["Prepared", date.today().isoformat()],
                 ["Source", "Sanad AML & Sanctions CMS (prototype, fictional data)"]]
        if conclusions:
            cover.append(["MLRO conclusions", conclusions])
        cover += [["Note", text] for head, text in sections if isinstance(text, str)]
        _safe_frame(pd.DataFrame(cover, columns=["Item", "Value"])).to_excel(xw, sheet_name="Summary", index=False)
        used = set()
        for head, body in sections:
            if isinstance(body, pd.DataFrame):
                name = "".join(ch for ch in head if ch not in "[]:*?/\\")[:31]
                while name in used:
                    name = name[:29] + str(len(used))
                used.add(name)
                _safe_frame(body).to_excel(xw, sheet_name=name, index=False)
    return buf.getvalue()


def to_html(title: str, sections: list, period: str, conclusions: str = "") -> str:
    e = html.escape
    out = [f"""<!doctype html><html><head><meta charset="utf-8"><title>{e(title)}</title><style>
body{{font-family:Arial,Helvetica,sans-serif;color:#222;max-width:900px;margin:32px auto;padding:0 16px}}
h1{{color:#0B3D5C;font-size:24px;margin:8px 0}} h2{{color:#0E7C7B;font-size:16px;margin:24px 0 8px}}
.head{{display:flex;justify-content:space-between;border-bottom:3px solid #0E7C7B;padding-bottom:8px;font-size:12px;color:#555}}
table{{border-collapse:collapse;width:100%;font-size:12px}} th,td{{border:1px solid #ddd;padding:5px 7px;text-align:left}}
th{{background:#F0F4F7}} .note{{font-size:13px;line-height:1.5}} @media print{{body{{margin:0}}}}
</style></head><body>
<div class="head"><b style="color:#0B3D5C;font-size:14px">Sanad · AML &amp; Sanctions CMS</b>
<span>CONFIDENTIAL · Prepared {date.today():%d %b %Y} · Period: {e(period)}</span></div>
<h1>{e(title)}</h1>"""]
    for head, body in sections:
        out.append(f"<h2>{e(head)}</h2>")
        if isinstance(body, pd.DataFrame):
            out.append(body.to_html(index=False, border=0, na_rep="-") if not body.empty else "<p class='note'>None.</p>")
        else:
            out.append(f"<p class='note'>{e(body)}</p>")
    if conclusions:
        out.append(f"<h2>MLRO conclusions and actions for management</h2><p class='note'>{e(conclusions)}</p>")
    out.append("<p class='note' style='color:#888;margin-top:32px'>Prototype with fictional data.</p></body></html>")
    return "\n".join(out)
