# Clay Enrichment - Redesign Plan

## What We Want to Achieve

Avelero is a DPP (Digital Product Passport) company. We want to build our own version of what platforms like Clay do -- automated lead discovery, data enrichment, and outreach -- but tailored specifically to Avelero's market.

The system prompts need to be finetuned so the AI understands Avelero's business and generates results that match our target market: companies like Filling Pieces, Daily Paper, and similar fashion, streetwear, and lifestyle brands. The AI should be able to discover these kinds of companies on its own by generating smart search queries based on what it knows about Avelero and our ideal customer profile.

The full pipeline we want: discover companies, enrich their data, find the right people, generate personalized emails, review those emails in Notion, and send approved emails in bulk with smart rotation and delays. All of this should run continuously and in parallel.

---

## How the System Should Work

The system has four layers that all run at the same time, independently and continuously:

### Layer 1: Company Discovery (runs continuously)
Gemini 1.5 Flash generates its own search queries based on a system prompt that describes what kind of companies Avelero targets (fashion, streetwear, lifestyle brands similar to Filling Pieces, Daily Paper, etc.). It uses the Google API key to perform web searches, reads the results, and extracts company names that match. These names get added to a growing list. This layer never stops -- it keeps generating new searches and finding new companies.

### Layer 2: Company Enrichment (runs continuously, picks up new companies as they appear)
As new companies land on the list, this layer picks them up and runs AI-powered web searches to enrich the data -- website, location, size, industry, social media presence, and anything else relevant. The enriched data is saved to a cache so it does not need to be fetched again. This layer runs independently from Layer 1.

### Layer 3: People Discovery and Enrichment (runs continuously, picks up enriched companies)
Using the cached company data, this layer uses AI-powered searches to find the specific people Avelero needs to reach within each company. It then enriches those contacts with email, phone, LinkedIn, job title. All results flow into the Notion database. This layer runs independently from Layers 1 and 2.

### Layer 4: Email Generation and Sending
Once contacts are enriched, the system generates personalized outreach emails for each contact. These emails land in Notion for review (see the Email Workflow section below). This layer runs independently from the other layers.

All four layers run in parallel. No layer waits for another to finish -- each processes items as they become available.

---

## Email Workflow (New -- Not Yet Implemented)

This is a new feature that does not exist in the current project at all.

### Review in Notion
Every generated email appears as a row in a Notion database with a status column. The status starts as **Pending Review**. A team member reviews the email in Notion and either approves it (status changes to **Approved**) or rejects/edits it. Only approved emails get sent.

### Notion Email Status Column
Add a column to the Notion leads table (or a separate emails table) that tracks the email state:
- **Pending Review** -- email has been generated, waiting for human review
- **Approved** -- reviewed and approved, ready to be sent
- **Sent** -- email has been sent
- **Rejected** -- reviewed and rejected, will not be sent

### Bulk Email Sending with Domain Rotation
We need to connect multiple sender email addresses (domain emails) via the `.env` file. The system should:

- Support a large number of sender email addresses (e.g., outreach1@avelero.com, outreach2@avelero.com, etc.)
- Rotate through these sender addresses automatically when sending approved emails
- Add configurable delays between sends (e.g., wait 15 between each email) to avoid spam detection
- Spread emails across the sender pool so no single address sends too many in a short time
- Track which sender address was used for each email

The goal is to send at scale without getting flagged as spam or having domains banned. The rotation and delay logic should be configurable.

---

## What the Current Project Does (and Why It Does Not Fit)

The current codebase was built as a combination of multiple sub-projects for a company called "ElevateAI Marketing Solutions." It is a generic outreach automation system that:

- Fetches leads from Airtable, Google Sheets, or HubSpot
- Scrapes LinkedIn profiles and company websites
- Analyzes blogs, YouTube channels, and news
- Generates digital presence reports, outreach reports, and lead research reports
- Scores leads and generates cold emails and interview scripts
- Saves everything to Google Docs and Google Drive

This is not what we need. The system processes leads one at a time in a fixed sequence (not parallel, not continuous). It focuses on analyzing digital presence and generating marketing materials, not on discovering companies and enriching contact data.

---

## System Prompts Are Completely Wrong

Every system prompt in `src/prompts.py` is written for "ElevateAI Marketing Solutions" -- a marketing agency that sells AI-driven content optimization, SEO, and social media automation. This has nothing to do with Avelero.

All 13 prompts need to be rewritten from scratch:

