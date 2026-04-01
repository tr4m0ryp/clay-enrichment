# Avelero Lead Discovery Pipeline

Automated lead discovery, company enrichment, contact research, and outreach drafting for [Avelero](https://avelero.com). The pipeline discovers fashion and lifestyle brands, scores them for Digital Product Passport (DPP) relevance, finds decision-makers, drafts personalized emails, and uses Notion as the operational system of record.

## Overview

The application runs as four long-lived pipeline layers plus a separate email sender:

1. `discovery`
   Generates search queries with Gemini, runs Serper searches, extracts target companies, de-duplicates them against Notion, and creates new company records with status `Discovered`.
2. `enrichment`
   Scrapes company websites, analyzes recent news, enriches company data, calculates a DPP fit score, and marks each company as `Enriched` or `Low Fit`.
3. `people`
   Searches for relevant decision-makers, extracts contact details from search results, optionally enriches contacts with LinkedIn data, and stores the primary contact on the company record with status `Contacts Found`.
4. `email`
   Generates a personalized outreach draft for each contact with an email address, creates a Notion email record with status `Pending Review`, and updates the company status to `Email Drafted`.
5. `--send-emails`
   Runs separately from the pipeline. It polls Notion for `Approved` emails, sends them over SMTP using round-robin sender rotation, and updates both email and company statuses to `Sent` / `Email Sent`.

Each layer runs continuously and can recover its pending work from Notion on startup, which makes restarts and single-layer testing practical.

## Requirements

- Python 3.9+
- A Notion workspace with an internal integration and API access
- `GOOGLE_API_KEY` for Gemini
- `SERPER_API_KEY` for Google search and news search through Serper
- `NOTION_API_KEY` plus the relevant Notion page/database IDs
- SMTP access for outbound email sending
- `RAPIDAPI_KEY` is optional but recommended if you want LinkedIn enrichment

## Installation

1. Create and activate a virtual environment:

```sh
python -m venv venv
```

macOS/Linux:

```sh
source venv/bin/activate
```

PowerShell:

```powershell
venv\Scripts\Activate.ps1
```

2. Install dependencies:

```sh
pip install -r requirements.txt
```

3. Create your local environment file:

macOS/Linux:

```sh
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

4. Fill in `.env` with your credentials and runtime settings.

## Notion Setup

This project expects two databases in Notion:

- `Companies`
- `Outreach Emails`

The easiest way to create them is:

1. Create a Notion page where the databases should live.
2. Share that page with your Notion integration.
3. Set `NOTION_API_KEY` and `NOTION_PARENT_PAGE_ID` in `.env`.
4. Run:

```sh
python main.py --setup
```

The script creates both databases and prints the generated database IDs. Add those IDs back into `.env` as:

- `NOTION_COMPANIES_DB_ID`
- `NOTION_EMAILS_DB_ID`

## Configuration

`.env.example` contains the full configuration surface:

```dotenv
# AI Model (Gemini)
GOOGLE_API_KEY=

# Web Search (Serper API)
SERPER_API_KEY=

# LinkedIn Scraping (optional)
RAPIDAPI_KEY=

# Notion CRM
NOTION_API_KEY=
NOTION_PARENT_PAGE_ID=
NOTION_COMPANIES_DB_ID=
NOTION_EMAILS_DB_ID=

# Email Sending (SMTP)
EMAIL_SENDER_ADDRESSES=
EMAIL_SMTP_HOST=
EMAIL_SMTP_PORT=587
EMAIL_SMTP_PASSWORD=
EMAIL_DELAY_SECONDS=15
EMAIL_MAX_PER_SENDER_PER_HOUR=20
EMAIL_POLL_INTERVAL_SECONDS=300

# Pipeline Configuration
DISCOVERY_INTERVAL_SECONDS=60
DPP_FIT_THRESHOLD=6
```

Notes:

- `EMAIL_SENDER_ADDRESSES` is a comma-separated list used for round-robin sending.
- SMTP authentication currently logs in with the sender email address and one shared `EMAIL_SMTP_PASSWORD`.
- `RAPIDAPI_KEY` is optional. If it is missing, the pipeline still runs but skips LinkedIn profile enrichment.
- `DPP_FIT_THRESHOLD` controls which companies move from enrichment to people discovery.
- `DISCOVERY_INTERVAL_SECONDS` controls how often the discovery layer generates a new batch of search queries.

## Usage

Run the full four-layer pipeline:

```sh
python main.py
```

Run one layer only:

```sh
python main.py --layer discovery
python main.py --layer enrichment
python main.py --layer people
python main.py --layer email
```

Run the email sender:

```sh
python main.py --send-emails
```

Create the Notion databases:

```sh
python main.py --setup
```

Use `Ctrl+C` to stop gracefully. The orchestrator sets a shutdown event and lets the active work item finish before exiting.

## Workflow In Notion

### Company statuses

- `Discovered`: created by the discovery layer
- `Enriched`: passed DPP scoring and is ready for people discovery
- `Low Fit`: filtered out by the enrichment layer
- `Contacts Found`: at least one decision-maker was found and stored
- `Email Drafted`: an outreach draft exists in the email database
- `Email Sent`: an approved email was sent successfully

### Email statuses

- `Pending Review`: created by the email generation layer
- `Approved`: ready for sending
- `Rejected`: manually rejected in Notion
- `Sent`: marked after successful SMTP delivery

Typical flow:

1. Run `python main.py` to keep discovery, enrichment, contact research, and draft generation moving.
2. Review generated drafts in the `Outreach Emails` database.
3. Change selected drafts from `Pending Review` to `Approved`.
4. Run `python main.py --send-emails` in a separate process to send approved emails.

## Recovery Behavior

The system is designed to resume from Notion state on startup:

- discovery re-queues companies with status `Discovered`
- enrichment re-queues companies with status `Discovered`
- people re-queues companies with status `Enriched`
- email generation re-queues contacts reconstructed from companies with status `Contacts Found`

That means you can restart the process or run a single layer without losing all progress, as long as the required records already exist in Notion.

## Project Structure

```text
main.py
setup_notion.py
src/
  orchestrator.py
  state.py
  structured_outputs.py
  utils.py
  prompts/
    discovery.py
    enrichment.py
    people.py
    email.py
  layers/
    discovery.py
    enrichment.py
    people.py
    email_generation.py
  tools/
    notion.py
    search.py
    web_scraper.py
    linkedin.py
  email/
    smtp_client.py
    sender.py
```

## Implementation Notes

- The pipeline uses in-memory queues between layers during a live run.
- Notion is the durable system of record used for restart and recovery.
- Website content and generated text written to Notion are trimmed to fit Notion property limits in several places.
- The default LLM path is Gemini via `langchain_google_genai`.
- Search is implemented through Serper's Google Search and News APIs.

## Troubleshooting

- If nothing is being discovered, verify `GOOGLE_API_KEY` and `SERPER_API_KEY`.
- If Notion operations fail, make sure the integration has access to the parent page and both databases.
- If emails are generated but never sent, confirm the email record status is `Approved` and the SMTP settings are valid.
- If SMTP authentication fails for rotated senders, confirm all sender addresses can authenticate with the configured shared password.
