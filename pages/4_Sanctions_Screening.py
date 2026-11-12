"""Sanctions list management, automated screening and alert review."""

import pandas as pd
import streamlit as st

import db
import sanctions
from ui import NEON, md, setup, stat_card

setup("Sanctions screening")
st.title("Sanctions screening")
st.caption("Screen every customer, shareholder, director and manager against OFAC, UN, EU and UAE lists.")
user = st.session_state["user"]

status = sanctions.list_status()
alerts = sanctions.alerts_df()
open_alerts = alerts[alerts.status == "Open"]
names = int(status["names"].fillna(0).sum())

k1, k2, k3, k4 = st.columns(4)
stat_card(k1, "Open alerts", len(open_alerts), NEON["pink"], "waiting for a decision")
stat_card(k2, "True matches", int((alerts.status == "True match").sum()), NEON["amber"], "frozen and reported")
stat_card(k3, "Names on file", f"{names:,}", NEON["cyan"],
          f"{int(status['entries'].fillna(0).sum()):,} listed parties")
stat_card(k4, "Lists loaded", int((status["status"] == "ok").sum()), NEON["violet"], f"of {len(sanctions.ALL_LISTS)}")

with st.expander("📘 AML note: sanctions screening in the UAE"):
    st.markdown("""
**Targeted financial sanctions (TFS)** require you to freeze the funds of listed persons **without delay**
(the UAE expects within 24 hours) and **without prior notice**, and never make funds available to them.
In the UAE this is governed by Cabinet Decision No. 74 of 2020, with lists from the UN Security Council and the
UAE Local Terrorist List. OFAC and EU lists are not UAE law, but banks screen them too because of correspondent
banking and the US dollar.

**When to screen:** at onboarding, whenever a list changes, and whenever customer or ownership data changes.
Screen the customer, its UBOs, shareholders, directors and authorised signatories.

**Working an alert:** compare secondary identifiers: date of birth, nationality, ID numbers, address.
A common name alone is not a match.

* **False positive:** identifiers clearly differ. Document why and close.
* **Potential match:** you can't rule it out. Suspend the transaction and file a **PNMR** (Partial Name Match
  Report) through goAML to the Executive Office (EOCN).
* **True match:** freeze, don't process anything, and file a **FFR** (Funds Freeze Report) through goAML.

*Try it:* the fictional training list is loaded and screened for you. **Reza Tehrani** is a spelling variant,
**Golden Sands Jewellery** is a similar but different company, and **Dmitri Orlov** (owner of Blue Harbour
Holdings) is a hit on a beneficial owner. Add a new customer called **Ahmed Khan** to see how a common name
creates a false positive, then use the date of birth to clear it.
""")

tab_alerts, tab_lists, tab_run = st.tabs(["Alert review", "Sanctions lists", "Run screening"])

