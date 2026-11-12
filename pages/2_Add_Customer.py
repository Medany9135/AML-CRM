"""Onboard a new customer."""

import json

import streamlit as st

import ai_intake
import db
import sanctions
from ui import badge, customer_form, md, setup

setup("Add customer")
st.title("Onboard a customer")
how = st.segmented_control("How do you want to add the customer?", ["Enter details by hand", "Read documents with AI"],
                           default="Enter details by hand", key="add_how") or "Enter details by hand"
if how == "Read documents with AI":
    ai_intake.render()
    st.stop()

st.caption("Fill in the KYC details. The risk rating and document checklist are generated automatically.")
kind = st.segmented_control("Customer type", ["Individual", "Company"], default="Individual",
                            key="new_customer_type")
kind = kind or "Individual"
st.subheader("New individual customer" if kind == "Individual" else "New company customer")
new = customer_form(f"add_{kind.lower()}", customer_type=kind)
if new:
    cid = db.add_customer(new, st.session_state["user"])
    hits = sanctions.screen(cid, st.session_state.get("screen_threshold", 85), st.session_state["user"])
    if hits:
        st.error(f"Sanctions screening raised {hits} alert(s) for this customer. Review them on the "
                 "Sanctions Screening page before approving.")
    saved = db.get_customer(cid)   # the stored rating also includes ownership and screening factors
    st.success(f"Created customer #{cid}: {md(saved['full_name'])} rated {badge(saved['risk_rating'])} "
               f"(score {saved['risk_score']}).")
    for r in json.loads(saved["risk_reasons"]):
        st.markdown(f"- {md(r)}")
    st.session_state["open_customer"] = cid
    st.page_link("pages/1_Customers.py", label="Open the customer profile", icon="👥")
