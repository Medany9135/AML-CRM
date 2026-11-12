"""Customer list and customer profile (KYC file)."""

import json
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import db
import sanctions
from ubo import analyse
from ui import badge, customer_form, md, setup

setup("Customers")
st.title("Customers")

df = db.customers_df()

# --- Filters ---------------------------------------------------------------
f1, f2, f3, f4 = st.columns([2, 1, 1, 1])
search = f1.text_input("Search name or ID", "")
ratings = f2.multiselect("Risk", ["High", "Medium", "Low"])
types = f3.multiselect("Type", ["Individual", "Company"])
statuses = f4.multiselect("KYC status", ["Pending", "Under review", "Approved", "Rejected"])

view = df
if search:
    s = search.lower()
    view = view[view["full_name"].str.lower().str.contains(s) | view["id_number"].fillna("").str.lower().str.contains(s)]
if ratings:
    view = view[view["risk_rating"].isin(ratings)]
if types:
    view = view[view["customer_type"].isin(types)]
if statuses:
    view = view[view["kyc_status"].isin(statuses)]

st.dataframe(
    view[["id", "full_name", "customer_type", "nationality", "activity", "risk_score", "risk_rating",
          "kyc_status", "next_review"]],
    hide_index=True, width="stretch",
    column_config={"id": "ID", "nationality": "Nationality", "activity": "Activity", "full_name": "Name", "customer_type": "Type", "risk_score": "Score",
                   "risk_rating": "Risk", "kyc_status": "KYC", "next_review": "Next review"},
)

# --- Profile -------------------------------------------------------------
if view.empty:
    st.stop()
options = {f"#{r.id} · {r.full_name}": int(r.id) for r in view.itertuples()}
default = st.session_state.get("open_customer")
labels = list(options)
idx = next((i for i, l in enumerate(labels) if options[l] == default), 0)
choice = st.selectbox("Open customer profile", labels, index=idx)
cid = options[choice]
st.session_state["open_customer"] = cid
c = db.get_customer(cid)
user = st.session_state["user"]

st.divider()
h1, h2, h3 = st.columns([3, 1, 1])
h1.header(c["full_name"])
h1.caption(f"{c['customer_type']} · {md(c['activity'])} · customer #{cid} since {c['created_at']}")
h2.markdown(f"**Risk rating**\n\n### {badge(c['risk_rating'])}\nscore {c['risk_score']}")
h3.markdown(f"**KYC status**\n\n### {c['kyc_status']}\nreview by {c['next_review']}")

if c["id_expiry"] and c["id_expiry"] < date.today().isoformat():
    st.warning(f"ID / licence expired on {c['id_expiry']}. Request an updated copy.")

tab_profile, tab_risk, tab_owners, tab_screen, tab_docs, tab_decision, tab_audit = st.tabs(
    ["Profile", "Risk assessment", "Ownership & UBO", "Screening", "Documents", "KYC decision", "Audit trail"])

with tab_screen:
    hits = sanctions.alerts_df(customer_id=cid)
    if hits.empty:
        st.success("No sanctions alerts for this customer or its owners.")
    else:
        st.dataframe(hits[["screened_name", "matched_name", "list_name", "score", "status", "decision_note"]],
                     hide_index=True, width="stretch",
                     column_config={"screened_name": "Our name", "matched_name": "Listed name", "list_name": "List",
                                    "score": "Score", "status": "Status", "decision_note": "Rationale"})
    if st.button("Screen this customer again"):
        n = sanctions.screen(cid, st.session_state.get("screen_threshold", 85), user)
        st.toast(f"{n} new alert(s)")
        st.rerun()
    st.page_link("pages/4_Sanctions_Screening.py", label="Review alerts on the Sanctions Screening page", icon="🛰️")

with tab_owners:
    if c["customer_type"] != "Company":
        st.info("Ownership applies to company customers. For an individual, the customer is the beneficial owner.")
    else:
        a = analyse(db.owners_for(cid))
        st.markdown(f"**Basis:** {md(a['basis'])}")
        for p in a["ubos"]:
            st.markdown(f"- **{md(p['name'])}** ({md(p['nationality'])}), {p['effective_pct']:g}% effective"
                        + (", **PEP**" if p["pep"] else ""))
        if not a["ubos"]:
            st.warning("No beneficial owner identified yet.")
        st.page_link("pages/3_Ownership_UBO.py", label="Open the ownership tree and edit owners", icon="🕸️")

