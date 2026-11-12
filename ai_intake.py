"""AI document intake, shown on the Add Customer page: upload KYC documents, let AI read them, review the
fields, then save to a new or existing customer. The reading itself is in doc_ai.py."""

import pandas as pd
import streamlit as st

import db
import doc_ai
import sanctions
from risk import COUNTRIES
from ubo import ROLES
from ui import badge, customer_form, md


def render():
    st.caption("Upload a passport, Emirates ID, trade licence or memorandum of association. AI reads the "
               "fields, you check and correct them, and nothing is saved until you press Save.")
    user = st.session_state["user"]

    if st.session_state.get("ai_flash"):
        cid_done, msg = st.session_state.pop("ai_flash")
        st.success(msg)
        st.session_state["open_customer"] = cid_done
        c1, c2 = st.columns(2)
        c1.page_link("pages/1_Customers.py", label="Open the customer profile", icon="👥")
        c2.page_link("pages/3_Ownership_UBO.py", label="Open Ownership & UBO", icon="🕸️")

    # --- Status of the AI service --------------------------------------------------------------------
    if doc_ai.api_ready():
        st.info(f"AI extraction is on ({doc_ai.MODEL}). Used today: {doc_ai.used_today()} of "
                f"{doc_ai.daily_limit()} extractions.", icon="🤖")
    else:
        st.warning("AI extraction is not switched on for this app yet (no API key). You can still try the "
                   "flow with the bundled fictional sample documents below, which use saved results.", icon="🔌")

    with st.expander("Fictional sample documents to try"):
        st.caption("Invented people and companies, marked SPECIMEN. Download them, then upload them below.")
        cols = st.columns(3)
        for col, (fname, label) in zip(cols, [
                ("sample_passport_sofia_marquez.pdf", "Passport: Sofia Marquez"),
                ("sample_trade_licence_falcon_bay.pdf", "Trade licence: Falcon Bay"),
                ("sample_moa_falcon_bay.pdf", "MOA: Falcon Bay")]):
            path = doc_ai.SAMPLES_DIR / fname
            if path.exists():
                col.download_button(label, path.read_bytes(), file_name=fname, mime="application/pdf",
                                    width="stretch")

    # --- 1. Where the data goes ------------------------------------------------------------------------
    st.subheader("1. Choose the customer")
    mode = st.segmented_control("Use the documents to", ["Create a new customer", "Update an existing customer"],
                                default="Create a new customer", key="ai_mode") or "Create a new customer"
    existing = None
    if mode == "Update an existing customer":
        df = db.customers_df()
        options = {f"#{r.id} · {r.full_name}": int(r.id) for r in df.itertuples()}
        labels = list(options)
        default = st.session_state.get("open_customer")
        idx = next((i for i, l in enumerate(labels) if options[l] == default), 0)
        existing = db.get_customer(options[st.selectbox("Customer", labels, index=idx)])

    # --- 2. Upload and extract -------------------------------------------------------------------------
    st.subheader("2. Upload documents")
    files = st.file_uploader("PDF, PNG or JPG, up to 5 MB and 10 pages each", type=["pdf", "png", "jpg", "jpeg"],
                             accept_multiple_files=True, key=f"ai_files_{st.session_state.get('ai_saved', 0)}")
    if st.button("Read documents with AI", type="primary", disabled=not files):
        results, errors = [], []
        with st.spinner("Reading documents..."):
            for f in files:
                try:
                    r = doc_ai.extract(f.name, f.getvalue(), user)
                    r["file_name"] = f.name
                    results.append(r)
                except doc_ai.ExtractionError as e:
                    errors.append(str(e))
        st.session_state["ai_results"] = results
        st.session_state["ai_errors"] = errors
        st.session_state["ai_run"] = st.session_state.get("ai_run", 0) + 1
        st.rerun()

    for e in st.session_state.get("ai_errors", []):
        st.error(e)
    results = st.session_state.get("ai_results", [])
    if not results:
        return

    # --- 3. What the AI found ---------------------------------------------------------------------------
    st.subheader("3. What the AI found")
    LABELS = {"full_name": "Name", "date_of_birth": "Date of birth / registration", "nationality":
              "Nationality / incorporation", "residence_country": "Residence / operations", "id_number":
              "Document no.", "id_expiry": "Expiry", "activity": "Occupation / activity",
              "activity_as_written": "As written on the document"}
    for r in results:
        flags = len(r["checks"]) + len(r["notes"])
        with st.expander(f"📄 {md(r['file_name'])} · {r['document_type']}" + (f" · {flags} point(s) to check" if flags else ""),
                         expanded=bool(r["checks"])):
            st.caption(r["source"])
            st.table(pd.DataFrame([(LABELS[k], r[k] or "—") for k in LABELS], columns=["Field", "Value"]))
            if r["owners"]:
                st.markdown("**People and companies named**")
                st.dataframe(pd.DataFrame(r["owners"]), hide_index=True, width="stretch")
            for c in r["checks"]:
                st.warning(md(c))
            for n in r["notes"]:
                st.caption(f"AI note: {md(n)}")

    merged, conflicts = doc_ai.merge(results)
    for c in conflicts:
        st.warning(f"Documents disagree. {md(c)}")

    # --- 4. Review and save -------------------------------------------------------------------------------
    st.subheader("4. Review and save")
    run = st.session_state.get("ai_run", 0)
    ctype = merged["customer_type"]
    if existing is not None and existing["customer_type"] != ctype:
        st.error(f"These documents describe {'a company' if ctype == 'Company' else 'an individual'}, but "
                 f"{existing['full_name']} is {'a company' if existing['customer_type'] == 'Company' else 'an individual'}. "
                 "Choose another customer or other documents.")
        return

    prefill = dict(existing or {})
    fields = [k for k in doc_ai.FIELDS if merged.get(k)]
    if existing is not None:
        changes = [(LABELS[k], existing.get(k) or "—", merged[k]) for k in fields
                   if str(existing.get(k) or "") != str(merged[k])]
        if changes:
            st.markdown("**Changes the documents suggest** (already filled into the form below)")
            st.table(pd.DataFrame(changes, columns=["Field", "Now", "From documents"]))
        else:
            st.caption("The documents match what is already on file.")
    prefill.update({k: merged[k] for k in fields})
    st.caption("Source of funds, expected volume, channel, PEP and cash intensity are not on these documents, "
               "so they need your input.")

    owner_rows = pd.DataFrame()
    if ctype == "Company" and merged["owners"]:
        st.markdown("**Shareholders and controllers to add** (untick anyone you don't want added)")
        have = {(o["name"].strip().lower(), o["role"]) for o in db.owners_for(existing["id"])} if existing else set()
        owner_rows = pd.DataFrame([dict(add=(o["name"].strip().lower(), o["role"]) not in have, **o)
                                   for o in merged["owners"]])
        owner_rows = st.data_editor(
            owner_rows, hide_index=True, width="stretch", key=f"ai_owners_{run}",
            column_config={
                "add": st.column_config.CheckboxColumn("Add"),
                "name": "Name",
                "owner_type": st.column_config.SelectboxColumn("Type", options=["Individual", "Company"], required=True),
                "nationality": st.column_config.SelectboxColumn("Nationality / country", options=COUNTRIES),
                "pct": st.column_config.NumberColumn("Shares %", min_value=0, max_value=100),
                "role": st.column_config.SelectboxColumn("Role", options=ROLES, required=True),
            })
        if have:
            st.caption("People already recorded on this company are unticked.")

    docs_found = sorted({doc_ai.CHECKLIST[(ctype, r["document_type"])] for r in results
                         if (ctype, r["document_type"]) in doc_ai.CHECKLIST})
    mark_docs = st.checkbox("Tick these documents as received on the KYC checklist: " + ", ".join(docs_found),
                            value=True) if docs_found else False

    new = customer_form(f"ai_form_{run}", existing=prefill, customer_type=ctype)
    if new:
        selected = owner_rows[owner_rows["add"]] if not owner_rows.empty else owner_rows
        problems = []
        if not selected.empty:
            if selected["name"].fillna("").str.strip().eq("").any():
                problems.append("Every owner needs a name.")
            if ((selected["role"] != "Shareholder") & (selected["owner_type"] == "Company")).any():
                problems.append("Only a person can be a director or senior manager.")
            existing_pct = sum(o["pct"] for o in db.owners_for(existing["id"])
                               if o["parent_owner_id"] is None and o["role"] == "Shareholder") if existing else 0
            added_pct = selected.loc[selected["role"] == "Shareholder", "pct"].fillna(0).sum()
            if existing_pct + added_pct > 100.001:
                problems.append(f"Direct shareholdings would total {existing_pct + added_pct:g}% (over 100%). "
                                "Untick or correct some owners.")
        for p in problems:
            st.error(p)
        if not problems:
            if existing is None:
                cid = db.add_customer(new, user)
            else:
                cid = existing["id"]
                db.update_customer(cid, new, user)
            for o in selected.to_dict("records"):
                db.add_owner(cid, dict(parent_owner_id=None, name=o["name"].strip(), owner_type=o["owner_type"],
                                       nationality=o["nationality"] or None,
                                       pct=float(o["pct"] or 0) if o["role"] == "Shareholder" else 0,
                                       role=o["role"], pep=0), user)
            if mark_docs:
                for d in docs_found:
                    db.set_document(cid, d, True, user)
            with db.connect() as conn:
                db.log(conn, "customer", cid, "AI document intake",
                       "Fields read by AI from " + ", ".join(f"{r['file_name']} ({r['document_type']})" for r in results)
                       + f"; reviewed and saved by {user}. Owners added: {len(selected)}.", user)
            hits = sanctions.screen(cid, st.session_state.get("screen_threshold", 85), user)
            saved = db.get_customer(cid)
            msg = (f"{'Created' if existing is None else 'Updated'} customer #{cid}: {md(saved['full_name'])}, rated "
                   f"{badge(saved['risk_rating'])} (score {saved['risk_score']}).")
            if hits:
                msg += f" Sanctions screening raised {hits} alert(s): review them before approving."
            st.session_state["ai_flash"] = (cid, msg)
            for k in ("ai_results", "ai_errors"):
                st.session_state.pop(k, None)
            st.session_state["ai_run"] = run + 1
            st.session_state["ai_saved"] = st.session_state.get("ai_saved", 0) + 1   # clears the uploader
            st.rerun()

    with st.expander("AML note: using AI on KYC documents"):
        st.markdown(
            "- AI speeds up data entry; it does not verify a document. Original or certified copies, "
            "and checks such as UAE PASS or ICP validation, are still needed.\n"
            "- A person reviews every field before it is saved, and the audit log records which documents "
            "were read and who saved the result.\n"
            "- Expired documents, shareholdings that don't add to 100% and corporate shareholders are flagged "
            "by fixed rules, not by the AI.\n"
            "- Saving re-runs the risk score and sanctions screening, including any owners added.\n"
            "- In a live system, check that sending customer documents to an AI provider is allowed under the "
            "UAE PDPL, your outsourcing policy and the provider's data terms.")
