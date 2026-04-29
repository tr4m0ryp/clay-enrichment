"""Internal HTTP service exposing pipeline functionality to the Next.js web layer.

All Gemini calls flow through src.gemini.client -> src.api_keys.retry_with_fallback,
the same chokepoint pipeline workers use. The service binds to localhost only;
the Next.js routes proxy to it. No public exposure.
"""
