"""Policy management: the policy register, approval workflow, linked controls and staff attestation."""

import streamlit as st

import governance as gov
from ui import md, setup, stat_card

setup("Policy management")
st.title("Policy management")
st.caption("Keep the AML/CFT and sanctions policies current, approved, linked to the controls that enforce them, "
           "and acknowledged by staff.")
user = st.session_state["user"]

df = gov.policies_df()
current = df[df.status.isin(["Current", "Due for review", "Overdue"])]
att = current.staff_attested.sum() / max(current.staff_total.sum(), 1)
k = st.columns(5)
stat_card(k[0], "Policies", len(df), sub="in the register")
stat_card(k[1], "Current", int((df.status == "Current").sum()), sub="approved and in date")
stat_card(k[2], "Due for review", int((df.status == "Due for review").sum()), sub="within 30 days")
stat_card(k[3], "Overdue", int((df.status == "Overdue").sum()), sub="past review date")
stat_card(k[4], "Staff attestation", f"{att:.0%}", sub="across approved policies")

STATUS_ICON = {"Current": "🟢 Current", "Due for review": "🟠 Due for review", "Overdue": "🔴 Overdue",
               "Draft": "🔵 Draft"}

top = st.columns([3, 1])
top[0].subheader("Policy register")
with top[1].popover("➕ New policy", use_container_width=True):
    with st.form("new_policy"):
        name = st.text_input("Policy name")
        owner = st.text_input("Owner", "MLRO")
        approver = st.selectbox("Approved by", gov.APPROVERS)
        months = st.number_input("Review every (months)", 1, 36, 12)
        staff = st.number_input("Staff who must attest", 0, 1000, 10)
        basis = st.text_area("Regulatory basis (one per line)", "\n".join(gov.UAE_BASIS[:2]))
        if st.form_submit_button("Create draft", type="primary"):
            if name.strip():
                st.session_state["policy_id"] = gov.add_policy(name.strip(), owner, approver, months, basis, staff, user)
                st.rerun()
            else:
                st.error("Name is required.")

view = df.assign(Status=df.status.map(STATUS_ICON),
                 Attested=[f"{p}%" if p is not None else "-" for p in df.attested_pct],
                 Stage=[gov.WORKFLOW[s] for s in df.stage])
st.dataframe(view[["name", "version", "owner", "approver", "approved_on", "next_review", "Attested", "Stage", "Status"]],
             hide_index=True, width="stretch",
             column_config={"name": "Policy", "version": "Version", "owner": "Owner", "approver": "Approved by",
                            "approved_on": "Last approved", "next_review": "Next review"})

if df.empty:
    st.stop()
labels = {f"{r.name} · {r.version}": int(r.id) for r in df.itertuples()}
default = st.session_state.get("policy_id")
keys = list(labels)
idx = next((i for i, key in enumerate(keys) if labels[key] == default), 0)
pid = labels[st.selectbox("Open policy", keys, index=idx)]
p = gov.get_policy(pid)
status = gov.policy_status(p["stage"], p["next_review"])

st.divider()
left, right = st.columns(2)
with left:
    st.subheader(f"{md(p['name'])} · {md(p['version'])}")
    st.markdown(f"**Status:** {STATUS_ICON[status]} · **Owner:** {md(p['owner'])} · **Approved by:** {md(p['approver'])}")
    st.markdown("**Approval workflow**")
    steps = []
    for i, step in enumerate(gov.WORKFLOW):
        mark = "✅" if i < p["stage"] else ("➡️" if i == p["stage"] else "⬜")
        steps.append(f"{mark} {i + 1}. {step}")
    st.markdown("  \n".join(steps))
    if p["stage"] < len(gov.WORKFLOW) - 1:
        nxt = gov.WORKFLOW[p["stage"] + 1]
        with st.form(f"advance_{pid}"):
            note = st.text_input(f"Note for the move to '{nxt}' (who approved, meeting reference)")
            if st.form_submit_button(f"Move to: {nxt}", type="primary"):
                if note.strip():
                    gov.advance_policy(pid, note.strip(), user)
                    st.rerun()
                else:
                    st.error("Write a note: approvals need evidence.")
    else:
        st.success("Approved and published to staff.")

    st.markdown("**Regulatory basis**")
    st.markdown("\n".join(f"- {line}" for line in (p["basis"] or "").splitlines() if line.strip()) or "-")

    st.markdown("**Staff acknowledgement**")
    total = p["staff_total"] or 0
    st.progress(p["staff_attested"] / total if total else 0.0, text=f"{p['staff_attested']} of {total} staff")
    c1, c2 = st.columns(2)
    n = c1.number_input("Staff who have attested", 0, max(total, 0), p["staff_attested"], key=f"att_{pid}")
    if c2.button("Save attestations", key=f"att_btn_{pid}"):
        gov.record_attestations(pid, int(n), user)
        st.rerun()

with right:
    st.subheader("Controls set in Sanad")
    st.caption("Each policy rule next to the setting that enforces it. 'Differs' means the policy and the app "
               "disagree: change one of them, with approval.")
    ctrl = gov.policy_controls()
    for r in ctrl:
        r["Status"] = "✅ Matches" if r["Status"] == "Matches" else "⚠️ Differs"
    st.dataframe(ctrl, hide_index=True, width="stretch")
    st.markdown("**Version history**")
    st.dataframe(gov.versions_df(pid), hide_index=True, width="stretch",
                 column_config={"version": "Version", "on_date": "Date", "note": "Change", "by_user": "By"})
    with st.form(f"version_{pid}"):
        note = st.text_input("What changes in the new version?")
        if st.form_submit_button("Start a new version"):
            if note.strip():
                gov.new_version(pid, note.strip(), user)
                st.rerun()
            else:
                st.error("Describe the change.")

with st.expander("📘 AML note: why policy management matters"):
    st.markdown("""
UAE law requires written AML/CFT and sanctions **policies, controls and procedures** that are approved by senior
management (for most firms, the Board), applied across the business, and kept up to date when the law or the
firm's risks change (Federal Decree-Law No. 20 of 2018 and Cabinet Decision No. 10 of 2019).

An inspector will typically ask for: the **current version**, **who approved it and when**, the **review cycle**,
evidence that **staff read it**, and whether the systems actually apply what the policy says. That last point is why
this page compares each policy rule with the matching Sanad setting.
""")
