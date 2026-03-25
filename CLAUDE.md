# CLAUDE.md

## Project Overview

Clay-enrichment is an AI-powered lead discovery and outreach automation system built for Avelero, a DPP (Digital Product Passport) company. The system automates discovering target companies (fashion, streetwear, lifestyle brands like Filling Pieces and Daily Paper), enriching company and contact data, and generating personalized outreach emails. Built in Python using LangGraph, LangChain, and Pydantic. Notion is the only CRM.

---

## Coding Rules

### Naming
- `snake_case` for functions and variables.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for constants and prompt strings.

### Formatting
- Indent with 4 spaces. No tabs.
- Use double quotes (`"`) for all strings.
- Use f-strings for string interpolation. Use `.format()` for prompt templates with placeholders. Use triple-quoted strings for multi-line content.

### Comments and Documentation
- Every function must have a human-readable comment explaining what it does, what parameters it takes, and what it returns. This is required so code can be easily reviewed later.
- Use inline comments above non-obvious logic to explain intent.
- Keep comments concise and factual. No filler, no emojis.

### Imports
- Order: standard library first, then third-party packages, then local modules.
- Separate each group with a blank line.

### Type Hints and Data Models
- Use Pydantic `BaseModel` for structured data (state objects, API responses, structured LLM outputs).
- Use `TypedDict` for LangGraph state definitions.
- Use `Field(description=...)` on Pydantic model fields to document their purpose.
- Add type hints to function signatures where practical.

### Error Handling and Logging
- Wrap external calls (APIs, web scraping, LLM invocations) in try-except blocks.
- Use colorama for console output: `Fore.YELLOW` for status/progress, `Fore.GREEN` for success, `Fore.RED` for errors. Always append `Style.RESET_ALL`.
- Use `print()` with colorama for logging, not the `logging` module.

### Architecture
- All code is synchronous. Do not use `async`/`await`.
- Notion is the only CRM integration. Do not add other CRM integrations.
- Gemini 2.5 Flash is the default AI model.
- LLM calls go through `invoke_llm()` in `src/utils.py`. Do not call LangChain models directly outside that function.
- Prompt constants live in `src/prompts.py` as `UPPER_SNAKE_CASE` strings.
- Structured output schemas live in `src/structured_outputs.py` as Pydantic models.
- State definitions live in `src/state.py`.
- Private/internal helper functions are prefixed with underscore (`_`).

### General
- No emojis anywhere: not in code, comments, docstrings, commit messages, or documentation.
- Use meaningful variable names. Avoid single-letter names except for trivial loop counters.
- Configuration values come from `.env` files loaded via `python-dotenv`. Access with `os.getenv()`.
- Python is the only language for this project.

---

## Git Workflow

- Never push directly to `main`. All new work goes on a feature branch.
- **One branch per feature or task.** Each distinct piece of work (new feature, bug fix, cleanup) gets its own branch. Do not mix unrelated changes on the same branch.
- Branch naming: `feature/<short-description>` for new features, `fix/<short-description>` for bug fixes, `cleanup/<short-description>` for refactoring or dead code removal.
- **Push the branch when the feature is done.** Once all commits for a feature are complete and the code works, push the branch to the remote. Do not leave finished work unpushed.
- Do not merge branches. All merges are done manually after human review.
- Write clear, concise commit messages in imperative mood (e.g., "Rewrite scoring prompt for Avelero"). No emojis in commit messages.
- Keep commits focused. One commit per logical change.
- Run `/review` before pushing a branch to catch issues early.

---

## General Principles

- Remove dead code aggressively. Do not leave unused functions, imports, variables, or commented-out code in the codebase. If something is not being used, delete it.
- Keep files compact. Aim for around 300 lines max per file. If a file grows beyond that, split it into logical modules.
- Organize files into directories. Do not let a large number of individual files accumulate in a single directory. Group related files into subdirectories.
- Keep `.md` files to a minimum. Do not create documentation files unless absolutely necessary. If documentation is needed, place it in the `/docs` directory.

---

## Planned Improvements

Summary of the full redesign plan in `IMPROVEMENTS.md`. Work through these in order.

### 1. Rewrite System Prompts for Avelero
All 13 prompts in `src/prompts.py` are written for "ElevateAI Marketing Solutions" and must be rewritten from scratch for Avelero's DPP services. Prompts should describe Avelero's value proposition, define what makes a company a good fit (fashion, lifestyle, streetwear, premium consumer brands needing digital product passports), and use Filling Pieces and Daily Paper as reference targets.

### 2. Redesign Architecture to 4 Parallel Layers
Replace the current sequential single-lead pipeline with four independent, continuously running layers:
- Layer 1 -- Company Discovery: AI generates search queries and discovers target companies continuously.
- Layer 2 -- Company Enrichment: Picks up discovered companies and enriches with web data (website, location, size, industry, socials).
- Layer 3 -- People Discovery: Finds and enriches contacts within companies (email, phone, LinkedIn, job title). Results flow into Notion.
- Layer 4 -- Email Generation and Sending: Generates personalized emails, sends to Notion for review, bulk sends approved emails with domain rotation.

### 3. Find Cheaper Data Enrichment Alternatives
Evaluate replacements for RapidAPI (LinkedIn scraping) and Serper API (Google search). Candidates: Google Custom Search API (keys already available), Brave Search API, direct web scraping. Notify Moussa if no free/cheaper alternatives exist.

### 4. Remove Dead Code
Delete all unused integrations and clean up references across `main.py`, `nodes.py`, `graph.py`, and `prompts.py`: Airtable, Google Sheets, HubSpot, Google Docs/Drive, Gmail, YouTube analysis, blog analysis, interview script generation, SPIN questions, RAG/vector DB.

### 5. Build Email Workflow
Implement email generation with a Notion review pipeline (statuses: Pending Review, Approved, Sent, Rejected) and bulk sending with configurable domain rotation and delays from `.env`.

### 6. Fix Notion Table Issues
- Standardize address format across all entries.
- Redesign lead scoring around Avelero's DPP fit criteria.
- Replace old statuses (NEW, ATTEMPTED_TO_CONTACT) with statuses matching the new discovery-enrichment-outreach pipeline.

### 7. Update README
Rewrite `README.md` to reflect the new system, its purpose, and setup instructions.
