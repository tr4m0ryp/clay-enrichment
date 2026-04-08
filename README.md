# Clay Enrichment: Automated Lead Discovery and Outreach for Avelero

## Overview

Fashion brands face mandatory EU Digital Product Passport (DPP) compliance starting mid-2027, with vendor selection needing to happen in 2026 given 6-10 month lead times. Avelero provides a DPP platform that lets brands launch compliant digital passports in days. The challenge: finding and reaching the right brands at the right time, at scale.

Clay Enrichment is Avelero's automated lead discovery, enrichment, and outreach pipeline. It continuously discovers fashion, streetwear, and lifestyle brands that would benefit from DPP, enriches company and contact data, generates personalized outreach emails, and manages the sending process -- all from a single Notion dashboard.

The system runs four independent async workers in parallel. No worker waits for another. Each picks up items as they become available, processes them, and writes results back to Notion. The pipeline moves companies from discovery through enrichment, contact finding, email generation, human review, and sending.

## Core Architecture

```
+---------------------+     +---------------------+     +---------------------+
|  Layer 1: Discovery |     |  Layer 2: Enrichment|     |  Layer 3: People    |
|  - Gemini generates |     |  - Scrapes websites |     |  - Google search    |
|    search queries   |---->|  - AI enrichment    |---->|  - Email permutation|
|  - Google CSE runs  |     |  - DPP fit scoring  |     |  - SMTP verification|
|    searches         |     |  - Notion update    |     |  - Notion contacts  |
+---------------------+     +---------------------+     +---------------------+
                                                                    |
                                                                    v
                         +---------------------+     +---------------------+
                         |  Email Sender        |<----|  Layer 4: Email Gen |
                         |  - SMTP rotation     |     |  - Personalized     |
                         |  - 3-8 min delays    |     |    outreach emails  |
                         |  - 10/day/sender     |     |  - Pending Review   |
                         |  - 15% fail stop     |     |    in Notion        |
                         +---------------------+     +---------------------+
```

All layers run continuously as `asyncio` coroutines. A supervisor restarts any crashed worker after 30 seconds. Graceful shutdown on SIGINT/SIGTERM.

## How It Works

**1. Campaign-Driven Discovery** -- Create a campaign in Notion with a natural language target description (e.g., "Find EU streetwear brands with sustainability initiatives"). Gemini generates 10-20 search queries per cycle. Google Custom Search executes them. Gemini parses results into company names. New companies are deduplicated and written to the Companies database.

**2. Single-Pass Enrichment** -- Companies with status "Discovered" are scraped (with fallback to alternative sources if the main site fails). Scraped content is sent to Gemini in batches of 3 for single-pass enrichment: company profile, industry classification, and DPP fit scoring (1-10) based on six criteria specific to Avelero's market. Full enrichment reports are stored in Notion page bodies.

**3. Contact Discovery** -- Enriched companies trigger a Google-based people search. Contacts are found without LinkedIn scraping -- the system searches for employees via `site:linkedin.com/in` queries, generates email permutations from name + domain, and verifies addresses via SMTP/MX checks. Verified contacts are created in Notion.

**4. Email Generation and Review** -- Contacts trigger personalized email generation using company context, contact profile, and campaign targeting. Emails land in Notion with "Pending Review" status. A team member reviews and sets status to "Approved" or "Rejected". Only approved emails are sent.

**5. Sending with Safety Rails** -- The sender polls for approved emails, sends via SMTP with round-robin sender rotation, randomized 3-8 minute delays, 10 emails/day/sender limit, and a 15% fail-rate hard stop.

## Notion Dashboard

The system is managed entirely from a single Notion page -- the **Avelero Outreach Hub** -- containing linked views from four databases:

| Database | Purpose | Key Status Flow |
|----------|---------|----------------|
| **Campaigns** | Define what to search for | Active / Paused / Completed |
| **Companies** | Discovered and enriched companies | Discovered -> Enriched -> Contacts Found |
| **Contacts** | People at target companies | Found -> Enriched -> Email Generated |
| **Emails** | Generated outreach with review | Pending Review -> Approved -> Sent |

Relations connect everything: Campaign -> Companies -> Contacts -> Emails. Navigate in any direction. Filter by campaign, status, score, or date.

## Quick Start

<details>
<summary>Prerequisites</summary>

- Python 3.10+
- Gemini API key (paid tier)
- Google Custom Search API key + engine ID
- Notion integration token
- A Notion page shared with the integration

</details>

### Setup

