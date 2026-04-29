// Minimal Gemini REST client for the campaign-brief flow. Posts a single
// generateContent request with google_search grounding + JSON mime type and
// returns the parsed text. The full pool/circuit-breaker stack lives in the
// Python pipeline (src/api_keys/retry_with_fallback.py); this web-side
// client does the simpler thing -- one key from process.env, one model, one
// retry on a malformed JSON response.
//
// Used by the /api/campaign-brief/generate and /regenerate routes only.

const ENDPOINT_BASE = "https://generativelanguage.googleapis.com/v1beta/models";
// Default to Gemini 2.5 Pro -- it's available on every paid tier and supports
// google_search grounding. The pipeline prefers Gemini 3 Pro but the Pro
// downshift path is structurally identical (per F16 the prompt is invariant).
const DEFAULT_MODEL =
  process.env.GEMINI_CAMPAIGN_BRIEF_MODEL || "gemini-2.5-pro";
const HTTP_TIMEOUT_MS = 60_000;

type GeminiPart = { text: string };
type GeminiCandidate = { content?: { parts?: GeminiPart[] } };
type GeminiBody = {
  candidates?: GeminiCandidate[];
  error?: { message?: string; status?: string };
};

// Tolerant JSON extraction -- mirrors src/utils/json_extract.py. Lower-tier
// models occasionally wrap output in markdown fences or prose.
const FENCE_RE = /```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```/;
const SPAN_RE = /(\{[\s\S]*\}|\[[\s\S]*\])/;

export function extractJson<T = unknown>(text: string): T | null {
  if (!text) return null;
  const stripped = text.trim();
  try {
    return JSON.parse(stripped) as T;
  } catch {
    // fall through
  }
  const fence = stripped.match(FENCE_RE);
  if (fence?.[1]) {
    try {
      return JSON.parse(fence[1]) as T;
    } catch {
      // fall through
    }
  }
  const span = stripped.match(SPAN_RE);
  if (span?.[1]) {
    try {
      return JSON.parse(span[1]) as T;
    } catch {
      const shrunk = shrinkToBalanced(span[1]);
      if (shrunk) {
        try {
          return JSON.parse(shrunk) as T;
        } catch {
          // exhausted
        }
      }
    }
  }
  return null;
}

function shrinkToBalanced(s: string): string | null {
  if (!s) return null;
  const open = s[0];
  const close = open === "{" ? "}" : open === "[" ? "]" : null;
  if (!close) return null;
  let depth = 0;
  let inString = false;
  let escape = false;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (inString) {
      if (escape) {
        escape = false;
        continue;
      }
      if (ch === "\\") {
        escape = true;
        continue;
      }
      if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (ch === open) depth++;
    else if (ch === close) {
      depth--;
      if (depth === 0) return s.slice(0, i + 1);
    }
  }
  return null;
}

export class GeminiBriefError extends Error {}

interface GenerateOptions {
  systemPrompt: string;
  userMessage: string;
  apiKey?: string;
  model?: string;
}

// Run one grounded + JSON-mode generateContent call. Returns the parsed
// object; throws GeminiBriefError on transport failure, missing API key,
// non-2xx response, empty candidates, or unrecoverable JSON.
export async function generateGroundedJson<T>({
  systemPrompt,
  userMessage,
  apiKey,
  model,
}: GenerateOptions): Promise<T> {
  const key = apiKey || process.env.GEMINI_API_KEY;
  if (!key) {
    throw new GeminiBriefError(
      "GEMINI_API_KEY is not configured on the server",
    );
  }
  const m = model || DEFAULT_MODEL;
  const url = `${ENDPOINT_BASE}/${m}:generateContent`;

  const body = {
    system_instruction: { parts: [{ text: systemPrompt }] },
    contents: [{ role: "user", parts: [{ text: userMessage }] }],
    tools: [{ google_search: {} }],
    generationConfig: {
      temperature: 0.1,
      responseMimeType: "application/json",
    },
  };

  const ctrl = new AbortController();
  const timeout = setTimeout(() => ctrl.abort(), HTTP_TIMEOUT_MS);
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": key,
      },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
  } catch (err) {
    throw new GeminiBriefError(
      `Gemini request failed: ${(err as Error).message}`,
    );
  } finally {
    clearTimeout(timeout);
  }

  const text = await resp.text();
  if (!resp.ok) {
    throw new GeminiBriefError(
      `Gemini ${resp.status}: ${text.slice(0, 400)}`,
    );
  }

  let parsed: GeminiBody;
  try {
    parsed = JSON.parse(text) as GeminiBody;
  } catch {
    throw new GeminiBriefError(
      `Gemini returned non-JSON envelope: ${text.slice(0, 200)}`,
    );
  }
  const candidate = parsed.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!candidate) {
    const reason = parsed.error?.message || "no candidate text";
    throw new GeminiBriefError(`Gemini returned no candidates: ${reason}`);
  }
  const obj = extractJson<T>(candidate);
  if (obj == null) {
    throw new GeminiBriefError(
      `Gemini output was not valid JSON: ${candidate.slice(0, 200)}`,
    );
  }
  return obj;
}
