import os
import time

from src.state import CompanyRecord
from src.structured_outputs import SearchQueries, DiscoveredCompanyList
from src.prompts.discovery import COMPANY_DISCOVERY_PROMPT, COMPANY_EXTRACTION_PROMPT
from src.tools.search import google_search
from src.tools.notion import company_exists, create_company
from src.utils import invoke_llm, log_status, log_success, log_error


def run_discovery_layer(shutdown_event, input_queue, output_queue):
    """
    Layer 1: Company Discovery. Runs continuously, generating search
    queries via LLM, executing Google searches, extracting company names,
    de-duplicating against Notion, and pushing new companies to the
    enrichment queue.

    Parameters:
        shutdown_event: A threading.Event that signals when to stop.
        input_queue: Not used (Layer 1 generates its own work).
        output_queue: Queue to push discovered CompanyRecord objects to.
    """
    interval = int(os.getenv("DISCOVERY_INTERVAL_SECONDS", "60"))
    num_queries_per_batch = 5
    max_companies_per_search = 5
    used_queries = set()

    # Recovery: re-queue companies that were discovered but not yet enriched
    _recover_from_notion(output_queue)

    while not shutdown_event.is_set():
        log_status("[Discovery] Generating search queries...")

        # Generate search queries using LLM
        queries = _generate_search_queries(
            num_queries_per_batch, used_queries
        )

        if not queries:
            log_error("[Discovery] No queries generated, retrying next cycle")
            _wait(interval, shutdown_event)
            continue

        # Execute each query and extract companies
        for query in queries:
            if shutdown_event.is_set():
                break

            used_queries.add(query)
            log_status(f"[Discovery] Searching: {query}")

            search_results = google_search(query, num_results=10)
            if not search_results:
                continue

            # Extract companies from search results
            companies = _extract_companies(
                search_results, max_companies_per_search
            )

            for company in companies:
                if shutdown_event.is_set():
                    break

                # De-duplicate against Notion
                if company_exists(company.name):
                    log_status(f"[Discovery] Skipping duplicate: {company.name}")
                    continue

                # Create company record
                record = CompanyRecord(
                    name=company.name,
                    website=company.website,
                    status="Discovered",
                    discovery_source=query,
                    summary=company.reason,
                )

                # Write to Notion
                page_id = create_company(record)
                if page_id:
                    record.notion_page_id = page_id
                    output_queue.put(record)
                    log_success(f"[Discovery] Found: {company.name}")

        _wait(interval, shutdown_event)


def _generate_search_queries(num_queries, used_queries):
    """
    Uses the LLM to generate a batch of search queries for discovering
    target companies.

    Parameters:
        num_queries: Number of queries to generate.
        used_queries: Set of previously used queries to avoid repetition.

    Returns:
        A list of query strings, or empty list on failure.
    """
    used_str = "\n".join(used_queries) if used_queries else "None yet"
    prompt = COMPANY_DISCOVERY_PROMPT.format(
        num_queries=num_queries,
        used_queries=used_str,
    )

    try:
        result = invoke_llm(
            system_prompt=prompt,
            user_message="Generate the next batch of search queries.",
            response_format=SearchQueries,
        )
        return result.queries
    except Exception as e:
        log_error(f"[Discovery] Query generation failed: {e}")
        return []


def _extract_companies(search_results, max_companies):
    """
    Uses the LLM to extract company names and basic info from search results.

    Parameters:
        search_results: List of dicts with "title", "link", "snippet" keys.
        max_companies: Maximum number of companies to extract.

    Returns:
        A list of DiscoveredCompany objects.
    """
    prompt = COMPANY_EXTRACTION_PROMPT.format(max_companies=max_companies)
    results_text = "\n".join(
        f"Title: {r['title']}\nURL: {r['link']}\nSnippet: {r['snippet']}\n"
        for r in search_results
    )

    try:
        result = invoke_llm(
            system_prompt=prompt,
            user_message=results_text,
            response_format=DiscoveredCompanyList,
        )
        return result.companies
    except Exception as e:
        log_error(f"[Discovery] Company extraction failed: {e}")
        return []


def _recover_from_notion(output_queue):
    """
    On startup, queries Notion for companies with status "Discovered"
    and re-queues them for enrichment. This handles recovery after
    a restart.

    Parameters:
        output_queue: Queue to push recovered CompanyRecord objects to.
    """
    from src.tools.notion import query_companies_by_status
    try:
        discovered = query_companies_by_status("Discovered")
        if discovered:
            log_status(f"[Discovery] Recovering {len(discovered)} companies from Notion")
            for company in discovered:
                output_queue.put(company)
    except Exception as e:
        log_error(f"[Discovery] Recovery failed: {e}")


def _wait(seconds, shutdown_event):
    """
    Waits for the specified number of seconds, checking the shutdown
    event every second to allow early exit.

    Parameters:
        seconds: Number of seconds to wait.
        shutdown_event: A threading.Event to check for early exit.
    """
    for _ in range(seconds):
        if shutdown_event.is_set():
            break
        time.sleep(1)
