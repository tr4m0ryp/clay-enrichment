// Catalogue of editable system prompts surfaced in Settings.
//
// Each entry maps a stable `key` (also used as the settings-table row
// `prompt:<key>`) to its Python source-of-truth file + symbol so the
// page can read the default text at request time, plus a description
// that explains where in the pipeline this prompt fires.
//
// Keys must stay in sync with the resolve("<key>", ...) calls in the
// matching Python module. Pipeline restart picks up new overrides.

export type PromptCategory =
  | "Identity"
  | "Discovery"
  | "Enrichment"
  | "People"
  | "Person Research"
  | "Scoring"
  | "Campaign Brief"
  | "Email";

export interface PromptEntry {
  key: string;
  title: string;
  description: string;
  category: PromptCategory;
  pythonFile: string; // path relative to repo root
  pythonSymbol: string; // the constant whose body is the default text
}

export const PROMPTS: PromptEntry[] = [
  {
    key: "avelero_identity",
    title: "Avelero Identity Context",
    description:
      "Shared company-context preamble prepended to every other prompt. Defines who Avelero is, what a DPP is, the EU regulatory timeline, target market, and outreach identity. Edit this only if the company positioning itself changes.",
    category: "Identity",
    pythonFile: "src/prompts/base_context.py",
    pythonSymbol: "AVELERO_CONTEXT",
  },
  {
    key: "enrich_company_single_call",
    title: "Company Enrichment (single-call grounded)",
    description:
      "Drives the single Gemini-3 grounded JSON call that combines website discovery, market research, and DPP-fit scoring for a target company. This is the primary enrichment path; the two-step prompts below are only used as fallback.",
    category: "Enrichment",
    pythonFile: "src/enrichment/prompts/single_call.py",
    pythonSymbol: "ENRICH_COMPANY_SINGLE_CALL",
  },
  {
    key: "enrich_company_research",
    title: "Company Research (legacy step 1)",
    description:
      "Fallback grounded research prompt: 9-category free-text company brief used when the single-call path is unavailable. Output is plain prose; structuring happens in the next prompt.",
    category: "Enrichment",
    pythonFile: "src/enrichment/prompts/research.py",
    pythonSymbol: "RESEARCH_COMPANY_GROUNDED",
  },
  {
    key: "enrich_company_structure",
    title: "Company Structure (legacy step 2)",
    description:
      "Converts the grounded research text from step 1 into a structured JSON profile with DPP-fit scoring and 3 evidence-based selling points. Used only on the legacy two-step fallback path.",
    category: "Enrichment",
    pythonFile: "src/enrichment/prompts/structure.py",
    pythonSymbol: "STRUCTURE_COMPANY_ENRICHMENT",
  },
  {
    key: "enrich_company_website_lookup",
    title: "Company Website Lookup",
    description:
      "Grounded fallback that finds a company's official homepage URL when the SearXNG resolver fails. Asks for one canonical URL, rejecting marketplaces, social profiles, and directory listings.",
    category: "Enrichment",
    pythonFile: "src/enrichment/prompts/website_lookup.py",
    pythonSymbol: "FIND_COMPANY_WEBSITE",
  },
  {
    key: "people_discover_contacts",
    title: "Contact Discovery",
    description:
      "Asks the model to recall up to 6 named decision-makers (founders, C-level, heads-of) at a target company who fit the campaign. Strict no-fabrication rules; LinkedIn URLs are filled later by the verified resolver.",
    category: "People",
    pythonFile: "src/people/prompts.py",
    pythonSymbol: "DISCOVER_CONTACTS",
  },
  {
    key: "person_research_structured",
    title: "Person Research",
    description:
      "Builds a typed JSON brief about one named contact (background, achievements, public activity, recent timeline, DPP relevance). Recall-only -- no search access on this call -- so it returns empty fields when the model has no specific knowledge.",
    category: "Person Research",
    pythonFile: "src/person_research/prompts.py",
    pythonSymbol: "RESEARCH_PERSON_STRUCTURED",
  },
  {
    key: "scoring_structure_and_score_person",
    title: "Person Scoring + Structuring",
    description:
      "Takes raw person research plus a campaign target description and produces the structured profile, 1-10 relevance score, and 3-5 personalized outreach hooks consumed by email generation. The 11-field schema feeds the contact_campaigns junction table.",
    category: "Scoring",
    pythonFile: "src/scoring/prompts.py",
    pythonSymbol: "STRUCTURE_AND_SCORE_PERSON",
  },
  {
    key: "campaign_brief_generate",
    title: "Campaign Brief (generate)",
    description:
      "First-pass campaign brief: from a campaign name + target description, produces the ICP brief, voice profile, banned phrases list, and one sample cold email. Triggered by the Next button on the campaign-create flow.",
    category: "Campaign Brief",
    pythonFile: "src/campaign_brief/prompts.py",
    pythonSymbol: "GENERATE_BRIEF",
  },
  {
    key: "campaign_brief_regenerate_sample",
    title: "Campaign Brief (regenerate sample)",
    description:
      "Re-renders only the sample email when the user edits feedback in the brief screen. Echoes ICP brief, voice profile, and banned phrases back unchanged so the round-trip is uniform with the generate call.",
    category: "Campaign Brief",
    pythonFile: "src/campaign_brief/prompts.py",
    pythonSymbol: "REGENERATE_SAMPLE",
  },
  {
    key: "email_generate_outreach",
    title: "Cold Email Generation",
    description:
      "Generates each personalized 75-100 word cold outreach email. Locked to the per-campaign voice profile and banned phrases (injected at the top of the prompt). Three-part structure: timeline hook, value bridge, low-friction CTA.",
    category: "Email",
    pythonFile: "src/email/prompts.py",
    pythonSymbol: "GENERATE_EMAIL",
  },
];