with tab_profile:
    updated = customer_form(f"edit_{cid}", c)
    if updated:
        db.update_customer(cid, updated, user)
        st.success("Saved. Risk rating recalculated.")
        st.rerun()

with tab_risk:
    st.markdown(f"**Score {c['risk_score']} → {badge(c['risk_rating'])}**  "
                "(0-24 Low, 25-49 Medium, 50+ High; PEP or FATF black list forces High)")
    for reason in json.loads(c["risk_reasons"]):
        st.markdown(f"- {md(reason)}")
    st.caption("Rules live in risk.py. Change them there and every customer is rescored when edited.")

with tab_docs:
    docs = db.documents_for(cid)
    got = sum(d["received"] for d in docs)
    weight = 100 / len(docs) if docs else 0          # every document counts the same
    pct = got * weight
    chart_col, list_col = st.columns([1, 1.4])
    with chart_col:
        st.markdown("**Document completion**")
        parts = pd.DataFrame({"Status": ["Received", "Outstanding"],
                              "Share": [pct, 100 - pct],
                              "Documents": [got, len(docs) - got]})
        ring = alt.Chart(parts).mark_arc(innerRadius=70, outerRadius=105).encode(
            theta=alt.Theta("Share:Q", stack=True),
            color=alt.Color("Status:N", scale=alt.Scale(domain=["Received", "Outstanding"],
                                                        range=["#2CA02C", "#E6EAF1"]),
                            legend=alt.Legend(orient="bottom", title=None)),
            order=alt.Order("Status:N", sort="descending"),
            tooltip=["Status", "Documents", alt.Tooltip("Share:Q", title="%", format=".0f")])
        label = alt.Chart(pd.DataFrame({"t": [f"{pct:.0f}%"]})).mark_text(fontSize=28, fontWeight="bold").encode(
            text="t:N")
        st.altair_chart((ring + label).properties(height=260), width="stretch")
        st.caption(f"{got} of {len(docs)} received. Each document weighs {weight:.1f}%.")
    with list_col:
        st.markdown("**Checklist**")
        for d in docs:
            new = st.checkbox(f"{d['doc_type']} ({weight:.1f}%)", bool(d["received"]),
                              key=f"doc_{cid}_{d['doc_type']}")
            if new != bool(d["received"]):
                db.set_document(cid, d["doc_type"], new, user)
                st.rerun()

with tab_decision:
    docs_complete = all(d["received"] for d in db.documents_for(cid))
    with st.form(f"decision_{cid}"):
        status = st.radio("Decision", ["Approved", "Rejected", "Under review", "Pending"], horizontal=True)
        note = st.text_area("Rationale (required, goes to the audit trail)")
        go = st.form_submit_button("Record decision", type="primary")
    if go:
        if not note.strip():
            st.error("Please write a rationale. Regulators expect every decision to be documented.")
        elif status == "Approved" and not sanctions.alerts_df("Open", cid).empty:
            st.error("Cannot approve: there are open sanctions alerts. Review them first.")
        elif status == "Approved" and not sanctions.alerts_df("True match", cid).empty:
            st.error("Cannot approve: this customer has a confirmed sanctions match.")
        elif status == "Approved" and not docs_complete:
            st.error("Cannot approve: some KYC documents are still missing.")
        else:
            db.set_kyc_status(cid, status, note.strip(), user)
            st.success(f"Recorded: {status}")
            st.rerun()
    if c["risk_rating"] == "High":
        st.info("High risk: approval needs enhanced due diligence and senior management sign-off "
                "(both are on the document checklist).")

with tab_audit:
    st.dataframe(db.audit_df(cid), hide_index=True, width="stretch")

with st.expander("📘 AML note: what goes into a KYC file?"):
    st.markdown("""
Customer due diligence (CDD) means you **identify** the customer, **verify** that identity with
reliable documents, understand the **nature and purpose** of the relationship (activity, expected
volumes, source of funds), and keep it **up to date** through ongoing monitoring and periodic reviews.

Every decision needs a written rationale. In an inspection, the regulator reads the file, not your
memory, so the audit trail tab is as important as the decision itself. UAE law requires records to be
kept for at least **5 years** after the relationship ends.
""")
