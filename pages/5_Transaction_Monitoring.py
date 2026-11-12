"""Upload transactions, run monitoring rules and triage the alerts."""

import copy
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import db
import tm
from ui import NEON, md, setup, stat_card

setup("Transaction monitoring")
st.title("Transaction monitoring")
st.caption("Upload transactions as CSV, run the detection rules, and turn alerts into investigations.")
user = st.session_state["user"]
tm.init()
st.session_state.setdefault("tm_rules", copy.deepcopy(tm.DEFAULT_RULES))
rules = st.session_state["tm_rules"]

txns = tm.transactions_df()
alerts = tm.alerts_df()
open_alerts = alerts[alerts.status == "Open"]

k1, k2, k3, k4 = st.columns(4)
stat_card(k1, "Transactions", f"{len(txns):,}", NEON["cyan"],
          f"AED {txns.amount_aed.sum() / 1e6:,.1f}m total" if not txns.empty else "upload a CSV to start")
stat_card(k2, "Open alerts", len(open_alerts), NEON["pink"],
          f"{int((open_alerts.severity.isin(['Critical', 'High'])).sum())} critical or high")
stat_card(k3, "Customers alerted", open_alerts.customer_id.nunique(), NEON["amber"], "with open alerts")
stat_card(k4, "Open investigations", int((tm.cases_df().status.isin(["Open", "Investigating"])).sum()), NEON["violet"],
          "see the Investigations page")

with st.expander("📘 AML note: how transaction monitoring works"):
    st.markdown("""
Transaction monitoring compares what customers **actually do** with what you **expect** from their KYC profile,
and with known money laundering **typologies**. Each rule here is a typology:

* **Structuring (smurfing):** splitting cash into amounts just under a reporting threshold.
* **Rapid movement / pass-through:** money arrives and leaves within days, typical of layering and mule accounts.
* **High risk jurisdictions:** flows to FATF black or grey list countries need extra scrutiny.
* **Profile deviation:** activity far above the declared expected volume or out of line with the occupation.
* **Round amounts and large cash:** common in trade-based laundering and cash-intensive businesses.

An alert is **not** a suspicion yet. The analyst reviews it, looks for a legitimate explanation (ask the customer
only if it won't tip them off), and either closes it with a rationale or opens an **investigation**. If suspicion remains,
file an **STR** to the UAE FIU through goAML **without delay**, and never tell the customer (tipping off is a crime
under Federal Decree-Law No. 20 of 2018).

*Try it:* load the sample file, run the rules, then look at Reza Tehrani (structuring), Blue Harbour Holdings
(pass-through to a sanctioned name) and Priya Nair (salary account with sudden large inflows).
""")

tab_alerts, tab_upload, tab_rules, tab_data = st.tabs(["Alerts", "Upload transactions", "Rules", "Transactions"])

# --- Upload -------------------------------------------------------------------
with tab_upload:
    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.markdown("**Upload a CSV**")
        up = st.file_uploader("Transactions file", type=["csv"])
        if up is not None and st.button("Import file", type="primary"):
            res = tm.import_csv(pd.read_csv(up, dtype=str), up.name, user)
            st.success(f"{res['added']} transactions added, {res['skipped']} duplicates skipped.")
            for p in res["problems"][:20]:
                st.warning(p)
        st.markdown("**Or use the sample file**")
        st.caption("436 fictional transactions over 90 days for the dummy customers, with planted red flags.")
        sample = Path(__file__).parent.parent / "data" / "sample_transactions.csv"
        if st.button("Load sample transactions", disabled=not sample.exists()):
            res = tm.import_csv(pd.read_csv(sample, dtype=str), "sample_transactions.csv", user)
            n = tm.run_rules(rules, user)
            st.success(f"{res['added']} transactions added and monitored: {n} new alerts.")
            st.rerun()
    with c2:
        st.markdown("**File format**")
        st.dataframe(pd.DataFrame({
            "Column": ["txn_id", "customer_id", "date", "amount", "currency", "direction", "channel",
                       "counterparty", "counterparty_country", "description"],
            "Example": ["T-0001", "7", "2026-10-01 10:15", "12000", "AED", "IN or OUT",
                        "Cash, Wire, Card, Cheque, Transfer", "ACME Payroll LLC", "United Arab Emirates", "Salary"],
        }), hide_index=True, width="stretch")
        st.download_button("Download a template", tm.sample_csv(), "transactions_template.csv", "text/csv")

