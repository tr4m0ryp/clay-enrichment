# Avelero Lead Discovery Pipeline

Automated lead discovery, data enrichment, and outreach system built for [Avelero](https://avelero.com), a Digital Product Passport (DPP) company. The system discovers fashion, streetwear, and lifestyle brands that would benefit from DPP services, enriches company and contact data, generates personalized outreach emails, and manages the review-to-send workflow through Notion.

## How It Works

The pipeline runs four independent layers in parallel, each in its own thread:

**Layer 1 -- Company Discovery**: Gemini generates search queries targeting fashion and lifestyle brands in the EU market. Serper API (Google search) finds companies, and the LLM extracts and filters matches. New companies are written to Notion with status "Discovered".

**Layer 2 -- Company Enrichment**: Picks up discovered companies, scrapes their websites, extracts structured data (industry, location, size, products), and scores each company on DPP fit (1-10). Companies above the threshold move forward; low-fit companies are filtered out.

**Layer 3 -- People Discovery**: Finds decision-makers at qualified companies (sustainability, compliance, product, and operations roles). Extracts contact information from search results and enriches via LinkedIn.

**Layer 4 -- Email Generation**: Generates personalized cold outreach emails referencing each company's products, sustainability efforts, and DPP relevance. Emails land in Notion for human review before sending.

**Email Sender**: A separate process polls Notion for approved emails and sends them via SMTP with round-robin domain rotation and configurable delays.

## Prerequisites

- Python 3.9+
- A Notion workspace with API access
- Google API key (Gemini)
- Serper API key (serper.dev, for web search)
- RapidAPI key (for LinkedIn scraping)
- SMTP credentials (for email sending)

## Setup

1. Clone the repository and create a virtual environment:

```sh
git clone <repository-url>
cd clay-enrichment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:

```sh
pip install -r requirements.txt
```

3. Configure environment variables:

```sh
cp .env.example .env
```

Edit `.env` and fill in your API keys. See `.env.example` for all required variables.

4. Set up Notion databases:

Add `NOTION_PARENT_PAGE_ID` to your `.env` (the Notion page where databases will be created), then run:

```sh
python main.py --setup
```

This creates the Companies and Emails databases in Notion and prints the database IDs. Add those IDs to your `.env` as `NOTION_COMPANIES_DB_ID` and `NOTION_EMAILS_DB_ID`.

## Usage

**Run the full pipeline** (all 4 layers in parallel):

```sh
python main.py
```

**Run a single layer** (for testing):

```sh
python main.py --layer discovery
python main.py --layer enrichment
python main.py --layer people
python main.py --layer email
```

**Run the email sender** (sends approved emails from Notion):

```sh
python main.py --send-emails
```

Press `Ctrl+C` to stop gracefully. The system finishes its current work item before shutting down.

## Email Workflow

1. Layer 4 generates emails and writes them to the Notion Emails database with status **Pending Review**
2. A team member reviews each email in Notion and changes the status to **Approved** or **Rejected**
3. The email sender (`--send-emails`) picks up approved emails, sends them via SMTP with domain rotation, and updates the status to **Sent**

Email sending is configured through environment variables:
- `EMAIL_SENDER_ADDRESSES`: Comma-separated list of sender addresses for rotation
- `EMAIL_DELAY_SECONDS`: Wait time between sends (default 15s)
- `EMAIL_MAX_PER_SENDER_PER_HOUR`: Per-address hourly limit (default 20)

## Project Structure

```
main.py                          Entry point with CLI argument handling
setup_notion.py                  One-time Notion database creation
src/
  orchestrator.py                Thread management and pipeline coordination
  state.py                       Pydantic data models (CompanyRecord, ContactRecord, EmailRecord)
  structured_outputs.py          LLM structured output schemas
  utils.py                       LLM invocation, logging helpers
  prompts/                       All system prompts (discovery, enrichment, people, email)
  layers/
    discovery.py                 Layer 1: Company discovery via search
    enrichment.py                Layer 2: Website scraping, data enrichment, DPP scoring
    people.py                    Layer 3: Contact discovery and LinkedIn enrichment
    email_generation.py          Layer 4: Personalized email generation
  email/
    sender.py                    Bulk email sending with domain rotation
    smtp_client.py               SMTP connection wrapper
  tools/
    notion.py                    Notion API client (CRUD, queries, rate limiting)
    search.py                    Serper API (web search and news search)
    web_scraper.py               Website scraping to markdown
    linkedin.py                  LinkedIn profile scraping via RapidAPI
```

## Configuration

All configuration is done through environment variables in `.env`. See `.env.example` for the complete list including:
- AI model keys (Gemini)
- Serper API key (web search)
- Notion API key and database IDs
- LinkedIn scraping (RapidAPI) key
- SMTP email sending configuration
- Pipeline tuning (discovery interval, DPP fit threshold)
