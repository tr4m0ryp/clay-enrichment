# Clay Enrichment -- Project Instructions

## CRITICAL: Server-First Workflow

This project runs on the GCP server, NOT locally. Local development should only be used for code changes. After every change:

1. Commit and push to GitHub
2. Deploy to server: `gcloud compute ssh searxng --zone=europe-west1-b --command="/opt/clay-enrichment/deploy.sh"`

Do NOT run the pipeline or Next.js app locally -- it will exhaust the local machine. The server handles all execution.

## GCP Server Access

- **Provider:** Google Cloud Platform
- **Project ID:** marketing-team-not-needed
- **Account:** m.ouallaf007@gmail.com
- **Instance:** searxng
- **Zone:** europe-west1-b
- **Machine type:** e2-micro (1.9GB RAM + 2GB swap)
- **Internal IP:** 10.132.0.2
- **External IP:** ephemeral (check with `gcloud compute instances describe searxng --zone=europe-west1-b --format="get(networkInterfaces[0].accessConfigs[0].natIP)"`)
- **SSH:** `gcloud compute ssh searxng --zone=europe-west1-b`
- **Run remote command:** `gcloud compute ssh searxng --zone=europe-west1-b --command="<cmd>"`
- **PATH requirement:** `export PATH="/usr/local/share/google-cloud-sdk/bin:$PATH"` before using gcloud

## Server Stack

- **PostgreSQL 14** -- clay_enrichment database, user: clay
- **Python 3.10** -- pipeline in /opt/clay-enrichment with .venv
- **Node.js 20** -- Next.js frontend in /opt/clay-enrichment/web
- **Nginx** -- reverse proxy on port 80 -> Next.js port 3000
- **Docker** -- SearXNG meta-search on port 8888
- **Web UI:** http://<external-ip>/ (dashboard)
- **SearXNG:** http://<external-ip>:8888 (internal search engine)

## Systemd Services

- `clay-web` -- Next.js frontend (port 3000, proxied by Nginx)
- `clay-pipeline` -- Python enrichment pipeline
- `postgresql` -- Database
- `nginx` -- Reverse proxy

Common commands (run on server):
```
sudo systemctl status clay-web clay-pipeline
sudo systemctl restart clay-web
sudo systemctl restart clay-pipeline
sudo journalctl -u clay-pipeline -f  # tail pipeline logs
sudo journalctl -u clay-web -f       # tail web logs
```

## Deploy Workflow

After pushing code to GitHub:
```
export PATH="/usr/local/share/google-cloud-sdk/bin:$PATH"
gcloud compute ssh searxng --zone=europe-west1-b --command="/opt/clay-enrichment/deploy.sh"
```

The deploy script:
1. git pull
2. pip install -r requirements.txt
3. npm install + next build
4. Restart clay-web service

## Database

- **Connection:** postgresql://clay:clay_enrichment_2026@localhost:5432/clay_enrichment
- **Schema:** schema/001_init.sql (5 main tables + 2 join tables)
- **Tables:** campaigns, companies, contacts, emails, contact_campaigns, company_campaigns, contact_campaign_links
- **Access from Python:** asyncpg via src/db/
- **Access from Next.js:** postgres.js via web/src/lib/db.ts

## Project Structure

```
clay-enrichment/
  src/           -- Python pipeline
    db/          -- Postgres data layer (asyncpg)
    layers/      -- Worker modules (discovery, enrichment, research, scoring, email)
    models/      -- Gemini client
    prompts/     -- LLM prompts
    search/      -- SearXNG, Brave, scraper
    discovery/   -- Contact finder, email permutation, SMTP verify
    email/       -- SMTP sender
  web/           -- Next.js frontend (avelero style)
    src/app/     -- Pages (App Router)
    src/components/ -- UI components
    src/lib/     -- DB connection, queries, utils
  schema/        -- SQL migrations
  scripts/       -- Utility scripts
  deploy.sh      -- Server deploy script
```
