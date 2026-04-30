"""Defer-to-high-priority email resolver.

Picks contact_campaigns rows with relevance_score >= threshold whose
contact has no email yet, runs the full email-resolution chain (Hunter
pattern -> deterministic construction -> MyEmailVerifier validation),
and writes the verified email back. Saves Hunter / verification credits
by skipping contacts that scored below threshold.
"""
