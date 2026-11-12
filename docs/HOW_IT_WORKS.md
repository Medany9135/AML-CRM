# How the AML CRM works

This guide explains the logic behind every feature and points to the exact file and function that
implements it. Read it next to the code. All data in the app is fictional.

## The big picture

```
                 ┌────────────────────────── Streamlit pages (pages/*.py, Dashboard.py) ─────────────────────────┐
 you click  ───▶ │ Customers · Add Customer · Ownership & UBO · Sanctions · Transaction Monitoring · Investigations · Audit │
                 └───────────────┬───────────────────────────────┬───────────────────────────────┬───────────────┘
                                 │                               │                               │
                          risk.py (scoring)              ubo.py (ownership)          sanctions.py / tm.py (detection)
                                 └───────────────┬───────────────┴───────────────────────────────┘
                                                 ▼
                                db.py  ───▶  aml_crm.db (one SQLite file)
```

* **Pages** only show things and collect input. They never contain AML rules.
* **Logic modules** (`risk.py`, `ubo.py`, `sanctions.py`, `tm.py`) hold the rules. Change a rule there and every
  page picks it up.
* **`db.py`** is the only place that talks to the database. Every change goes through it, and every change writes
  an audit log entry.

A key design idea: the customer's **risk rating is recalculated** whenever anything that affects it changes
(KYC details, owners, a confirmed sanctions match, an STR). That happens in `db.update_customer()`, which calls
`risk.score_customer()` with everything it knows about the customer.

---

## 1. Customer risk rating (KYC)

**Where:** `risk.py` → `score_customer()`, called from `db._apply_risk()`

