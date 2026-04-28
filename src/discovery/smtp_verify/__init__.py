"""SMTP/MX email verification.

Public API: SMTPVerifier and the VerifyResult dataclass.
"""

from src.discovery.smtp_verify.types import VerifyResult
from src.discovery.smtp_verify.verifier import SMTPVerifier

__all__ = ["SMTPVerifier", "VerifyResult"]
