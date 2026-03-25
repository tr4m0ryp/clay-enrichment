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

- [ ] **1. Improve system prompts for Avelero** -- Research Avelero (use Claude Code to visit avelero.com, check LinkedIn, understand the DPP business). Rewrite all prompts in `src/prompts.py` so the AI understands Avelero, our target market, and generates results for companies like Filling Pieces, Daily Paper, etc. This is step one because once the prompts are correct, Claude Code will automatically generate correct prompts for all the other layers too.

- [ ] **2. Improve the system workflow** -- Redesign the architecture to run four parallel, continuous layers as described in "How the System Should Work." No layer waits on another. The system runs non-stop, picking up new items as they become available.

- [ ] **3. Find cheaper alternatives for data enrichment** -- Evaluate alternatives to our current paid dependencies (RapidAPI, Serper API). Look into Google Custom Search API, Brave Search API, or any other free/cheaper options for web search and contact enrichment. If there are no better free alternatives, notify Moussa before proceeding.

- [ ] **4. Remove all dead code** -- Delete all unused integrations: Airtable, Google Sheets, HubSpot, Google Docs/Drive, Gmail, YouTube analysis, blog analysis, interview script generation, SPIN questions, RAG/vector DB. Clean up all references in `main.py`, `nodes.py`, `graph.py`, and `prompts.py`.

- [ ] **5. Notify Moussa that steps 1-4 are done** -- Let me know you are finished with the above so I can review before moving on.

- [ ] **6. Improve the README** -- Update the README file to reflect the new system, what it does, and how to set it up.

- [ ] **7. Build the email workflow** -- Implement the full email pipeline: email generation, review in Notion (Pending Review / Approved / Sent / Rejected status column), bulk sending with domain rotation from `.env`, configurable delays between sends, and sender tracking.
