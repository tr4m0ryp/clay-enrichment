import queue

from src.state import EmailRecord
from src.structured_outputs import OutreachEmail
from src.prompts.email import EMAIL_GENERATION_PROMPT
from src.tools.notion import (
    get_company_by_page_id,
    create_email,
    update_company,
)
from src.utils import invoke_llm, log_status, log_success, log_error


def run_email_generation_layer(shutdown_event, input_queue, output_queue):
    """
    Layer 4: Email Generation. Runs continuously, pulling contacts from
    the input queue, fetching their company data from Notion, generating
    personalized outreach emails via LLM, and writing them to the Notion
    Emails database for review.

    Parameters:
        shutdown_event: A threading.Event that signals when to stop.
        input_queue: Queue of ContactRecord objects from the people layer.
        output_queue: Not used (emails go to Notion for review).
    """
    while not shutdown_event.is_set():
        try:
            contact = input_queue.get(timeout=5)
        except queue.Empty:
            continue

        log_status(f"[Email] Generating email for: {contact.name} at {contact.company_name}")

        # Skip contacts without email addresses
        if not contact.email:
            log_status(f"[Email] Skipping {contact.name} -- no email address")
            continue

        # Fetch company data from Notion for context
        company_summary = ""
        if contact.company_notion_id:
            company = get_company_by_page_id(contact.company_notion_id)
            if company:
                company_summary = _build_company_context(company)

        # Generate personalized email
        email_output = _generate_email(
            contact.name,
            contact.title,
            contact.company_name,
            company_summary,
        )

        if not email_output:
            log_error(f"[Email] Failed to generate email for {contact.name}")
            continue

        # Create email record in Notion
        email_record = EmailRecord(
            subject=email_output.subject,
            body=email_output.body,
            recipient_email=contact.email,
            recipient_name=contact.name,
            company_name=contact.company_name,
            status="Pending Review",
        )

        page_id = create_email(email_record)
        if page_id:
            email_record.notion_page_id = page_id

        # Update company status in Notion
        if contact.company_notion_id:
            update_company(contact.company_notion_id, {
                "Status": "Email Drafted",
            })

        log_success(f"[Email] Created email for {contact.name} -- pending review in Notion")


def _build_company_context(company):
    """
    Builds a text summary of company data for the email generation prompt.

    Parameters:
        company: A CompanyRecord instance.

    Returns:
        A formatted string with company context.
    """
    parts = []
    if company.summary:
        parts.append(company.summary)
    if company.industry:
        parts.append(f"Industry: {company.industry}")
    if company.location:
        parts.append(f"Location: {company.location}")
    if company.size:
        parts.append(f"Size: {company.size}")
    if company.dpp_fit_reasoning:
        parts.append(f"DPP relevance: {company.dpp_fit_reasoning}")
    return "\n".join(parts)


def _generate_email(contact_name, contact_title, company_name, company_summary):
    """
    Uses LLM to generate a personalized outreach email for a contact.

    Parameters:
        contact_name: The contact's full name.
        contact_title: The contact's job title.
        company_name: The company name.
        company_summary: A text summary of the company's profile and
            DPP relevance.

    Returns:
        An OutreachEmail object with subject and body, or None on failure.
    """
    prompt = EMAIL_GENERATION_PROMPT.format(
        contact_name=contact_name,
        contact_title=contact_title or "team member",
        company_name=company_name,
        company_summary=company_summary or "No additional company information available.",
    )

    try:
        return invoke_llm(
            system_prompt=prompt,
            user_message=f"Write a personalized outreach email to {contact_name} at {company_name}.",
            response_format=OutreachEmail,
        )
    except Exception as e:
        log_error(f"[Email] Email generation failed for {contact_name}: {e}")
        return None
