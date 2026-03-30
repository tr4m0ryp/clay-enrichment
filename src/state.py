from typing import List

from pydantic import BaseModel, Field


class CompanyRecord(BaseModel):
    """
    Represents a company flowing through the discovery-enrichment pipeline.
    Created in Layer 1 (discovery), enriched in Layer 2, and used in
    Layers 3 and 4 for contact discovery and email generation.
    """
    name: str = Field(description="Company name")
    website: str = Field(default="", description="Company website URL")
    industry: str = Field(default="", description="Fashion/lifestyle sub-industry")
    location: str = Field(
        default="",
        description="Headquarters location in City, Country format"
    )
    size: str = Field(default="", description="Estimated employee count or range")
    linkedin_url: str = Field(default="", description="Company LinkedIn page URL")
    social_media: str = Field(
        default="",
        description="Comma-separated social media URLs"
    )
    dpp_fit_score: float = Field(
        default=0.0,
        description="DPP fit score from 1.0 to 10.0"
    )
    dpp_fit_reasoning: str = Field(
        default="",
        description="Explanation of the DPP fit score"
    )
    status: str = Field(
        default="Discovered",
        description="Pipeline status: Discovered, Enriched, Contacts Found, Email Drafted, Email Sent, Low Fit"
    )
    notion_page_id: str = Field(
        default="",
        description="Notion page ID once synced to the database"
    )
    discovery_source: str = Field(
        default="",
        description="The search query that originally found this company"
    )
    summary: str = Field(default="", description="Company profile summary")


class ContactRecord(BaseModel):
    """
    Represents a contact person within a target company.
    Created in Layer 3 (people discovery) and used in Layer 4
    (email generation).
    """
    name: str = Field(description="Full name of the contact")
    email: str = Field(default="", description="Email address")
    phone: str = Field(default="", description="Phone number")
    title: str = Field(default="", description="Job title at the company")
    linkedin_url: str = Field(
        default="",
        description="Personal LinkedIn profile URL"
    )
    company_name: str = Field(
        default="",
        description="Name of the company this contact works at"
    )
    company_notion_id: str = Field(
        default="",
        description="Notion page ID of the associated company"
    )
    notion_page_id: str = Field(
        default="",
        description="Notion page ID once synced to the database"
    )


class EmailRecord(BaseModel):
    """
    Represents a generated outreach email that flows through the
    Notion review pipeline (Pending Review -> Approved -> Sent or Rejected).
    """
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Full email body text")
    recipient_email: str = Field(description="Target email address")
    recipient_name: str = Field(default="", description="Target person name")
    company_name: str = Field(default="", description="Target company name")
    status: str = Field(
        default="Pending Review",
        description="Email status: Pending Review, Approved, Sent, Rejected"
    )
    sender_address: str = Field(
        default="",
        description="Which sender address was used to send this email"
    )
    company_notion_id: str = Field(
        default="",
        description="Notion page ID of the associated company in the Companies database"
    )
    notion_page_id: str = Field(
        default="",
        description="Notion page ID in the Emails database"
    )