# --- Rules ------------------------------------------------------------------
with tab_rules:
    st.caption("Tune the rules and run them again. Changes last for this browser session; defaults live in tm.py.")
    for key, r in rules.items():
        with st.container(border=True):
            a, b = st.columns([1, 2])
            r["on"] = a.toggle(r["label"], r["on"], key=f"on_{key}")
            b.caption(r["why"])
            nums = [k for k, v in r.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
            cols = st.columns(max(len(nums), 1))
            for col, k in zip(cols, nums):
                r[k] = col.number_input(k.replace("_", " ").capitalize(), value=r[k], key=f"{key}_{k}",
                                        step=0.1 if isinstance(r[k], float) else 1)
    if st.button("Run all rules now", type="primary"):
        n = tm.run_rules(rules, user)
        st.success(f"{n} new alerts.")
        st.rerun()

# --- Transactions -------------------------------------------------------------
with tab_data:
    if txns.empty:
        st.info("No transactions yet.")
    else:
        daily = (txns.assign(day=txns.ts.dt.floor("D"))
                 .groupby(["day", "direction"]).amount_aed.sum().reset_index())
        st.bar_chart(daily, x="day", y="amount_aed", color="direction", x_label="", y_label="AED", height=220)
        who = st.selectbox("Customer", ["All"] + sorted(txns.customer.unique()))
        view = txns if who == "All" else txns[txns.customer == who]
        st.dataframe(view[["ts", "txn_id", "customer", "direction", "channel", "amount", "currency", "amount_aed",
                           "counterparty", "counterparty_country", "description"]].sort_values("ts", ascending=False),
                     hide_index=True, width="stretch",
                     column_config={"amount_aed": st.column_config.NumberColumn("AED", format="%.0f")})

# --- Alerts -------------------------------------------------------------------
with tab_alerts:
    if alerts.empty:
        st.info("No alerts yet. Load the sample transactions from the 'Upload transactions' tab.")
    else:
        left, right = st.columns([1, 2])
        with left:
            st.subheader("Open alerts by rule")
            by_rule = open_alerts.groupby("rule").size().rename("Alerts")
            if not by_rule.empty:
                st.bar_chart(by_rule, horizontal=True, height=230)
        with right:
            show = st.multiselect("Status", sorted(alerts.status.unique()), default=["Open"])
            view = alerts[alerts.status.isin(show)] if show else alerts
            st.dataframe(view[["id", "severity", "customer", "rule", "description", "total_aed", "status"]],
                         hide_index=True, width="stretch", height=300,
                         column_config={"id": "Alert", "total_aed": st.column_config.NumberColumn("AED", format="%.0f")})

        if not open_alerts.empty:
            st.divider()
            cust = st.selectbox("Work alerts for customer",
                                sorted(open_alerts.customer.unique(),
                                       key=lambda n: open_alerts[open_alerts.customer == n].severity
                                       .map({s: i for i, s in enumerate(tm.SEVERITY_ORDER)}).min()))
            mine = open_alerts[open_alerts.customer == cust]
            cid = int(mine.customer_id.iloc[0])
            c = db.get_customer(cid)
            st.markdown(f"**{md(cust)}** · {c['customer_type']} · {md(c['activity'])} · risk {c['risk_rating']} · "
                        f"expected AED {c['expected_monthly_volume']:,.0f} per month")
            picked = []
            for a in mine.itertuples():
                with st.container(border=True):
                    top = st.columns([0.08, 0.92])
                    if top[0].checkbox("Include", key=f"pick_{a.id}", value=True, label_visibility="collapsed"):
                        picked.append(a.id)
                    top[1].markdown(f"**[{a.severity}] {a.rule}**: {md(a.description)}")
                    with top[1].expander("Transactions"):
                        t = tm.alert_transactions(mine[mine.id == a.id].iloc[0])
                        st.dataframe(t[["ts", "txn_id", "direction", "channel", "amount_aed", "counterparty",
                                        "counterparty_country"]], hide_index=True, width="stretch")
            a1, a2 = st.columns(2)
            with a1.form("new_case_form"):
                title = st.text_input("Investigation title", f"{cust}: {mine.rule.iloc[0].lower()}")
                prio = st.selectbox("Priority", ["High", "Medium", "Low"],
                                    index=0 if mine.severity.isin(["Critical", "High"]).any() else 1)
                if st.form_submit_button("Open an investigation with the ticked alerts", type="primary"):
                    if picked:
                        case_id = tm.open_case(cid, picked, title, prio, user)
                        st.session_state["open_case"] = case_id
                        st.success(f"Investigation #{case_id} opened. Continue on the Investigations page.")
                        st.page_link("pages/6_Investigations.py", label="Go to the investigation", icon="🗂️")
                    else:
                        st.error("Tick at least one alert.")
            with a2.form("close_alerts"):
                note = st.text_area("Explanation (required)",
                                    placeholder="e.g. Customer provided sale contract for the property; funds match.")
                if st.form_submit_button("Close ticked alerts as explained"):
                    if not note.strip() or not picked:
                        st.error("Tick alerts and write the explanation.")
                    else:
                        for aid in picked:
                            tm.close_alert(aid, note.strip(), user)
                        st.rerun()