**Logic:** a points system. Each risk factor adds points and a plain-English reason, so the rating is always
explainable (you see the reasons on the customer's *Risk assessment* tab).

| Factor | Points | Why it matters |
|---|---|---|
| Nationality or residence in a FATF **black list** country | +40, forces High | Countries under a FATF "call for action" |
| Nationality or residence in a FATF **grey list** country | +20 | Countries under increased monitoring |
| **PEP** (politically exposed person) | +30, forces High | Bribery and corruption risk; EDD is mandatory |
| **High risk activity** (gold dealers, real estate, money exchange, virtual assets, general trading, charities, used cars) | +25 | Sectors the UAE National Risk Assessment flags |
| Medium risk activity | +10 | |
| Cash intensive | +15 | Cash is hard to trace |
| Onboarded **non face to face** | +10 | Higher impersonation risk |
| Source of funds **unclear** | +15 | Can't show where money comes from |
| Expected monthly volume ≥ AED 1m / ≥ 250k | +15 / +5 | Bigger exposure |
| Company (legal entity) | +5 | Ownership must be verified |
| Ownership red flags (see section 2) | +10 to +15 each | Hidden owners |
| Confirmed **sanctions** match (section 3) | +100, forces High | |
| **STR filed** (section 4) | +40, forces High | |

**Bands:** 0–24 **Low**, 25–49 **Medium**, 50+ **High**. Some factors "force High" whatever the score, because the
law requires enhanced due diligence for them regardless of anything else.

**Onboarding forms** (`ui.customer_form()`, page `pages/2_Add_Customer.py`): the analyst first picks
*Individual* or *Company* and gets a different form for each. The company form asks for company full name,
incorporation country, registration / trade licence no., licence registration and expiry dates (calendar
pickers) and the trade licence activity. Activities come from `uae_activities.py`, a sample of UAE licence
activities each tagged High, Medium or Low risk, and that tag feeds the activity points above. Both forms
share a *Risk profile* section (source of funds, expected volume, channel, PEP, cash intensive) because
those fields drive the rating and transaction monitoring.

**Periodic review** (`next_review_date()`): High every 1 year, Medium 2 years, Low 3 years. An approval resets the
clock (`db.set_kyc_status()`); a change of rating moves the review date (`db.update_customer()`).

**Document checklist** (`required_documents()`): individuals need ID, proof of address and source of funds
evidence; companies need trade licence, MOA/AOA, shareholder register, board resolution, UBO declaration and
signatory IDs. High risk adds an EDD form and senior management approval.
On the customer's *Documents* tab, a ring chart shows the **completion rate**: every required document
carries the same weight (100% divided by the number of documents), so the rate is simply
received ÷ required. Ticking or unticking a box updates it straight away.

**Approval guard rails** (`pages/1_Customers.py`, KYC decision tab): you can't approve while documents are
missing, while sanctions alerts are open, or if there's a confirmed sanctions match. Every decision needs a
written rationale that goes into the audit trail.

---

## 2. Ownership and UBO identification

**Where:** `ubo.py` → `analyse()` and `risk_factors()`; data in the `owners` table (`db.add_owner()`)

**Data model:** ownership is a **tree**. Each owner row either owns the customer directly (`parent_owner_id` is
empty) or owns a company one layer up. Directors and senior managers hang off the entity they work for.

**Logic in `analyse()`:**

1. **Walk the tree** from the customer upwards (`walk()`), carrying a multiplier.
2. **Effective ownership** is the product of the percentages along the chain. Example: Dmitri owns 60% of Coral,
   Coral owns 100% of Northwind, Northwind owns 70% of Blue Harbour → 0.6 × 1.0 × 0.7 = **42%**.
3. A person reached through several paths has their percentages **added up**.
4. **UBO rule** (UAE Cabinet Decision 109 of 2023):
   * anyone with **25% or more** effective ownership is a UBO;
   * if nobody reaches 25%, the **senior manager** is recorded as UBO (then a director as a last resort), and the
     app says this is the fallback.
5. **Gaps:** at each company, shareholdings should add up to 100%. Anything missing is "Unidentified" and shown
   on the tree.

**Red flags** (`risk_factors()`), which feed the risk score:

| Red flag | Points |
|---|---|
| No owners recorded yet | +10 |
| 2 or more layers of companies | +15 |
| A company in the chain is offshore or in a FATF listed country | +15 |
| Nobody reaches 25% (fallback used) | +10 |
| Ownership doesn't add up to 100% somewhere | +10 |
| A PEP among owners, directors or managers | +30, forces High (in `risk.py`) |

**The tree picture** (`pages/3_Ownership_UBO.py` → `dot_graph()`) is drawn with Graphviz: one box per company,
one box per person, solid arrows for shareholdings with the percentage, dashed arrows for roles.

---

## 3. Sanctions screening

**Where:** `sanctions.py`; page `pages/4_Sanctions_Screening.py`

### Getting the lists (`update_list()`)

| List | Source | Parser |
|---|---|---|
| OFAC SDN | US Treasury CSV files `SDN.CSV` + `ALT.CSV` (aliases) | `parse_ofac()` reads name, type, programme, and pulls DOB and nationality out of the remarks text |
| UN Consolidated | UN Security Council XML | `parse_un()` joins first to fourth names, adds every alias, nationality and dates of birth |
| EU Consolidated | EU Financial Sanctions CSV (one row per name/attribute) | `parse_eu()` groups rows by entity and keeps every name variant |
| UAE Local Terrorist List | Excel file you download from uaeiec.gov.ae and upload | `parse_uae()`; you pick which column holds the name |
| Training list | Built in (`TRAINING_ENTRIES`), **fictional** | so you can practise offline |

Every name and alias becomes one row in `sanctions_entries`. Lists are refreshed on demand from the
*Sanctions lists* tab.

### Matching (`normalise()` and `screen()`)

1. **Normalise** both names: remove accents, lower-case, join "Al-"/"Al " prefixes, drop punctuation and, for
   companies, legal-form words (LLC, Ltd, FZE, S.A.…). Descriptive words such as "Trading" are kept, otherwise
   "Marina Trading LLC" would shrink to "marina" and match everything.
2. **Compare** with `token_sort_ratio` from the `rapidfuzz` library: words are sorted alphabetically and then
   compared character by character, so "KHAN, Ahmed" and "Ahmed Khan" score 100 and small spelling variations
   ("Tehrani" vs "Tehrany") still score around 90.
3. Individuals are only compared with individuals, companies with companies.
4. A **one-word name against a longer name** is ignored, and so are very short names: too weak to mean anything.
5. Anything at or above the **threshold (default 85)** becomes an alert. Lower finds more variants but more
   false positives.
6. **Secondary identifiers** are checked and shown: same nationality, same birth year.
7. Alerts are **never duplicated**: the database refuses a second alert for the same name against the same list
   entry (`UNIQUE` constraint), so reviewed alerts don't come back.

**Who is screened** (`parties()`): every customer plus every shareholder, director and manager in their ownership
tree. Screening runs automatically when you add a customer or an owner, and on demand for everyone.

### Decisions (`decide()`)

* **False positive:** identifiers differ; documented and closed.
* **Potential match (escalate):** can't rule it out → in the UAE, suspend and file a **PNMR** through goAML.
* **True match:** freeze without delay, file an **FFR** through goAML. The customer is rescored (+100, High) and
  can no longer be approved.

---

## 4. Transaction monitoring

**Where:** `tm.py`; pages `pages/5_Transaction_Monitoring.py` and `pages/6_Investigations.py`

### Import (`import_csv()`)

Each row is checked: the customer must exist, date and amount must be readable, direction must be IN or OUT, the
currency must be known. Amounts are converted to AED with fixed rates (`FX_TO_AED`). Rejected rows are listed
with the reason; duplicates (same `txn_id`) are skipped.

### Rules (`run_rules()`, settings in `DEFAULT_RULES`)

| Rule | Logic | Severity | Typology |
|---|---|---|---|
| Large cash | one cash transaction ≥ AED 55,000 | Medium | Cash placement |
| Possible structuring | ≥ 3 cash transactions between AED 40,000 and 54,999 within 7 days | High | Smurfing below the threshold |
| High risk jurisdiction | any transaction with a FATF black list (High) or grey list (Medium) country | High / Medium | Cross-border risk |
| Rapid movement of funds | an incoming amount ≥ AED 100,000 and ≥ 80% of it sent out within 3 days | High | Layering, mule accounts |
| Activity above profile | a month's total > 2 × expected monthly volume (and ≥ AED 50,000) | Medium | Doesn't match KYC |
| Repeated round amounts | ≥ 3 transactions that are exact multiples of AED 10,000 within 30 days | Low | Trade-based laundering |
| Sanctioned counterparty | counterparty name scores ≥ 90 against any loaded sanctions list | Critical | Sanctions evasion |

Every number above can be changed on the *Rules* tab for experimenting. Alerts are de-duplicated by customer +
rule + period, so running the rules again only adds genuinely new alerts.

### From alert to case to STR

1. **Triage** (*Alerts* tab): either close alerts with an explanation (`close_alert()`), or tick them and
   **open a case** (`open_case()`).
2. **Investigate** (*Investigations* page): see every transaction for the customer and their KYC, write the narrative.
3. **Decide** (`update_case()`): *Closed – no suspicion*, or **STR filed**. Closing or filing requires a
   narrative and a rationale.
4. **STR draft** (`str_report()`): builds a text report laid out like the goAML sections (subject, red flags,
   transactions, narrative, action taken) that you can download.
5. Filing an STR **rescores the customer** (+40, High).

**Sample data** (`make_sample_transactions.py`): 90 days of normal activity for every dummy customer, plus planted
patterns: structuring (Reza Tehrani), large cash and round amounts (Golden Sands Jewellery), pass-through to a
sanctioned name (Blue Harbour Holdings), remittances to high risk countries (Falcon Exchange House), cash
donations wired to Yemen (Hope Bridge Charity), and a salary account with sudden large inflows (Priya Nair).

---

## 5. Audit trail

**Where:** `db.log()`, page `pages/7_Audit_Log.py`

Every write (customer created or edited, document ticked, KYC decision, owner added or removed, list refreshed,
screening run, alert decision, case update) records **who, when, what and why**. Regulators expect you to show
not only the decision but the reasoning, and to keep records for at least 5 years.

---

## 6. Governance: policies, effectiveness testing and reports

**Where:** `governance.py`, `reports.py`, pages `8_Policy_Management.py`, `9_Effectiveness_Testing.py`, `10_Reports.py`

**Policy management.** Each policy has a version, owner, approver, review cycle and staff count. It moves through
a fixed workflow (`WORKFLOW`): Drafted, Compliance review, Senior management, Board approved, Published to staff.
Each move needs a note (who approved, meeting reference) and is written to the audit log. Status is worked out,
never typed: before Board approval it is **Draft**; after that it is **Overdue** if the next review date has passed,
**Due for review** within 30 days, otherwise **Current**. Starting a new version sends the policy back to Drafted.
`policy_controls()` puts each policy rule next to the Sanad setting that enforces it (UBO threshold, monitoring
thresholds, review cycles) and flags any that **differ**. The demo deliberately has one difference (medium risk
review: 18 months in the policy, 2 years in the app) so you can see it.

**Effectiveness testing.** A test records the control area, what is tested, the method, sample size, items passed,
tester and evidence. The result is set by `result_for()`: 95% or more passed is **Effective**, 80 to 94% is
**Partially effective**, below 80% is **Ineffective**. The quarter grid shows the latest result per area per quarter.
Findings carry a severity, action, owner and due date; an open finding past its due date shows as **Overdue**, and
closing one needs a note on how the fix was verified.

**Reports.** `reports.build(key, start, end)` returns a title and a list of sections (text or tables) from live data
for the chosen period. The MLRO quarterly report combines all the others (long tables are left to the detailed
reports) and adds the MLRO's conclusions. `to_excel()` writes one sheet per section; `to_html()` writes a clean
printable page you open in a browser and print to PDF.

**Governance dashboard** (`pages/11_Governance_Dashboard.py`). `area_status()` gives each control area its latest
test, result and next test date (last test plus its frequency); an area with no test is "Never tested".
`attention_items()` builds the management to-do list and ranks it: **Act now** for overdue policies, ineffective
controls, and high or overdue findings; **This month** for policies due for review or awaiting approval and policy
rules that differ from Sanad's settings; **Monitor** for low attestation, other open findings and tests that are due.

**Enterprise-wide risk assessment** (`ewra.py`, `pages/12_EWRA.py`; full method in `docs/RISK_SCORING.md`). Six risk factors: Customers, Geography,
Products and services, Delivery channels, Transactions, Sanctions and proliferation financing.
- **Inherent risk** is set from live data by the thresholds in `INHERENT_RULES` (for example, Customers is High
  when over 25% of customers are High risk). Products and services is set by the MLRO. The MLRO can override any
  rating with a reason, which is logged.
- **Control strength** comes from the latest Effectiveness testing result of the control areas mapped to each
  factor in `FACTORS`: any Ineffective = Weak, all Effective = Strong, mostly Effective = Adequate, otherwise or
  never tested = Needs improvement.
- **Residual risk** = `RESIDUAL[inherent][strength]`. A factor whose residual risk is above the risk appetite
  needs an action. Overall risk is the highest factor, except that one High factor alone gives Medium-High.
- The assessment uses the policy workflow; on Board approval the results are saved as a **snapshot** so the
  approved version never changes. The Governance Dashboard flags a missing or out-of-date approved EWRA and
  factors above appetite; the EWRA is also a report and part of the MLRO pack.

---

## 7. AI document intake (`doc_ai.py`, page "AI Document Intake")

The page turns KYC documents into profile fields. The AI only proposes; a person decides.

1. **Read** (`extract()`): each uploaded PDF or photo (max 5 MB, 10 pages) is sent to Claude with a list of
   the fields we want and the app's own country, occupation and licence-activity lists. Claude must answer
   in a fixed structure (document type, name, dates, nationality, document number, expiry, activity,
   owners, notes), so there is no free text to parse. It is told to leave a field empty rather than guess,
   and to treat text inside the document as data, not instructions.
2. **Clean** (`_finish()`): values that are not in the app's lists are blanked with a note, so a wrong
   country or activity can't slip in.
3. **Check** (`checks()`): fixed rules, not AI, flag an expired document, a holder under 18, a missing
   document number, shareholdings that don't add to 100%, and corporate shareholders that need a
   look-through.
4. **Merge** (`merge()`): several documents become one profile. The licence leads for company details,
   the passport for a person; an MOA's own date never overwrites the licence dates. When two documents
   disagree, the page shows the conflict.
5. **Review and save**: the normal customer form opens pre-filled. Updating an existing customer shows a
   "now vs from documents" table. Owners from an MOA appear in an editable table (people already on
   file are unticked). On Save the customer is created or updated (risk re-scored), owners are added
   (UBO analysis re-runs), the matching checklist documents are ticked, sanctions screening runs on the
   customer and the new owners, and the audit log records which files were read and who saved.

**Cost control:** the key lives in Streamlit secrets; `AI_DAILY_LIMIT` (default 25) caps extractions per day,
counted in the `ai_usage` table with token counts. Each document costs roughly a few US cents.

**Without a key:** the three fictional samples in `samples/` return saved results (matched by file hash),
so the flow can be demonstrated offline. Any other file asks for the key.

## 8. Look and feel

`ui.py` holds the shared pieces: the number tiles (`stat_card()`, a thin wrapper around `st.metric`) and the
customer form (`customer_form()`). The app uses Streamlit's default light theme (`.streamlit/config.toml`) and its
built-in charts (`st.bar_chart()`), so there is no custom styling to maintain.

## Where to change things

| I want to… | Edit |
|---|---|
| Change risk points, bands or review cycles | `risk.py` |
| Add or re-rate a UAE trade licence activity | `TRADE_LICENCE_ACTIVITIES` in `uae_activities.py` |
| Update FATF country lists | `FATF_BLACKLIST` / `FATF_GREYLIST` in `risk.py` |
| Change the UBO threshold or offshore list | `UBO_THRESHOLD` / `OFFSHORE` in `ubo.py` |
| Tune name matching | `COMPANY_WORDS`, `normalise()`, `screen()` in `sanctions.py` |
| Change monitoring thresholds permanently | `DEFAULT_RULES` in `tm.py` |
| Add a monitoring rule | add a block in `tm.run_rules()` and an entry in `DEFAULT_RULES` |
| Change the policy workflow or test result bands | `WORKFLOW` / `result_for()` in `governance.py` |
| Change EWRA thresholds, factor-to-control mapping or the residual matrix | `INHERENT_RULES` / `_auto_inherent()`, `FACTORS`, `RESIDUAL` in `ewra.py` |
| Change what AI extracts or its instructions | `Extraction` and `SYSTEM` in `doc_ai.py` |
| Change the AI daily cap | `AI_DAILY_LIMIT` in secrets, or `DEFAULT_DAILY_LIMIT` in `doc_ai.py` |
| Add a report | an entry in `REPORTS` and a builder in `reports.py` |
