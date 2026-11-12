"""Shared Streamlit pieces used by several pages."""

from datetime import date
from pathlib import Path
import re
import threading

import streamlit as st

import db
from risk import ACTIVITIES, CHANNELS, COUNTRIES, SOURCES_OF_FUNDS
from uae_activities import ACTIVITY_LIST

ASSETS = Path(__file__).parent / "assets"   # Sanad logo files

RATING_COLORS = {"High": "🔴", "Medium": "🟠", "Low": "🟢"}


# Colour palette for the ownership tree and number cards (Streamlit's default light theme).
NEON = {
    "cyan": "#0068C9", "violet": "#6D3FC0", "pink": "#D62728", "amber": "#E07B00",
    "green": "#2CA02C", "text": "#31333F", "muted": "#808495", "grid": "#E6EAF1",
}
RISK_PALETTE = {"Low": NEON["green"], "Medium": NEON["amber"], "High": NEON["pink"]}


def setup(title: str):
    st.set_page_config(page_title=f"Sanad · {title}", page_icon=str(ASSETS / "sanad-mark.png"), layout="wide")
    st.logo(str(ASSETS / "sanad-logo-compact.png"), icon_image=str(ASSETS / "sanad-mark.png"), size="large")
    _bootstrap()
    with st.sidebar:
        st.caption("Demo with fictional data only. Never enter real customer data.")
        st.session_state.setdefault("user", "analyst")
        st.session_state["user"] = st.text_input("Your name (for the audit log)", st.session_state["user"])


_demo_lock = threading.Lock()

DEMO_NARRATIVE = (
    "Between the dates shown, the customer made several cash deposits, each just below the AED 55,000 "
    "reporting threshold, within a few days. The pattern does not match the declared profile and source "
    "of funds. Next steps: request an explanation and supporting documents (without tipping off), check "
    "linked accounts, then decide whether to file an STR via goAML.")


def _bootstrap():
    """Create the demo database on first run. One lock, so two visitors arriving at once on a fresh
    database don't both seed it."""
    with _demo_lock:
        if db.is_empty():
            import seed
            seed.main()
        elif db.owners_missing():   # database created before the UBO module existed
            import seed
            seed.seed_owners()
        import sanctions
        if not sanctions.has_list("Training list"):   # always have the fictional training list to practise with
            sanctions.load_training_list()
            sanctions.screen(user="seed")
        _load_demo_data()
        import governance
        governance.seed_demo()
        import ewra
        ewra.seed_demo()


def _load_demo_data():
    """Demo mode: on a fresh database, load the sample transactions, run the monitoring rules and open one
    investigation, so every page has something to show. Runs once; does nothing if transactions exist."""
    import copy

    import pandas as pd

    import tm
    # Called inside _bootstrap's lock.
    tm.init()
    if not tm.transactions_df().empty:
        return
    sample = Path(__file__).parent / "data" / "sample_transactions.csv"
    if not sample.exists():
        return
    tm.import_csv(pd.read_csv(sample, dtype=str), "sample_transactions.csv", "demo")
    tm.run_rules(copy.deepcopy(tm.DEFAULT_RULES), "demo")
    alerts = tm.alerts_df("Open")
    reza = alerts[alerts.customer == "Reza Tehrani"]
    if tm.cases_df().empty and not reza.empty:
        case_id = tm.open_case(int(reza.customer_id.iloc[0]), [int(i) for i in reza.id],
                               "Reza Tehrani: possible structuring", "High", "demo")
        tm.update_case(case_id, "Investigating", DEMO_NARRATIVE, "", "demo")


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~$:])")


def md(text) -> str:
    """Make text typed into the app (names, notes, descriptions) safe to show inside st.markdown.

    Streamlit already blocks HTML and scripts. This also stops someone's input from turning into a link,
    an image from another website, LaTeX or bold headings: the text is shown exactly as typed.
    """
    if text is None:
        return ""
    text = str(text).replace("://", ":\u200b//").replace("www.", "www\u200b.")   # no automatic links
    return _MD_SPECIAL.sub(r"\\\1", text).replace("\n", " ")


def badge(rating: str) -> str:
    return f"{RATING_COLORS.get(rating, '')} {rating}"


def _idx(options, value, default=0):
    return options.index(value) if value in options else default


def _to_date(value):
    """Turn a stored YYYY-MM-DD string into a date for st.date_input (None if empty or invalid)."""
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def customer_form(key: str, existing: dict | None = None, customer_type: str | None = None) -> dict | None:
    """Add or edit form. Returns the field values when submitted, else None.

    Individuals and companies get different forms. The type comes from the existing record, or from
    the choice made on the Add Customer page.
    """
    e = existing or {}
    ctype = customer_type or e.get("customer_type") or "Individual"
    if ctype == "Company":
        return _company_form(key, e)
    return _individual_form(key, e)


