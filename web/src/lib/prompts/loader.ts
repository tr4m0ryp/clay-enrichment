// Server-only: read the default body of a Python prompt constant
// from disk so the Settings UI can show users the current default.
//
// The Python convention is:
//   _DEFAULT_<NAME> = """\
//   ...body...
//   """
// or the legacy bare string:
//   AVELERO_CONTEXT = """\
//   ...body...
//   """
// Both forms are extracted with a single triple-quote slice.

import { promises as fs } from "fs";
import path from "path";

const REPO_ROOT = path.resolve(process.cwd(), "..");

function findTripleQuoteBody(source: string, anchorIdx: number): string | null {
  const open = source.indexOf('"""', anchorIdx);
  if (open === -1) return null;
  let bodyStart = open + 3;
  // Python authors usually open with `"""\` so the literal starts on the
  // next line. Skip the optional backslash + newline so the returned text
  // matches what the constant actually evaluates to.
  if (source[bodyStart] === "\\" && source[bodyStart + 1] === "\n") {
    bodyStart += 2;
  } else if (source[bodyStart] === "\n") {
    bodyStart += 1;
  }
  const close = source.indexOf('"""', bodyStart);
  if (close === -1) return null;
  return source.slice(bodyStart, close);
}

export async function loadPromptDefault(
  pythonFile: string,
  pythonSymbol: string,
): Promise<string> {
  const absPath = path.join(REPO_ROOT, pythonFile);
  let source: string;
  try {
    source = await fs.readFile(absPath, "utf8");
  } catch (err) {
    console.warn(`loadPromptDefault: cannot read ${absPath}:`, err);
    return "";
  }

  // Match either `_DEFAULT_<SYMBOL>` (the new override-aware pattern) or
  // the bare `<SYMBOL>` assignment (used by the identity context that
  // does not flow through `build_system_prompt`).
  const candidates = [`_DEFAULT_${pythonSymbol}`, pythonSymbol];
  for (const name of candidates) {
    const re = new RegExp(`(^|\\n)\\s*${name}\\s*=\\s*`, "g");
    const match = re.exec(source);
    if (!match) continue;
    const body = findTripleQuoteBody(source, match.index + match[0].length);
    if (body !== null) return body;
  }
  return "";
}
