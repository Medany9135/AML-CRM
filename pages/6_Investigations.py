"""Investigations (cases) and STR filing."""

import streamlit as st

import db
import tm
from ui import NEON, md, setup, stat_card

setup("Investigations")
st.title("Investigations")
st.caption("Investigate alerts, write the narrative and decide: close with no suspicion, or file an STR.")
user = st.session_state["user"]
tm.init()

cases = tm.cases_df()
k1, k2, k3, k4 = st.columns(4)
stat_card(k1, "Open", int((cases.status == "Open").sum()), NEON["cyan"], "not started")
stat_card(k2, "Investigating", int((cases.status == "Investigating").sum()), NEON["amber"], "in progress")
stat_card(k3, "STR filed", int((cases.status == "STR filed").sum()), NEON["pink"], "reported to the FIU")
stat_card(k4, "Closed", int((cases.status == "Closed - no suspicion").sum()), NEON["green"], "no suspicion")

if cases.empty:
    st.info("No investigations yet. Open one from the alerts on the Transaction Monitoring page.")
    st.stop()

st.dataframe(cases[["id", "customer", "title", "priority", "status", "assigned_to", "opened_at", "closed_at"]],
             hide_index=True, width="stretch",
             column_config={"id": "Investigation", "customer": "Customer", "title": "Title", "priority": "Priority",
                            "status": "Status", "assigned_to": "Analyst", "opened_at": "Opened", "closed_at": "Closed"})

labels = {f"#{k.id} · {k.customer} · {k.status}": int(k.id) for k in cases.itertuples()}
default = st.session_state.get("open_case")
keys = list(labels)
idx = next((i for i, l in enumerate(keys) if labels[l] == default), 0)
case_id = labels[st.selectbox("Open investigation", keys, index=idx)]
k = cases[cases.id == case_id].iloc[0]
c = db.get_customer(int(k.customer_id))

st.divider()
st.header(f"Investigation #{case_id}: {k.title}")
st.markdown(f"**Customer:** {md(c['full_name'])} ({c['customer_type']}, {md(c['activity'])}) · **risk** {c['risk_rating']} · "
            f"**priority** {k.priority} · **status** {k.status}")

left, right = st.columns([1.2, 1])
with left:
    st.subheader("Alerts in this investigation")
    for a in tm.case_alerts(case_id).itertuples():
        st.markdown(f"- **[{a.severity}] {a.rule}**: {md(a.description)}")
    st.subheader("All transactions for this customer")
    t = tm.transactions_df(int(k.customer_id))
    st.dataframe(t[["ts", "txn_id", "direction", "channel", "amount_aed", "counterparty", "counterparty_country",
                    "description"]].sort_values("ts", ascending=False),
                 hide_index=True, width="stretch", height=280,
                 column_config={"amount_aed": st.column_config.NumberColumn("AED", format="%.0f")})
    with st.expander("KYC snapshot"):
        st.markdown(f"Nationality / incorporation: {md(c['nationality'])}  \nSource of funds: {md(c['source_of_funds'])}  \n"
                    f"Expected monthly volume: AED {c['expected_monthly_volume']:,.0f}  \nPEP: "
                    f"{'Yes' if c['pep'] else 'No'}  \nKYC status: {c['kyc_status']}")

with right:
    st.subheader("Investigation")
    closed = k.status in ("STR filed", "Closed - no suspicion")
    with st.form(f"case_{case_id}"):
        narrative = st.text_area(
            "Narrative: what happened, why it is unusual, what you checked", k.narrative or "", height=200,
            placeholder="Who, what, when, where, why and how. e.g. Between 20 and 25 Sep the customer deposited "
                        "AED 203,200 in four cash deposits each below AED 55,000...")
        status = st.radio("Decision", tm.CASE_STATUSES, index=tm.CASE_STATUSES.index(k.status), horizontal=False)
        note = st.text_input("Decision rationale / action taken", k.decision_note or "")
        go = st.form_submit_button("Save investigation", type="primary", disabled=closed)
    if go:
        if status in ("STR filed", "Closed - no suspicion") and (not narrative.strip() or not note.strip()):
            st.error("A narrative and a rationale are required before closing an investigation or filing an STR.")
        else:
            tm.update_case(case_id, status, narrative.strip(), note.strip(), user)
            st.success("Saved.")
            st.rerun()
    if closed:
        st.info(f"This investigation is closed ({k.status}). Open a new one for new activity.")
    if k.status == "STR filed" or status == "STR filed":
        st.download_button("Download STR draft (.txt)", tm.str_report(case_id), f"STR_case_{case_id}.txt",
                           "text/plain", type="primary")
        st.warning("STR filed: the customer is now rated High. Do not tip off the customer. Consider whether to "
                   "keep or exit the relationship, and watch for FIU requests.")
    with st.expander("Preview STR draft"):
        st.code(tm.str_report(case_id), language=None)

with st.expander("📘 AML note: writing a good STR"):
    st.markdown("""
The FIU reads hundreds of reports. A useful STR narrative answers **who, what, when, where, why and how**:

* **Who** is involved: the customer, counterparties, beneficial owners.
* **What** happened: the transactions, amounts and channels, with dates.
* **Why** it is suspicious: which red flags, and why the customer's explanation (if any) does not fit their profile.
* **What you did:** the checks you ran and any action taken (account restricted, relationship under review).

In the UAE, STRs go to the Financial Intelligence Unit through **goAML**, **without delay** once suspicion is formed.
There is no minimum amount. You must not tip off the customer, and you must keep the records for at least 5 years.
Filing in good faith protects you from liability, even if the suspicion turns out to be wrong.
""")
