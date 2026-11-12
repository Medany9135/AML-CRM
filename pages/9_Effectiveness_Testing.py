"""Effectiveness testing: compliance management's periodic tests of AML and sanctions controls."""

from datetime import date

import streamlit as st

import governance as gov
from ui import md, setup, stat_card

setup("Effectiveness testing")
st.title("Effectiveness testing")
st.caption("Compliance management's periodic tests of whether each AML and sanctions control actually works, "
           "with findings tracked to closure.")
user = st.session_state["user"]

tests = gov.tests_df()
findings = gov.findings_df()
year = date.today().year
this_year = tests[tests.tested_on.str.startswith(str(year))]
open_f = findings[findings.status != "Closed"]
eff = int((this_year.result == "Effective").sum())
k = st.columns(5)
stat_card(k[0], f"Tests in {year}", len(this_year), sub=f"{this_year.area.nunique()} control areas")
stat_card(k[1], "Effective", f"{eff} of {len(this_year)}",
          sub=f"{eff / max(len(this_year), 1):.0%} of tests this year")
stat_card(k[2], "Not effective", int((this_year.result != "Effective").sum()), sub="partially or ineffective")
stat_card(k[3], "Open findings", len(open_f), sub=f"{int((open_f.severity == 'High').sum())} high severity")
stat_card(k[4], "Overdue actions", int((findings.status == "Overdue").sum()), sub="past due date")

RESULT_ICON = {"Effective": "🟢 Effective", "Partially effective": "🟠 Partially effective",
               "Ineffective": "🔴 Ineffective"}

tab_tests, tab_findings, tab_new = st.tabs(["Tests", "Findings and remediation", "Record a test"])

with tab_tests:
    left, right = st.columns([1.6, 1])
    with left:
        st.subheader("Test log")
        view = tests.assign(Result=tests.result.map(RESULT_ICON),
                            Passed=[f"{p} of {s}" for p, s in zip(tests["passed"], tests["sample"])])
        st.dataframe(view[["tested_on", "area", "what", "method", "frequency", "tester", "Passed", "Result"]],
                     hide_index=True, width="stretch", height=330,
                     column_config={"tested_on": "Tested", "area": "Control area", "what": "What is tested",
                                    "method": "Method", "frequency": "Frequency", "tester": "Tester"})
    with right:
        st.subheader(f"Results by quarter, {year}")
        grid = gov.quarter_grid(tests, year)
        icon = {"E": "🟢", "P": "🟠", "I": "🔴", "-": "·"}
        st.dataframe(grid.apply(lambda col: col.map(icon)), width="stretch", height=330)
        st.caption("🟢 effective · 🟠 partially effective · 🔴 ineffective · not tested. Latest test in each quarter.")

    if not tests.empty:
        labels = {f"{r.tested_on} · {r.area} · {r.result}": int(r.id) for r in tests.itertuples()}
        tid = labels[st.selectbox("Open a test", list(labels))]
        t = tests[tests.id == tid].iloc[0]
        st.markdown(f"#### {md(t.area)}: {md(t.what)}")
        st.markdown(f"{RESULT_ICON[t.result]} · tested {md(t.tested_on)} by {md(t.tester)} · {md(t.frequency)}")
        rate = t["passed"] / t["sample"] if t["sample"] else 1
        st.progress(rate, text=f"{t['passed']} of {t['sample']} passed ({rate:.0%})")
        c1, c2 = st.columns(2)
        c1.markdown(f"**Method:** {md(t.method)}  \n**What failed:** {md(t.notes) or 'Nothing'}")
        c2.markdown(f"**Evidence kept:** {md(t.evidence) or '-'}")
        linked = findings[findings.test_id == tid]
        if not linked.empty:
            st.markdown("**Findings from this test:** " + "; ".join(f"{r.finding} ({r.status})"
                                                                    for r in linked.itertuples()))

