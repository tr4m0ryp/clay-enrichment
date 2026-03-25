import queue

from src.state import ContactRecord
from src.structured_outputs import SearchQueries, ContactInfoList
from src.prompts.people import CONTACT_DISCOVERY_PROMPT, CONTACT_EXTRACTION_PROMPT
from src.tools.search import google_search
from src.tools.linkedin import scrape_linkedin, find_linkedin_profile_url
from src.tools.notion import update_company
from src.utils import invoke_llm, log_status, log_success, log_error


def run_people_layer(shutdown_event, input_queue, output_queue):
    """
    Layer 3: People Discovery. Runs continuously, pulling enriched
    companies from the input queue, searching for decision-makers,
    extracting contact information, and pushing contacts to the email
    generation queue.

    Parameters:
        shutdown_event: A threading.Event that signals when to stop.
        input_queue: Queue of enriched CompanyRecord objects.
        output_queue: Queue to push ContactRecord objects to.
    """
    num_queries_per_company = 5
    max_contacts_per_company = 3

    while not shutdown_event.is_set():
        try:
            company = input_queue.get(timeout=5)
        except queue.Empty:
            continue

        log_status(f"[People] Finding contacts at: {company.name}")

        # Generate search queries for finding decision-makers
        queries = _generate_contact_queries(
            company.name,
            company.industry or "fashion",
            num_queries_per_company,
        )

        if not queries:
            log_error(f"[People] No search queries generated for {company.name}")
            continue

        # Execute searches and collect all results
        all_search_results = []
        for query_text in queries:
            if shutdown_event.is_set():
                break
            results = google_search(query_text, num_results=10)
            all_search_results.extend(results)

        if not all_search_results:
            log_status(f"[People] No search results for {company.name}")
            continue

        # Extract contacts from combined search results
        contacts = _extract_contacts(
            company.name,
            all_search_results,
            max_contacts_per_company,
        )

        if not contacts:
            log_status(f"[People] No contacts found for {company.name}")
            continue

        # Enrich contacts with LinkedIn data where possible
        enriched_contacts = []
        for contact in contacts:
            if shutdown_event.is_set():
                break
            enriched = _enrich_contact_with_linkedin(contact)
            enriched_contacts.append(enriched)

        # Update Notion with contact info and push to email queue
        first_contact = enriched_contacts[0] if enriched_contacts else None
        if first_contact and company.notion_page_id:
            update_company(company.notion_page_id, {
                "Status": "Contacts Found",
                "Contact Name": first_contact.name,
                "Contact Email": first_contact.email,
                "Contact Title": first_contact.title,
                "Contact LinkedIn": first_contact.linkedin_url,
            })

        for contact in enriched_contacts:
            record = ContactRecord(
                name=contact.name,
                email=contact.email,
                title=contact.title,
                linkedin_url=contact.linkedin_url,
                company_name=company.name,
                company_notion_id=company.notion_page_id,
            )
            output_queue.put(record)
            log_success(f"[People] Found: {contact.name} ({contact.title}) at {company.name}")


def _generate_contact_queries(company_name, industry, num_queries):
    """
    Uses LLM to generate search queries for finding decision-makers
    at a target company.

    Parameters:
        company_name: The company name.
        industry: The company's industry.
        num_queries: Number of queries to generate.

    Returns:
        A list of query strings, or empty list on failure.
    """
    prompt = CONTACT_DISCOVERY_PROMPT.format(
        company_name=company_name,
        industry=industry,
        num_queries=num_queries,
    )
    try:
        result = invoke_llm(
            system_prompt=prompt,
            user_message=f"Generate search queries to find contacts at {company_name}.",
            response_format=SearchQueries,
        )
        return result.queries
    except Exception as e:
        log_error(f"[People] Query generation failed for {company_name}: {e}")
        return []


def _extract_contacts(company_name, search_results, max_contacts):
    """
    Uses LLM to extract contact information from combined search results.

    Parameters:
        company_name: The company name.
        search_results: List of dicts with "title", "link", "snippet" keys.
        max_contacts: Maximum number of contacts to extract.

    Returns:
        A list of ContactInfo objects.
    """
    prompt = CONTACT_EXTRACTION_PROMPT.format(
        company_name=company_name,
        max_contacts=max_contacts,
    )
    results_text = "\n".join(
        f"Title: {r.get('title', '')}\nURL: {r.get('link', '')}\nSnippet: {r.get('snippet', '')}\n"
        for r in search_results[:30]  # Limit to avoid token overflow
    )

    try:
        result = invoke_llm(
            system_prompt=prompt,
            user_message=results_text,
            response_format=ContactInfoList,
        )
        return result.contacts
    except Exception as e:
        log_error(f"[People] Contact extraction failed for {company_name}: {e}")
        return []


def _enrich_contact_with_linkedin(contact):
    """
    Attempts to enrich a contact with additional data from their
    LinkedIn profile. If a LinkedIn URL is available, scrapes the
    profile for additional details.

    Parameters:
        contact: A ContactInfo object.

    Returns:
        The same ContactInfo object, possibly with updated fields.
    """
    if not contact.linkedin_url:
        return contact

    try:
        profile_data = scrape_linkedin(contact.linkedin_url, is_company=False)
        if profile_data and isinstance(profile_data, dict):
            # Update email if not already set and available from LinkedIn
            if not contact.email:
                contact.email = profile_data.get("email", "") or ""
            # Update title if available and more specific
            linkedin_title = profile_data.get("headline", "") or profile_data.get("current_title", "")
            if linkedin_title and (not contact.title or len(linkedin_title) > len(contact.title)):
                contact.title = linkedin_title
    except Exception as e:
        log_error(f"[People] LinkedIn enrichment failed for {contact.name}: {e}")

    return contact