# --- Lists ------------------------------------------------------------------
with tab_lists:
    show = status.rename(columns={"list_name": "List", "fetched_at": "Last updated", "entries": "Entries",
                                  "names": "Names incl. aliases", "status": "Status", "source": "Source"})
    st.dataframe(show, hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Download the latest public lists**")
        st.caption("OFAC, UN and EU publish their lists as free files. Downloading takes a minute or two.")
        if st.button("Update OFAC, UN and EU lists", type="primary"):
            with st.status("Downloading lists...", expanded=True) as box:
                for name in sanctions.AUTO_LISTS:
                    st.write(sanctions.update_list(name))
                box.update(label="Lists updated", state="complete")
            st.rerun()
        if st.button("Reload the training list"):
            sanctions.load_training_list()
            st.rerun()
    with c2:
        st.markdown("**UAE Local Terrorist List**")
        st.caption("Download the Excel file from the UAE Executive Office for Control and Non-Proliferation "
                   "(uaeiec.gov.ae, Local Terrorist List), then upload it here.")
        up = st.file_uploader("Excel or CSV file", type=["xlsx", "xls", "csv"])
        if up is not None:
            try:
                raw = pd.read_csv(up, dtype=str) if up.name.endswith(".csv") else pd.read_excel(up, dtype=str)
            except Exception as exc:
                st.error(f"Could not read the file: {exc}")
                raw = None
            if raw is not None:
                raw = raw.dropna(how="all")
                cols = list(raw.columns)
                guess = next((c for c in cols if "name" in str(c).lower() and "arab" not in str(c).lower()), cols[0])
                name_col = st.selectbox("Column with the name (English)", cols, index=cols.index(guess))
                none = "(none)"
                type_col = st.selectbox("Column saying person or entity", [none] + cols)
                nat_col = st.selectbox("Nationality column", [none] + cols)
                dob_col = st.selectbox("Date of birth column", [none] + cols)
                st.dataframe(raw.head(5), hide_index=True)
                if st.button("Load UAE list"):
                    rows = sanctions.parse_uae(raw, name_col, *(None if c == none else c
                                                               for c in (type_col, nat_col, dob_col)))
                    sanctions._store("UAE Local Terrorist List", rows, up.name)
                    st.success(f"{len(rows)} names loaded.")
                    st.rerun()

# --- Run --------------------------------------------------------------------
with tab_run:
    st.markdown("Screening compares every customer and every owner, director and manager against all loaded "
                "lists. New customers and owners are also screened automatically when you add them.")
    threshold = st.slider("Match threshold (similarity score)", 70, 100, 85,
                          help="Lower finds more spelling variants but creates more false positives.")
    st.session_state["screen_threshold"] = threshold
    if st.button("Screen everyone now", type="primary", disabled=not sanctions.lists_loaded()):
        with st.spinner("Screening..."):
            new = sanctions.screen(threshold=threshold, user=user)
        st.success(f"Done. {new} new alerts.")
    st.caption("Alerts are never duplicated: a name already reviewed against the same list entry is not raised again.")

# --- Alerts -----------------------------------------------------------------
with tab_alerts:
    if alerts.empty:
        st.info("No alerts yet. Run screening from the 'Run screening' tab.")
        st.stop()
    f1, f2 = st.columns([1, 2])
    show_status = f1.multiselect("Status", sanctions.DECISIONS, default=["Open"])
    view = alerts[alerts.status.isin(show_status)] if show_status else alerts
    st.dataframe(
        view[["id", "customer", "screened_name", "matched_name", "list_name", "score", "status"]],
        hide_index=True, width="stretch",
        column_config={"id": "Alert", "customer": "Customer", "party": "Who", "screened_name": "Our name",
                       "matched_name": "Listed name", "list_name": "List", "details": "Other matches",
                       "status": "Status",
                       "score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d")})
    if view.empty:
        st.stop()
    pick = st.selectbox("Review alert", [f"#{r.id} · {r.screened_name} vs {r.matched_name} ({r.list_name})"
                                         for r in view.itertuples()])
    a = view[view.id == int(pick.split(" ")[0][1:])].iloc[0]
    left, right = st.columns(2)
    with left:
        st.subheader("Our party")
        c = db.get_customer(int(a.customer_id))
        if a.party == "Customer":
            nat, dob = c["nationality"], c["date_of_birth"] or "-"
        else:
            o = next((o for o in db.owners_for(int(a.customer_id)) if o["name"] == a.screened_name), {})
            nat, dob = o.get("nationality") or "-", "not recorded"
        st.markdown(f"**{md(a.screened_name)}** ({a.party})  \nCustomer: {md(c['full_name'])} (#{c['id']})  \n"
                    f"Nationality / country: {md(nat)}  \nDate of birth: {md(dob)}")
        st.markdown(f"**Similarity score:** {a.score:g}  \n**Other identifiers:** {md(a.details) or 'none matched'}")
    with right:
        st.subheader("Listed party")
        d = sanctions.entry_details(a.list_name, a.entry_id)
        if not d.empty:
            first = d.iloc[0]
            st.markdown(f"**{md(a.matched_name)}** ({md(first.entry_type)})  \nList: {a.list_name}, entry {a.entry_id}  \n"
                        f"Programme: {md(first.program) or '-'}  \nNationality: {md(first.nationality) or '-'}  \n"
                        f"Date of birth: {md(first.dob) or '-'}")
            if first.remarks:
                st.caption(md(first.remarks))
            if len(d) > 1:
                st.caption("Also known as: " + "; ".join(d.name.tolist()[:8]))
    with st.form(f"decide_{a.id}"):
        decision = st.radio("Decision", sanctions.DECISIONS[1:], horizontal=True,
                            index=sanctions.DECISIONS[1:].index(a.status) if a.status in sanctions.DECISIONS[1:] else 0)
        note = st.text_area("Rationale (required)", a.decision_note or "",
                            placeholder="e.g. Different date of birth and nationality; listed person is born 1965 in Pakistan.")
        go = st.form_submit_button("Record decision", type="primary")
    if go:
        if not note.strip():
            st.error("Write down why. Every screening decision must be documented.")
        else:
            sanctions.decide(int(a.id), decision, note.strip(), user)
            st.success(f"Recorded: {decision}")
            st.rerun()
    if a.status == "True match":
        st.error("Confirmed match: freeze the funds without delay, do not carry out any transaction, "
                 "and file a Funds Freeze Report (FFR) through goAML.")
    elif a.status == "Potential match (escalate)":
        st.warning("Potential match: suspend any transaction and file a Partial Name Match Report (PNMR) "
                   "through goAML while you clarify.")
