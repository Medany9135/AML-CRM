"""Ownership structure and ultimate beneficial owner (UBO) identification for company customers."""

import pandas as pd
import streamlit as st

import db
import sanctions
from risk import COUNTRIES
from ubo import OFFSHORE, ROLES, UBO_THRESHOLD, analyse, risk_factors
from ui import NEON, badge, md, setup, stat_card

setup("Ownership & UBO")
st.title("Ownership & UBO")
st.caption("Map who owns and controls each company, and find the natural persons behind it.")

companies = db.customers_df().query("customer_type == 'Company'")
if companies.empty:
    st.info("No company customers yet. Add one on the Add Customer page.")
    st.stop()

options = {f"#{r.id} · {r.full_name}": int(r.id) for r in companies.itertuples()}
labels = list(options)
default = st.session_state.get("open_customer")
idx = next((i for i, l in enumerate(labels) if options[l] == default), 0)
cid = options[st.selectbox("Company", labels, index=idx)]
st.session_state["open_customer"] = cid
c = db.get_customer(cid)
owners = db.owners_for(cid)
if st.session_state.get("ubo_flash"):
    st.error(st.session_state.pop("ubo_flash"))
a = analyse(owners)
user = st.session_state["user"]

# --- Headline numbers -------------------------------------------------------
direct = [o for o in owners if o["parent_owner_id"] is None and o["role"] == "Shareholder"]
traced = f'{sum(o["pct"] for o in direct):g}%' if direct else "n/a"
k1, k2, k3, k4 = st.columns(4)
stat_card(k1, "UBOs identified", len(a["ubos"]), NEON["green"],
          "by senior management fallback" if a["fallback"] else f"{UBO_THRESHOLD:g}% threshold")
stat_card(k2, "Corporate layers", a["layers"], NEON["violet"], f"{len(a['corporates'])} companies in the chain")
stat_card(k3, "Ownership traced", traced, NEON["cyan"], f"{len(a['people'])} natural persons")
stat_card(k4, "Customer risk", c["risk_rating"], {"High": NEON["pink"], "Medium": NEON["amber"]}.get(
    c["risk_rating"], NEON["green"]), f"score {c['risk_score']}")


# --- Ownership tree ---------------------------------------------------------
def dot_graph() -> str:
    def q(text):
        return '"' + str(text).replace('"', "'") + '"'

    lines = [
        "digraph G {",
        'bgcolor="transparent"; rankdir=TB; nodesep=0.3; ranksep=0.5;',
        'node [shape=box, style="rounded,filled", fontsize=15, margin="0.1,0.05", width=0, height=0, '
        f'fontcolor="{NEON["text"]}", color="{NEON["cyan"]}", fillcolor="#FFFFFF", penwidth=1.4];',
        f'edge [color="{NEON["muted"]}", fontcolor="{NEON["text"]}", fontsize=13, arrowsize=0.7];',
        f'root [label={q(c["full_name"] + chr(10) + "(customer)")}, color="{NEON["cyan"]}", penwidth=2.5, '
        f'fontsize=17, fillcolor="#E8F1FB"];',
    ]
    ubo_names = {p["name"] for p in a["ubos"]}
    pep_names = {p["name"] for p in a["people"] if p["pep"]}
    person_ids = {}   # one node per natural person, even if they hold several roles

    def person_node(o):
        if o["name"] not in person_ids:
            nid = f"p{len(person_ids)}"
            person_ids[o["name"]] = nid
            is_ubo = o["name"] in ubo_names
            color = NEON["pink"] if o["name"] in pep_names else (NEON["green"] if is_ubo else NEON["muted"])
            tags = (" · UBO" if is_ubo else "") + (" · PEP" if o["name"] in pep_names else "")
            label = f"{o['name']}{tags}\n{o['nationality']}"
            lines.append(f'{nid} [label={q(label)}, shape=box, style="rounded,filled,bold", color="{color}", '
                         f'penwidth={3 if is_ubo else 1.4}, fillcolor="{"#E9F7EC" if is_ubo else "#FFFFFF"}"];')
        return person_ids[o["name"]]

    for o in owners:
        if o["owner_type"] == "Company":
            node = f"o{o['id']}"
            risky = any(o["id"] == r["id"] for r in a["risky_corporates"])
            color = NEON["pink"] if risky else NEON["violet"]
            label = f"{o['name']}\n{o['nationality']}"
            lines.append(f'{node} [label={q(label)}, color="{color}", fillcolor="#F1ECFA"];')
        else:
            node = person_node(o)
        parent = "root" if o["parent_owner_id"] is None else f"o{o['parent_owner_id']}"
        if o["role"] == "Shareholder":
            lines.append(f'{node} -> {parent} [label=" {o["pct"]:g}%", color="{NEON["cyan"]}", penwidth=1.6];')
        else:
            lines.append(f'{node} -> {parent} [label=" {o["role"].lower()}", style=dashed];')
    name_to_node = {"the customer": "root"}
    name_to_node.update({o["name"]: f"o{o['id']}" for o in owners if o["owner_type"] == "Company"})
    for i, (name, pct) in enumerate(a["gaps"]):
        lines.append(f'gap{i} [label="Unidentified\\n{pct:g}%", shape=note, color="{NEON["amber"]}", '
                     f'fontcolor="{NEON["amber"]}"];')
        lines.append(f'gap{i} -> {name_to_node.get(name, "root")} [label=" {pct:g}%", style=dotted, '
                     f'color="{NEON["amber"]}"];')
    lines.append("}")
    return "\n".join(lines)


