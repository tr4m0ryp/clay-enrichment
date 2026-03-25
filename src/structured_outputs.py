from typing import List

from pydantic import BaseModel, Field


class SearchQueries(BaseModel):
    """Structured output for LLM-generated search queries."""
    queries: List[str] = Field(
        description="List of search query strings to discover target companies"
    )


class DiscoveredCompany(BaseModel):
    """A single company extracted from search results."""
    name: str = Field(description="Company name")
    website: str = Field(default="", description="Company website URL if found")
    reason: str = Field(
        default="",
        description="Brief explanation of why this company appears to be a good DPP fit"
    )


class DiscoveredCompanyList(BaseModel):
    """Structured output containing a list of discovered companies."""
    companies: List[DiscoveredCompany] = Field(
        default_factory=list,
        description="List of companies extracted from search results"
    )


class WebsiteAnalysis(BaseModel):
    """Structured output for website content analysis."""
    summary: str = Field(description="300-word summary of the company website")
    blog_url: str = Field(default="", description="Blog URL if found")
    instagram: str = Field(default="", description="Instagram URL if found")
    linkedin: str = Field(default="", description="LinkedIn URL if found")
    twitter: str = Field(default="", description="Twitter/X URL if found")
    facebook: str = Field(default="", description="Facebook URL if found")
    youtube: str = Field(default="", description="YouTube URL if found")


class CompanyEnrichment(BaseModel):
    """Structured output for enriched company data from website analysis."""
    industry: str = Field(
        default="",
        description="Specific fashion/lifestyle sub-industry"
    )
    location: str = Field(
        default="",
        description="Company headquarters in City, Country format"
    )
    size_estimate: str = Field(
        default="",
        description="Estimated employee count or size range"
    )
    products: str = Field(
        default="",
        description="Key product categories"
    )
    social_links: str = Field(
        default="",
        description="Comma-separated social media URLs found"
    )
    summary: str = Field(
        default="",
        description="200-word company profile"
    )


class DppFitScore(BaseModel):
    """Structured output for DPP fit scoring."""
    score: float = Field(description="DPP fit score from 1.0 to 10.0")
    reasoning: str = Field(description="Brief explanation of the score")


class ContactInfo(BaseModel):
    """A single contact extracted from search results."""
    name: str = Field(description="Full name of the contact")
    title: str = Field(default="", description="Job title at the company")
    email: str = Field(default="", description="Email address if found")
    linkedin_url: str = Field(default="", description="LinkedIn profile URL if found")


class ContactInfoList(BaseModel):
    """Structured output containing a list of discovered contacts."""
    contacts: List[ContactInfo] = Field(
        default_factory=list,
        description="List of contacts extracted from search results"
    )


class OutreachEmail(BaseModel):
    """Structured output for a generated outreach email."""
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Full email body text")