def _risk_profile_fields(e: dict, is_co: bool):
    """Fields that drive the risk rating and transaction monitoring, shared by both forms."""
    c1, c2 = st.columns(2)
    sof = c1.selectbox("Source of funds", SOURCES_OF_FUNDS, index=_idx(SOURCES_OF_FUNDS, e.get("source_of_funds")))
    volume = c2.number_input("Expected monthly volume (AED)", min_value=0.0, step=10_000.0,
                             value=float(e.get("expected_monthly_volume") or 0))
    channel = c1.selectbox("Onboarding channel", CHANNELS, index=_idx(CHANNELS, e.get("channel")))
    c2.write("")
    pep = c2.checkbox("PEP among owners / directors" if is_co else "Politically exposed person (PEP)",
                      bool(e.get("pep")))
    cash = c2.checkbox("Cash intensive", bool(e.get("cash_intensive")))
    return dict(source_of_funds=sof, expected_monthly_volume=volume, channel=channel, pep=int(pep),
                cash_intensive=int(cash))


def _individual_form(key: str, e: dict) -> dict | None:
    today = date.today()
    with st.form(key):
        c1, c2 = st.columns(2)
        name = c1.text_input("Full name", e.get("full_name", ""))
        dob = c2.date_input("Date of birth", _to_date(e.get("date_of_birth")), min_value=date(1900, 1, 1),
                            max_value=today, format="DD/MM/YYYY")
        nationality = c1.selectbox("Nationality", COUNTRIES,
                                   index=_idx(COUNTRIES, e.get("nationality", "United Arab Emirates")))
        residence = c2.selectbox("Country of residence", COUNTRIES,
                                 index=_idx(COUNTRIES, e.get("residence_country", "United Arab Emirates")))
        id_number = c1.text_input("Emirates ID / passport no.", e.get("id_number") or "")
        id_expiry = c2.date_input("ID expiry date", _to_date(e.get("id_expiry")), min_value=date(2000, 1, 1),
                                  max_value=date(today.year + 20, 12, 31), format="DD/MM/YYYY")
        activity = c1.selectbox("Occupation", ACTIVITIES, index=_idx(ACTIVITIES, e.get("activity")))
        st.markdown("**Risk profile**")
        profile = _risk_profile_fields(e, is_co=False)
        submitted = st.form_submit_button("Save customer", type="primary")
    if not submitted:
        return None
    if not name.strip():
        st.error("Full name is required.")
        return None
    return dict(customer_type="Individual", full_name=name.strip(),
                date_of_birth=dob.isoformat() if dob else None, nationality=nationality,
                residence_country=residence, id_number=id_number.strip() or None,
                id_expiry=id_expiry.isoformat() if id_expiry else None, activity=activity, **profile)


def _company_form(key: str, e: dict) -> dict | None:
    today = date.today()
    activities = ACTIVITY_LIST if e.get("activity") in ACTIVITY_LIST or not e.get("activity") \
        else [e["activity"]] + ACTIVITY_LIST   # keep an older activity value selectable
    with st.form(key):
        st.markdown("**Company details**")
        c1, c2 = st.columns(2)
        name = c1.text_input("Company full name", e.get("full_name", ""))
        country = c2.selectbox("Incorporation country", COUNTRIES,
                               index=_idx(COUNTRIES, e.get("nationality", "United Arab Emirates")))
        licence_no = c1.text_input("Registration / trade licence no.", e.get("id_number") or "")
        activity = c2.selectbox("Trade licence activity", activities, index=_idx(activities, e.get("activity")),
                                help="Sample of UAE licence activities with their AML risk level (uae_activities.py).")
        registered = c1.date_input("Licence registration date", _to_date(e.get("date_of_birth")),
                                   min_value=date(1950, 1, 1), max_value=today, format="DD/MM/YYYY")
        expiry = c2.date_input("Licence expiry date", _to_date(e.get("id_expiry")), min_value=date(2000, 1, 1),
                               max_value=date(today.year + 20, 12, 31), format="DD/MM/YYYY")
        st.markdown("**Risk profile**")
        profile = _risk_profile_fields(e, is_co=True)
        submitted = st.form_submit_button("Save company", type="primary")
    if not submitted:
        return None
    problems = []
    if not name.strip():
        problems.append("Company full name is required.")
    if not licence_no.strip():
        problems.append("Registration / trade licence no. is required.")
    if registered and expiry and expiry <= registered:
        problems.append("Licence expiry date must be after the registration date.")
    for p in problems:
        st.error(p)
    if problems:
        return None
    return dict(customer_type="Company", full_name=name.strip(),
                date_of_birth=registered.isoformat() if registered else None,   # stored as the licence date
                nationality=country, residence_country=country, id_number=licence_no.strip(),
                id_expiry=expiry.isoformat() if expiry else None, activity=activity, **profile)


def stat_card(col, label: str, value, color: str = "", sub: str = ""):
    """A plain Streamlit number tile with a short note underneath."""
    col.metric(label, value)
    if sub:
        col.caption(sub)