left, right = st.columns([1.5, 1])
with left:
    st.subheader("Ownership tree")
    if owners:
        st.graphviz_chart(dot_graph(), width="stretch")
        st.caption("Arrows point from owner to the entity they own. Solid = shareholding, dashed = control role. "
                   "Green = UBO, pink = PEP or offshore / high risk entity, violet = company.")
    else:
        st.info("No owners recorded yet. Add the first shareholder below.")

with right:
    st.subheader("Beneficial owners")
    st.markdown(f"**Basis:** {md(a['basis'])}")
    if a["people"]:
        table = pd.DataFrame([{
            "UBO": "✔" if p["is_ubo"] else "", "Name": p["name"] + (" (PEP)" if p["pep"] else ""),
            "Effective %": p["effective_pct"], "Roles": p["roles"],
        } for p in a["people"]])
        st.dataframe(table, hide_index=True, width="stretch",
                     column_config={"Effective %": st.column_config.ProgressColumn(
                         "Effective %", min_value=0, max_value=100, format="%.1f%%")})
    st.subheader("Red flags")
    flags = risk_factors(a)
    if a["pep_involved"]:
        flags.append((30, "A PEP is among the owners, directors or managers"))
    if flags:
        for points, why in flags:
            st.warning(f"{why} (+{points} risk points)")
    else:
        st.success("No ownership red flags.")

st.divider()

# --- Edit the structure -----------------------------------------------------
add_col, remove_col = st.columns([2, 1])
with add_col:
    st.subheader("Add owner, director or manager")
    parents = {f"{c['full_name']} (the customer)": None}
    parents.update({f"{o['name']} (company)": o["id"] for o in owners if o["owner_type"] == "Company"})
    with st.form("add_owner", clear_on_submit=True):
        f1, f2 = st.columns(2)
        parent_label = f1.selectbox("Owns / works for", list(parents))
        role = f2.selectbox("Role", ROLES)
        name = f1.text_input("Name")
        owner_type = f2.radio("Type", ["Individual", "Company"], horizontal=True)
        country = f1.selectbox("Nationality / country of incorporation", sorted(set(COUNTRIES) | OFFSHORE),
                               index=sorted(set(COUNTRIES) | OFFSHORE).index("United Arab Emirates"))
        pct = f2.number_input("Shareholding % (shareholders only)", min_value=0.0, max_value=100.0, step=5.0)
        pep = f1.checkbox("Politically exposed person")
        go = st.form_submit_button("Add", type="primary")
    if go:
        parent_id = parents[parent_label]
        used = sum(o["pct"] for o in owners if o["parent_owner_id"] == parent_id and o["role"] == "Shareholder")
        if not name.strip():
            st.error("Name is required.")
        elif role == "Shareholder" and pct <= 0:
            st.error("A shareholder needs a shareholding above 0%.")
        elif role == "Shareholder" and used + pct > 100.001:
            st.error(f"That would take {parent_label.split(' (')[0]} to {used + pct:g}% owned. Only {100 - used:g}% is left.")
        elif role != "Shareholder" and owner_type == "Company":
            st.error("Directors and managers must be natural persons.")
        else:
            db.add_owner(cid, dict(parent_owner_id=parent_id, name=name.strip(), owner_type=owner_type,
                                   nationality=country, pct=pct if role == "Shareholder" else 0,
                                   role=role, pep=pep), user)
            if sanctions.screen(cid, st.session_state.get("screen_threshold", 85), user):
                st.session_state["ubo_flash"] = f"Screening raised an alert for {name.strip()}. See Sanctions Screening."
            st.rerun()

with remove_col:
    st.subheader("Remove")
    if owners:
        choices = {f"{o['name']} · {o['role']}" + (f" {o['pct']:g}%" if o["role"] == "Shareholder" else ""): o["id"]
                   for o in owners}
        pick = st.selectbox("Entry", list(choices))
        st.caption("Removing a company also removes everyone recorded under it.")
        if st.button("Remove entry"):
            db.delete_owner(cid, choices[pick], user)
            st.rerun()

with st.expander("📘 AML note: how UBO identification works in the UAE"):
    st.markdown(f"""
A **beneficial owner** is the natural person who ultimately owns or controls a company, even if their name
is not on the shareholder register. Criminals hide behind layers of companies, often in offshore
jurisdictions, so you must look through every corporate layer to the people at the top.

Under UAE Cabinet Decision No. 109 of 2023, the steps are:

1. **Ownership:** anyone who owns **{UBO_THRESHOLD:g}% or more**, directly or indirectly. Indirect stakes are
   multiplied along the chain: 60% of a company that owns 70% of the customer is 42%.
2. **Control by other means:** if nobody reaches {UBO_THRESHOLD:g}%, find whoever controls the company in another way
   (voting rights, the power to appoint directors).
3. **Senior management fallback:** if still nobody, record the senior manager as the UBO, and document why.

**Red flags to watch:** several layers of companies with no clear business reason, entities in offshore or high risk
jurisdictions, ownership percentages that don't add up to 100%, nominee shareholders, and PEPs among the owners.
Companies must also keep their own UBO register and update it within 15 working days of a change.

*Try it:* open **Blue Harbour Holdings Ltd** to see a layered offshore structure with a 40% gap, or
**Hope Bridge Charity Foundation** for the senior management fallback.
""")