with tab_findings:
    STATUS_ICON = {"Open": "🔵 Open", "Overdue": "🔴 Overdue", "Closed": "🟢 Closed"}
    view = findings.assign(Status=findings.status.map(STATUS_ICON))
    st.dataframe(view[["id", "finding", "area", "severity", "action", "owner", "due", "Status", "closure_note"]],
                 hide_index=True, width="stretch",
                 column_config={"id": "#", "finding": "Finding", "area": "From test", "severity": "Severity",
                                "action": "Action", "owner": "Owner", "due": "Due", "closure_note": "Closure note"})
    c1, c2 = st.columns(2)
    with c1.form("new_finding"):
        st.markdown("**Raise a finding**")
        if tests.empty:
            st.caption("Record a test first.")
        opts = {f"#{r.id} {r.tested_on} · {r.area}": int(r.id) for r in tests.itertuples()}
        test_pick = st.selectbox("From test", list(opts) or ["-"])
        finding = st.text_input("Finding")
        sev = st.selectbox("Severity", gov.SEVERITIES)
        action = st.text_input("Remediation action")
        owner = st.text_input("Owner")
        due = st.date_input("Due date", format="DD/MM/YYYY")
        if st.form_submit_button("Raise finding", type="primary"):
            if opts and finding.strip() and action.strip() and owner.strip():
                gov.add_finding(opts[test_pick], finding.strip(), sev, action.strip(), owner.strip(),
                                due.isoformat(), user)
                st.rerun()
            else:
                st.error("Fill in the finding, action and owner.")
    with c2.form("close_finding"):
        st.markdown("**Close a finding**")
        open_opts = {f"#{r.id} {r.finding}": int(r.id) for r in open_f.itertuples()}
        pick = st.selectbox("Finding", list(open_opts) or ["No open findings"])
        note = st.text_area("How it was fixed and how you verified it")
        if st.form_submit_button("Close finding"):
            if open_opts and note.strip():
                gov.close_finding(open_opts[pick], note.strip(), user)
                st.rerun()
            else:
                st.error("Pick a finding and describe the fix.")

with tab_new:
    with st.form("new_test"):
        c1, c2 = st.columns(2)
        area = c1.selectbox("Control area", gov.AREAS)
        freq = c2.selectbox("Frequency", gov.FREQUENCIES, index=1)
        what = c1.text_input("What is tested", placeholder="e.g. Known list names are detected")
        method = c2.text_input("Method", placeholder="e.g. 20 test names: exact, aliases, spelling variants")
        tested_on = c1.date_input("Test date", format="DD/MM/YYYY")
        tester = c2.text_input("Tester", user)
        sample = c1.number_input("Items tested (sample)", 1, 10_000, 20)
        passed = c2.number_input("Items that passed", 0, 10_000, 20)
        notes = st.text_area("What failed, if anything")
        evidence = st.text_input("Evidence kept", placeholder="e.g. Sample list, screening output, sign-off")
        st.caption("Result is set automatically: 95% or more passed = Effective, 80-94% = Partially effective, "
                   "below 80% = Ineffective.")
        if st.form_submit_button("Record test", type="primary"):
            if not what.strip() or passed > sample:
                st.error("Describe what is tested, and passed cannot exceed the sample.")
            else:
                gov.add_test(area, what.strip(), method.strip(), freq, tested_on.isoformat(), tester, int(sample),
                             int(passed), notes.strip(), evidence.strip(), user)
                st.success(f"Recorded: {gov.result_for(int(sample), int(passed))}. Raise findings for anything "
                           "that failed on the Findings tab.")

with st.expander("📘 AML note: testing control effectiveness"):
    st.markdown("""
Having a control is not enough: a firm must be able to show it **works**. Compliance management tests each control
on a **risk-based schedule** (high-risk areas more often), records the **method, sample, result and evidence**, and
**fixes what fails** with an owner and a deadline. An **independent audit** then reviews the whole AML/CFT programme.

Good tests are concrete: run known list names through screening, plant scenarios to see if monitoring rules fire,
re-check a sample of KYC files, measure how long alerts stay open. Regulators look for these records and for
findings that were actually closed.
""")
