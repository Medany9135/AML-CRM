# Sanad (سند): AML & Sanctions CMS (prototype)

![Sanad](assets/sanad-logo.png)

A small learning project: KYC, customer risk rating, UBO identification, sanctions screening
and transaction monitoring for a UAE context. **Dummy data only.**

See [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) for the logic behind every feature.

## Run it (Windows or Mac)

1. Install Python 3.11 or newer from python.org (on Windows, tick "Add Python to PATH").
2. Open a terminal in this folder and run:

   ```
   pip install -r requirements.txt
   streamlit run Dashboard.py
   ```

3. Your browser opens at http://localhost:8501. The first launch creates 30 fictional customers.

To start over with fresh dummy data, use **Reset to fresh dummy data** on the Audit Log page,
or run `python seed.py`.

## Switching on AI document intake

1. Get an API key at console.anthropic.com (set a monthly spend limit there too).
2. Locally: create `.streamlit/secrets.toml` with the line `ANTHROPIC_API_KEY = "sk-ant-..."`
   (this file is git-ignored; never commit it).
   On Streamlit Community Cloud: app menu, Settings, Secrets, paste the same line.
3. Optional: `AI_DAILY_LIMIT = 25` caps how many documents can be read per day (default 25).

Without a key the page still works with the bundled fictional samples, using saved results.

## What's in it

| Page | What you can do |
|---|---|
| Dashboard | Risk and KYC status overview, expired IDs, pending KYC, overdue reviews |
| Customers | Search and filter, open a profile, edit KYC details, see why the risk rating was given, tick off documents, approve or reject with a rationale, view the audit trail |
| Add Customer | Onboard an individual or company; risk rating and document checklist are generated |
| AI Document Intake | Upload a passport, Emirates ID, trade licence or MOA (PDF or photo). AI reads the fields; you review and correct them before saving to a new or existing customer. MOA shareholders and directors can be added to the ownership tree. Saving re-runs the risk score and sanctions screening and is audit-logged. Needs an Anthropic API key (see below); fictional samples in `samples/` work without one |
| Ownership & UBO | Record shareholders (people or companies, in layers), directors and managers; see the ownership tree, effective percentages, the UBOs (25% rule with senior management fallback) and ownership red flags, which feed the risk score |
| Sanctions Screening | Download OFAC, UN and EU lists, upload the UAE Local Terrorist List, fuzzy-screen every customer, owner, director and manager, and review alerts (false positive, potential match / PNMR, true match / FFR). A fictional training list is built in |
| Transaction Monitoring | Upload transactions as CSV (or load the 436-row sample with planted red flags), run 7 tunable rules (large cash, structuring, high risk countries, rapid in/out, profile deviation, round amounts, sanctioned counterparties) and triage alerts |
| Investigations | Investigate alerts, write the narrative, close or file an STR, and download a goAML-style STR draft. An STR moves the customer to High risk |
| Governance Dashboard | Programme health, operational risk indicators, a ranked list of what needs management attention, control area status and the next 90 days |
| Risk Assessment (EWRA) | Enterprise-wide risk assessment: inherent risk per factor from live data, control strength from testing, residual risk map, risk appetite, MLRO overrides with reasons, action plan, approval workflow that freezes the approved version, Excel export |
| Policy Management (Governance) | Policy register with versions, owners and review dates; approval workflow (drafted, compliance review, senior management, Board, published to staff) with a note at each step; staff attestation; each policy rule compared with the Sanad setting that enforces it |
| Effectiveness Testing (Governance) | Record periodic control tests (method, sample, passed, evidence); result set automatically; quarter-by-quarter grid; raise findings with owner and due date and close them with evidence |
| Reports (Governance) | 8 ready-made reports (MLRO quarterly pack, customer risk, KYC, sanctions, monitoring, testing, policies, audit trail) for a chosen period, downloadable as Excel or a printable report (print to PDF) |
| Audit Log | Every action, who did it and when |

## Files

| File | Purpose |
|---|---|
| `Dashboard.py` | Entry point: sets the sidebar order and page names |
| `pages/0_Home.py` | Home page |
| `pages/` | The other pages |
| `sanctions.py` | List download, parsing and fuzzy name screening |
| `tm.py` | Transaction import, monitoring rules, alerts, cases and STR drafts |
| `make_sample_transactions.py` | Regenerates `data/sample_transactions.csv` |
| `doc_ai.py` | AI document intake: reads a document with Claude, rule checks (expiry, shareholdings), merges several documents, daily usage cap |
| `samples/` | Fictional specimen documents for AI intake, their saved results, and the script that makes them |
| `ubo.py` | UBO calculation and ownership red flags |
| `governance.py` | Policies, approval workflow, control tests, findings and their demo data |
| `ewra.py` | Enterprise-wide risk assessment: indicators, scoring rules, residual matrix, actions |
| `reports.py` | Builds each report and exports it to Excel or printable HTML |
| `risk.py` | Risk scoring rules, country and sector lists, review cycles, document checklists. **Edit this to change how customers are rated.** |
| `db.py` | SQLite database (`aml_crm.db`, created automatically) |
| `seed.py` | Dummy data generator |
| `ui.py` | Shared form and layout pieces |

## Ideas for later

- Connect a payments API instead of CSV uploads
- Scheduled daily list refresh and rescreening
- User logins and four-eyes approval

The country lists in `risk.py` are samples. Check the current FATF lists before relying on them.
