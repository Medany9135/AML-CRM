"""Entry point of Sanad. Run with:  streamlit run Dashboard.py

It only sets the order, names and sections of the pages in the sidebar. Each page lives in pages/.
"""

import streamlit as st

nav = st.navigation({
    "": [
        st.Page("pages/0_Home.py", title="Dashboard", icon="🏠", default=True),
        st.Page("pages/1_Customers.py", title="Customers", icon="👥"),
        st.Page("pages/2_Add_Customer.py", title="Add Customer", icon="➕"),
        st.Page("pages/13_AI_Document_Intake.py", title="AI Document Intake", icon="🤖"),
        st.Page("pages/3_Ownership_UBO.py", title="Ownership & UBO", icon="🕸️"),
        st.Page("pages/4_Sanctions_Screening.py", title="Sanctions Screening", icon="🛰️"),
        st.Page("pages/5_Transaction_Monitoring.py", title="Transaction Monitoring", icon="💸"),
        st.Page("pages/6_Investigations.py", title="Investigations", icon="🗂️"),
    ],
    "Governance": [
        st.Page("pages/11_Governance_Dashboard.py", title="Governance Dashboard", icon="🛡️"),
        st.Page("pages/12_EWRA.py", title="Risk Assessment (EWRA)", icon="🧭"),
        st.Page("pages/8_Policy_Management.py", title="Policy Management", icon="📘"),
        st.Page("pages/9_Effectiveness_Testing.py", title="Effectiveness Testing", icon="🧪"),
        st.Page("pages/10_Reports.py", title="Reports", icon="📄"),
        st.Page("pages/7_Audit_Log.py", title="Audit Log", icon="📜"),
    ],
}, expanded=True)   # show every page; by default Streamlit folds long menus behind "View more"
nav.run()
