import os
import queue

from src.structured_outputs import CompanyEnrichment, DppFitScore, WebsiteAnalysis
from src.prompts.enrichment import (
    WEBSITE_ANALYSIS_PROMPT,
    COMPANY_ENRICHMENT_PROMPT,
    DPP_FIT_SCORING_PROMPT,
    NEWS_ANALYSIS_PROMPT,
)
from src.tools.web_scraper import scrape_website_to_markdown
from src.tools.search import google_news_search
from src.tools.notion import update_company
from src.utils import invoke_llm, get_current_date, log_status, log_success, log_error


def run_enrichment_layer(shutdown_event, input_queue, output_queue):
    """
    Layer 2: Company Enrichment. Runs continuously, pulling discovered
    companies from the input queue, scraping their websites, enriching
    data via LLM, scoring DPP fit, and pushing qualified companies to
    the people discovery queue.

    Parameters:
        shutdown_event: A threading.Event that signals when to stop.
        input_queue: Queue of CompanyRecord objects from the discovery layer.
        output_queue: Queue to push enriched CompanyRecord objects to.
    """
    dpp_threshold = float(os.getenv("DPP_FIT_THRESHOLD", "6"))

    # Recovery: re-queue companies that were discovered but not yet enriched
    _recover_from_notion(input_queue)

    while not shutdown_event.is_set():
        try:
            # Block for up to 5 seconds waiting for work
            company = input_queue.get(timeout=5)
        except queue.Empty:
            continue

        log_status(f"[Enrichment] Processing: {company.name}")

        # Scrape company website
        website_content = ""
        if company.website:
            website_content = scrape_website_to_markdown(company.website)

        if not website_content:
            # Try to find website via search
            website_content = _search_for_company_info(company.name)

        # Analyze website for basic info and social links
        website_data = _analyze_website(company.website or "", website_content)

        # Enrich company data with structured extraction
        enrichment = _enrich_company(company.name, website_content)

        # Fetch and analyze recent news
        news_context = _get_news_context(company.name)

        # Build enrichment context for scoring
        scoring_context = _build_scoring_context(
            company.name, enrichment, website_data, news_context
        )

        # Score DPP fit
        score_result = _score_dpp_fit(scoring_context)

        # Update company record with enrichment data
        company.industry = enrichment.industry if enrichment else ""
        company.location = enrichment.location if enrichment else ""
        company.size = enrichment.size_estimate if enrichment else ""
        company.summary = enrichment.summary if enrichment else company.summary
        company.social_media = enrichment.social_links if enrichment else ""
        company.dpp_fit_score = score_result.score if score_result else 0.0
        company.dpp_fit_reasoning = score_result.reasoning if score_result else ""

        if website_data:
            company.linkedin_url = website_data.linkedin or company.linkedin_url

        # Update Notion
        if company.notion_page_id:
            if score_result and score_result.score >= dpp_threshold:
                company.status = "Enriched"
            else:
                company.status = "Low Fit"

            update_company(company.notion_page_id, {
                "Status": company.status,
                "Industry": company.industry,
                "Location": company.location,
                "Size": company.size,
                "LinkedIn": company.linkedin_url,
                "Social Media": company.social_media,
                "DPP Fit Score": company.dpp_fit_score,
                "DPP Fit Reasoning": company.dpp_fit_reasoning,
                "Summary": company.summary,
            })

        # Push to people queue if above threshold
        if score_result and score_result.score >= dpp_threshold:
            output_queue.put(company)
            log_success(
                f"[Enrichment] {company.name} -- score {score_result.score:.1f} -- qualified"
            )
        else:
            score_val = score_result.score if score_result else 0.0
            log_status(
                f"[Enrichment] {company.name} -- score {score_val:.1f} -- below threshold"
            )


def _search_for_company_info(company_name):
    """
    Searches Google for a company and scrapes the first result to get
    website content when no website URL is known.

    Parameters:
        company_name: The company name to search for.

    Returns:
        Scraped website content as markdown, or empty string.
    """
    from src.tools.search import google_search
    try:
        results = google_search(f"{company_name} official website", num_results=3)
        for result in results:
            link = result.get("link", "")
            if link and "linkedin.com" not in link and "facebook.com" not in link:
                content = scrape_website_to_markdown(link)
                if content:
                    return content
    except Exception as e:
        log_error(f"[Enrichment] Search for {company_name} failed: {e}")
    return ""


