"""
Sovereign Brain — PII Scrubber
================================
Detects and redacts Australian PII from text before audit storage.
The original query is kept for LLM processing; only the audit-stored copy
is scrubbed.

Detected types:
  TFN      — Australian Tax File Number (8–9 digits, various formats)
  MEDICARE — Medicare card number (10–11 digits)
  PHONE    — Australian mobile (04xx) and landline (0x xxxx xxxx)
  EMAIL    — Standard email addresses
  DOB      — Dates of birth (DD/MM/YYYY or DD-MM-YYYY format)
  BSB      — Bank BSB numbers (NNN-NNN)
  ACCOUNT  — Bank account numbers (6–10 digit sequences with surrounding context)

Non-scrubbed (intentional — needed for eligibility evaluation):
  Monetary amounts  ($XXX, $X,XXX/week)
  Age statements    ("I am 35 years old")
  Duration/dates    ("unemployed since January 2024")
"""

import re
from dataclasses import dataclass, field

# Each entry: (compiled_regex, replacement_token)
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # TFN: 8 or 9 digits, optionally space- or hyphen-separated in groups of 3
    (re.compile(
        r'\b(\d{3}[\s\-]?\d{3}[\s\-]?\d{2,3})\b'
        r'(?=.*\b(?:tfn|tax file|tax\s+file\s+number)\b)'
        r'|\b(?:tfn|tax file number)\s*[:\-]?\s*(\d{3}[\s\-]?\d{3}[\s\-]?\d{2,3})\b',
        re.IGNORECASE,
    ), '[TFN]'),

    # Medicare: 10 digits optionally with spaces/dashes (XXXX XXXXX X)
    (re.compile(
        r'\b\d{4}[\s\-]?\d{5}[\s\-]?\d{1}\b'
        r'(?=\s*(?:\d|$|\s))'
        r'|(?:medicare\s*(?:card\s*)?(?:number|no\.?|#)?\s*[:\-]?\s*)(\d{4}[\s\-]?\d{5}[\s\-]?\d{1})\b',
        re.IGNORECASE,
    ), '[MEDICARE]'),

    # Australian mobile: 04XX XXX XXX or +61 4XX XXX XXX
    (re.compile(
        r'\b(?:\+?61\s*4|\b04)\d{2}[\s\-]?\d{3}[\s\-]?\d{3}\b',
        re.IGNORECASE,
    ), '[PHONE]'),

    # Australian landline: (0X) XXXX XXXX or 0X XXXX XXXX
    (re.compile(
        r'\b(?:\(0[2-9]\)|0[2-9])[\s\-]?\d{4}[\s\-]?\d{4}\b',
    ), '[PHONE]'),

    # Email addresses
    (re.compile(
        r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b',
    ), '[EMAIL]'),

    # Date of birth: DD/MM/YYYY or DD-MM-YYYY (8-digit dates only, to avoid false positives)
    (re.compile(
        r'(?:born(?:\s+on)?|d\.?o\.?b\.?|date\s+of\s+birth\s*[:\-]?)\s*'
        r'\d{1,2}[/\-]\d{1,2}[/\-]\d{4}',
        re.IGNORECASE,
    ), '[DOB]'),

    # BSB number: NNN-NNN (bank state branch)
    (re.compile(
        r'\b(?:bsb\s*[:\-]?\s*)?\d{3}[\s\-]\d{3}\b'
        r'(?=.*\b(?:bsb|bank|account)\b)'
        r'|\b(?:bsb\s*[:\-]?\s*)(\d{3}[\s\-]\d{3})\b',
        re.IGNORECASE,
    ), '[BSB]'),

    # Bank account number (only when "account number" context present)
    (re.compile(
        r'(?:account\s+(?:number|no\.?|#)\s*[:\-]?\s*)(\d{6,10})\b',
        re.IGNORECASE,
    ), '[ACCOUNT]'),
]


@dataclass
class ScrubResult:
    scrubbed_text: str
    detected_types: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return len(self.detected_types) == 0


def scrub(text: str) -> ScrubResult:
    """
    Scan text for PII and replace detected values with typed tokens.

    Returns a ScrubResult with:
      - scrubbed_text: text with PII replaced by [TOKEN]
      - detected_types: list of PII type names found (e.g. ['TFN', 'EMAIL'])

    The original text is NOT modified — callers must use scrubbed_text
    for audit storage and retain the original for LLM/eligibility processing.
    """
    result = text
    detected: list[str] = []

    for pattern, token in _PATTERNS:
        if pattern.search(result):
            pii_type = token.strip("[]")
            detected.append(pii_type)
            result = pattern.sub(token, result)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_detected = [t for t in detected if not (t in seen or seen.add(t))]

    return ScrubResult(scrubbed_text=result, detected_types=unique_detected)