```bash
git clone https://github.com/tr4m0ryp/clay-enrichment.git
cd clay-enrichment
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your API keys:

```bash
GEMINI_API_KEY="your-gemini-key"
GOOGLE_API_KEY="your-google-api-key"
GOOGLE_CSE_ID="your-search-engine-id"
NOTION_API_KEY="your-notion-token"
NOTION_HUB_PAGE_ID="your-notion-page-id"
```

### First Run

The system auto-creates the four Notion databases on first launch:

```bash
python3 -m src.main
```

Copy the printed database IDs into your `.env`, then restart. Create a campaign in the Campaigns database with status "Active" and a target description. The pipeline starts automatically.

### Deployment (Mac Mini)

```bash
chmod +x deploy/install-service.sh
./deploy/install-service.sh
```

This installs a `launchd` service that auto-starts on boot and restarts on crash.

## Technical Details

### Module Breakdown

| Module | Files | Responsibility |
|--------|-------|---------------|
| `src/config.py` | 1 | Environment loading, typed config, sender auto-discovery |
| `src/models/` | 1 | Gemini API client (google-genai SDK), batch support, rate limiting |
| `src/notion/` | 7 | Notion CRUD for all 4 databases, page body management, auto-setup, dedup |
| `src/search/` | 2 | Google Custom Search client, website scraper with fallback |
| `src/discovery/` | 3 | Contact finder, email permutation (8 patterns), SMTP verification |
| `src/prompts/` | 5 | Avelero context layer + task-specific prompts for all 4 layers |
| `src/layers/` | 4 | Async worker loops for discovery, enrichment, people, email generation |
| `src/email/` | 2 | SMTP sender pool with rotation, delays, and safety rails |
| `src/main.py` | 1 | Orchestrator, supervised workers, graceful shutdown |

### Model Strategy

Benchmarked across Gemini 2.5 Flash-Lite, Flash, and Pro. Results:

| Task | Model | Why |
|------|-------|-----|
| Discovery queries | Flash-Lite | High volume, extraction work. 5x faster than Flash. |
| Company enrichment | Flash-Lite | Structured JSON output. Score quality 8/10 vs Flash 9/10. |
| Contact parsing | Flash-Lite | Pattern extraction from search results. |
| Email generation | Flash | Writing quality matters. Marginal but worthwhile improvement. |

Single-pass enrichment (one LLM call instead of chained reports) saves **64% of tokens**. Batching 3 companies per call saves an additional **29%**.

### Rate Limiting

Proactive sliding-window rate limiter prevents all 429 errors by checking capacity before every API call:

| API | Stated Limit | System Ceiling (80%) |
|-----|-------------|---------------------|
| Gemini Flash-Lite | 300 RPM | 240 RPM |
| Gemini Flash/Pro | 150 RPM | 120 RPM |
| Google Custom Search | 100/day | 80/day |
| Notion API | 3 req/sec | 2.5 req/sec |

### Email Safety

| Parameter | Value |
|-----------|-------|
| Daily limit per sender | 10 (configurable) |
| Delay between sends | 3-8 minutes, randomized with +/-20% jitter |
| Fail-rate threshold | 15% triggers hard stop |
| Sending window | Business hours only (Mon-Fri 8-18) |
| Required DNS | SPF, DKIM, DMARC (mandatory since March 2026) |

### Contact Discovery (No LinkedIn Scraping)

Instead of unreliable LinkedIn scraping via RapidAPI, the system uses a three-step waterfall:

1. **Find people** -- Google Custom Search with `site:linkedin.com/in` queries
2. **Generate emails** -- 8 permutation patterns from name + domain
3. **Verify** -- SMTP/MX RCPT TO check (free, no third-party dependency)

### Configuration

All settings live in `.env`. Key tuning parameters:

```bash
MODEL_DISCOVERY="gemini-2.5-flash-lite"     # Model per task (swappable)
MODEL_EMAIL_GENERATION="gemini-2.5-flash"
EMAIL_DAILY_LIMIT_PER_SENDER=10             # Emails/day/mailbox
EMAIL_MIN_DELAY_SECONDS=180                 # Min delay between sends (3 min)
EMAIL_MAX_DELAY_SECONDS=480                 # Max delay (8 min)
ENRICHMENT_STALE_DAYS=90                    # Re-enrich after N days
SENDER_1_EMAIL="outreach1@avelero.com"      # Add as many SENDER_N_ as needed
SENDER_1_PASSWORD="app-password"
```

## Roadmap

- [ ] Migrate from Google Custom Search to Vertex AI Search (CSE deprecated for new customers, deadline Jan 2027)
- [ ] Playwright-based screenshots for documentation
- [ ] CrossLinked integration for employee enumeration without search API
- [ ] Campaign analytics dashboard in Notion (rollup metrics)
- [ ] Webhook-based email approval (faster than polling)

## Disclaimer

This system is designed for legitimate business outreach. It does not scrape LinkedIn directly, does not bypass authentication, and respects email sending limits to avoid spam classification. The email sender is disabled by default until SMTP credentials are configured. Always ensure SPF, DKIM, and DMARC are properly configured before sending. Comply with GDPR and applicable regulations when processing personal contact data.

## License

Internal tool for Avelero. Not licensed for external distribution.