def _analyze_website(url, content):
    """
    Uses LLM to analyze website content and extract structured data
    including social media links.

    Parameters:
        url: The website URL.
        content: The scraped website content as markdown.

    Returns:
        A WebsiteAnalysis object, or None on failure.
    """
    if not content:
        return None
    try:
        prompt = WEBSITE_ANALYSIS_PROMPT.format(main_url=url)
        return invoke_llm(
            system_prompt=prompt,
            user_message=content[:10000],
            response_format=WebsiteAnalysis,
        )
    except Exception as e:
        log_error(f"[Enrichment] Website analysis failed: {e}")
        return None


def _enrich_company(company_name, website_content):
    """
    Uses LLM to extract structured company enrichment data from
    website content.

    Parameters:
        company_name: The company name.
        website_content: Scraped website content as markdown.

    Returns:
        A CompanyEnrichment object, or None on failure.
    """
    if not website_content:
        return None
    try:
        return invoke_llm(
            system_prompt=COMPANY_ENRICHMENT_PROMPT,
            user_message=f"Company: {company_name}\n\nWebsite content:\n{website_content[:10000]}",
            response_format=CompanyEnrichment,
        )
    except Exception as e:
        log_error(f"[Enrichment] Company enrichment failed: {e}")
        return None


def _get_news_context(company_name):
    """
    Fetches and analyzes recent news about a company.

    Parameters:
        company_name: The company name to search news for.

    Returns:
        A string with analyzed news context, or empty string.
    """
    try:
        raw_news = google_news_search(company_name, num_results=10)
        if not raw_news:
            return ""
        prompt = NEWS_ANALYSIS_PROMPT.format(
            company_name=company_name,
            number_months=6,
            date=get_current_date(),
        )
        return invoke_llm(
            system_prompt=prompt,
            user_message=raw_news,
        )
    except Exception as e:
        log_error(f"[Enrichment] News analysis failed: {e}")
        return ""


def _build_scoring_context(company_name, enrichment, website_data, news_context):
    """
    Builds a text summary of all enrichment data for the DPP scoring prompt.

    Parameters:
        company_name: The company name.
        enrichment: A CompanyEnrichment object (or None).
        website_data: A WebsiteAnalysis object (or None).
        news_context: Analyzed news string.

    Returns:
        A formatted string containing all available company information.
    """
    parts = [f"# Company: {company_name}\n"]
    if enrichment:
        parts.append(f"## Enrichment Data")
        parts.append(f"Industry: {enrichment.industry}")
        parts.append(f"Location: {enrichment.location}")
        parts.append(f"Size: {enrichment.size_estimate}")
        parts.append(f"Products: {enrichment.products}")
        parts.append(f"Summary: {enrichment.summary}")
    if website_data:
        parts.append(f"\n## Website Analysis")
        parts.append(f"Summary: {website_data.summary}")
    if news_context:
        parts.append(f"\n## Recent News")
        parts.append(news_context)
    return "\n".join(parts)


def _score_dpp_fit(context):
    """
    Uses LLM to score how well a company fits as an Avelero DPP customer.

    Parameters:
        context: A formatted string with all available company information.

    Returns:
        A DppFitScore object, or None on failure.
    """
    if not context or context.strip() == "":
        return None
    try:
        return invoke_llm(
            system_prompt=DPP_FIT_SCORING_PROMPT,
            user_message=context,
            model="gemini-2.5-flash",
            response_format=DppFitScore,
        )
    except Exception as e:
        log_error(f"[Enrichment] DPP fit scoring failed: {e}")
        return None


def _recover_from_notion(input_queue):
    """
    On startup, queries Notion for companies with status "Discovered"
    and adds them to the input queue for enrichment. This allows the
    enrichment layer to be tested independently or recover after a restart.

    Parameters:
        input_queue: Queue to push recovered CompanyRecord objects to.
    """
    from src.tools.notion import query_companies_by_status
    try:
        discovered = query_companies_by_status("Discovered")
        if discovered:
            log_status(f"[Enrichment] Recovering {len(discovered)} companies from Notion")
            for company in discovered:
                input_queue.put(company)
    except Exception as e:
        log_error(f"[Enrichment] Recovery failed: {e}")