- The scoring prompt scores leads based on how well they fit ElevateAI's AI marketing services
- The outreach report prompt sells ElevateAI's blog automation, social media automation, and AI chatbots
- The email prompt introduces "Aymen from ElevateAI"
- The interview script prompt pitches ElevateAI's content creation tools
- The blog/YouTube/news analysis prompts evaluate how a company performs on those channels (not relevant to Avelero's needs)

Your co-worker should use Claude Code to research Avelero (visit avelero.com, check their LinkedIn, understand their services and target market) and then rewrite all prompts to reflect what Avelero actually does and what kind of companies we are looking for. The prompts should focus on:

- Describing Avelero's DPP services and what value they bring to brands
- Defining what makes a company a good fit (fashion, lifestyle, streetwear, premium consumer brands that need digital product passports)
- Using examples like Filling Pieces and Daily Paper as reference points for the type of brands we target
- Generating search queries that will find similar companies

---

## Dead Code to Remove

We already have Notion implemented. The following integrations are dead code and should be removed:

- **Airtable integration** (`leads_loader/airtable.py`) -- not used, we use Notion
- **Google Sheets integration** (`leads_loader/google_sheets.py`) -- not used, we use Notion
- **HubSpot integration** (`leads_loader/hubspot.py`) -- not used, we use Notion
- **Google Docs / Google Drive integration** (`google_docs_tools.py`) -- not used, reports go to Notion
- **Gmail integration** (`gmail_tools.py`) -- will be replaced by the new bulk email system
- **YouTube analysis** (`youtube_tools.py`) -- not relevant
- **Blog analysis logic** -- not relevant
- **Interview script generation** -- not relevant
- **SPIN questions generation** -- not relevant
- **RAG / case study retrieval** (`rag_tool.py`, `database/` vector DB) -- not relevant

All references to these in `main.py`, `nodes.py`, `graph.py`, and `prompts.py` should also be cleaned up. The lead loader base class should be simplified since we only support Notion.

---

## Notion Table Improvements

The Notion database is already in place but has issues:

- **Addresses are inconsistent** -- company and contact addresses are logged in different formats across entries. We need a consistent structure (either separate fields for street, city, country, or a single standardized format that is enforced)
- **Score implementation is wrong** -- the current scoring is based on ElevateAI's criteria (digital presence, social media engagement, AI/automation readiness). It needs to be redesigned around what actually makes a company a good fit for Avelero's DPP services
- **Status tracking is incorrect** -- the current statuses (NEW, ATTEMPTED_TO_CONTACT) come from the old outreach workflow and do not reflect our actual pipeline. We need statuses that match how Avelero actually tracks leads through discovery, enrichment, and outreach
- **Email status column needed** -- see the Email Workflow section above

---

## Data Enrichment Dependencies

For the waterfall data enrichment (trying multiple sources in sequence to get contact data), we currently depend on:

- **RapidAPI** for LinkedIn profile scraping -- paid, rate-limited, unreliable if the provider changes their API
- **Serper API** for Google search results -- paid per query

We depend on these third-party companies for core functionality. If they change pricing, rate limits, or break their APIs, our pipeline stops working.

We should evaluate building our own enrichment where possible:

- Google Custom Search API (we already have keys for this) can replace Serper
- Direct web scraping for company information could replace some paid API calls
- Building our own contact enrichment reduces dependency on any single provider
- Owning more of the pipeline gives us control over data quality, cost, and reliability

---

## To-Do Checklist (in order)

Work through these steps in this exact order:

- [x] **1. Work preparation and system prompts for Avelero** -- CLAUDE.md created with full coding rules. Avelero researched. All 8 prompts in `src/prompts/` rewritten for Avelero's DPP services targeting fashion/streetwear/lifestyle brands. Prompts reference ESPR/AGEC regulations and use Filling Pieces, Daily Paper as reference targets.

- [x] **2. Improve the system workflow** -- Redesigned into 4 parallel layers running as daemon threads via `src/orchestrator.py`. Inter-layer communication via thread-safe queues. Each layer has Notion recovery for independent testing and crash recovery. Error recovery with automatic restarts.

- [ ] **3. Find cheaper alternatives for data enrichment** -- Currently using Serper API (paid) for web search and RapidAPI Fresh LinkedIn Scraper (paid) for LinkedIn. Evaluation pending -- see notes below.

  **Evaluation notes (2026-03-30):**
  - Google Custom Search API: 100 free queries/day (10,000/day paid at $5/1000). We already have API keys. However, it requires setting up a Custom Search Engine and results quality may differ from Serper.
  - Brave Search API: Has a free tier (1 query/second, 2000/month). Paid plans start at $3/1000 queries. Independent index, not Google results.
  - Serper API (current): 2,500 free queries, then $50/month for 50,000 queries. Returns Google results directly. Most reliable for our use case.
  - **Recommendation**: Serper is the best option for now. Google CSE is a viable fallback if Serper costs become an issue. Brave Search has a smaller index which may miss niche fashion brands. Notify Moussa for decision.

- [x] **4. Remove all dead code** -- All unused integrations deleted: Airtable, Google Sheets, HubSpot, Google Docs/Drive, Gmail, YouTube, blog analysis, interview scripts, SPIN questions, RAG/vector DB. Codebase is clean.

- [ ] **5. Notify Moussa that steps 1-4 are done** -- Steps 1, 2, and 4 are complete. Step 3 evaluated -- Serper is recommended as best current option. Ready for review.

- [x] **6. Improve the README** -- README rewritten to reflect 4-layer architecture, setup instructions, email workflow, and project structure. References corrected to Serper API.

- [x] **7. Build the email workflow** -- Full pipeline implemented: email generation via LLM, Notion review (Pending Review / Approved / Sent / Rejected), bulk sending via SMTP with round-robin domain rotation, configurable delays, per-sender hourly limits, sender tracking. Company status updates to "Email Sent" after sending.

### Additional fixes applied (2026-03-30, branch fix/integration-fixes):
- Added Notion recovery to enrichment, people, and email layers for single-layer testing
- Wired company_notion_id through EmailRecord so sender can update company status to "Email Sent"
- Added get_contact_from_company helper to Notion client
- Fixed README references from "Google Custom Search" to "Serper API"
