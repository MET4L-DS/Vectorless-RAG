"""
src/act_adapters/__init__.py
----------------------------
Central registry of ActAdapter configs for the 5 new statutory acts.
Import from here in main.py:
    from act_adapters import NEW_ACT_ADAPTERS
"""

import re
from src.generic_parser import ActAdapter

# ---------------------------------------------------------------------------
# Shared regex building blocks
# ---------------------------------------------------------------------------

# Standard chapter: CHAPTER I, CHAPTER IX, CHAPTER XII
_CHAPTER_RE_STD = re.compile(r"^CHAPTER\s+([IVXLCM]+)$", re.IGNORECASE)

# Extended chapter: also handles Arabic digits (IT Act body uses "CHAPTER 1")
# and letter-suffixed chapters (NDPS "CHAPTER IIA", "CHAPTER VA")
_CHAPTER_RE_EXT = re.compile(r"^CHAPTER\s+([IVXLCDM\d]+[A-Z]?)$", re.IGNORECASE)

# NDPS-specific: roman numerals + optional single-letter suffix (IIA, VA)
_CHAPTER_RE_NDPS = re.compile(r"^CHAPTER\s+([IVXLCM]+[A-Z]?)$", re.IGNORECASE)

# Standard section: "35. Title of section.—Body text"
# Requires an em-dash (–, —, ―, ‒, or plain -) after the title fragment
_EM_DASH = r"[\u2013\u2014\u2015\u2010\-]"
_SECTION_RE_STD = re.compile(
    r"^(\d{1,3}[A-Z]?)\s*\.\s*(.+?)(?:\s*\.)?\s*" + _EM_DASH,
    re.IGNORECASE,
)
_SECTION_START_RE_STD = re.compile(r"^(\d{1,3}[A-Z]?)\s*\.\s*(.+)$", re.IGNORECASE)

# NDPS-specific section: also handles "68-I.", "68-O." style
_SECTION_RE_NDPS = re.compile(
    r"^(\d{1,3}(?:[A-Z]|-[A-Z])?)\s*\.\s*(.+?)(?:\s*\.)?\s*" + _EM_DASH,
    re.IGNORECASE,
)
_SECTION_START_RE_NDPS = re.compile(
    r"^(\d{1,3}(?:[A-Z]|-[A-Z])?)\s*\.\s*(.+)$", re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Adapter definitions
# ---------------------------------------------------------------------------

IT_ADAPTER = ActAdapter(
    act_code          = "IT",
    act_full_name     = "THE INFORMATION TECHNOLOGY ACT, 2000",
    body_start_page   = 4,          # 0-indexed; pages 1-4 are TOC
    chapter_re        = _CHAPTER_RE_EXT,   # handles both "CHAPTER 1" and "CHAPTER II"
    section_re        = _SECTION_RE_STD,
    section_start_re  = _SECTION_START_RE_STD,
)

JJA_ADAPTER = ActAdapter(
    act_code          = "JJA",
    act_full_name     = "THE JUVENILE JUSTICE (CARE AND PROTECTION OF CHILDREN) ACT, 2015",
    body_start_page   = 5,          # 0-indexed; pages 1-5 are TOC
    chapter_re        = _CHAPTER_RE_STD,
    section_re        = _SECTION_RE_STD,
    section_start_re  = _SECTION_START_RE_STD,
)

POCSO_ADAPTER = ActAdapter(
    act_code          = "POCSO",
    act_full_name     = "THE PROTECTION OF CHILDREN FROM SEXUAL OFFENCES ACT, 2012",
    body_start_page   = 2,          # 0-indexed; pages 1-2 are TOC
    chapter_re        = _CHAPTER_RE_STD,
    section_re        = _SECTION_RE_STD,
    section_start_re  = _SECTION_START_RE_STD,
)

NDPS_ADAPTER = ActAdapter(
    act_code          = "NDPS",
    act_full_name     = "THE NARCOTIC DRUGS AND PSYCHOTROPIC SUBSTANCES ACT, 1985",
    body_start_page   = 4,          # 0-indexed; pages 1-4 are TOC
    chapter_re        = _CHAPTER_RE_NDPS,   # handles IIA, VA chapter suffixes
    section_re        = _SECTION_RE_NDPS,   # handles 68-I, 68-O style sections
    section_start_re  = _SECTION_START_RE_NDPS,
)

PCA_ADAPTER = ActAdapter(
    act_code          = "PCA",
    act_full_name     = "THE PREVENTION OF CORRUPTION ACT, 1988",
    body_start_page   = 4,          # 0-indexed; pages 1-4 are TOC + amending acts list
    chapter_re        = _CHAPTER_RE_STD,
    section_re        = _SECTION_RE_STD,
    section_start_re  = _SECTION_START_RE_STD,
)

# ---------------------------------------------------------------------------
# Registry — iterable list for main.py
# ---------------------------------------------------------------------------
NEW_ACT_ADAPTERS = [
    IT_ADAPTER,
    JJA_ADAPTER,
    POCSO_ADAPTER,
    NDPS_ADAPTER,
    PCA_ADAPTER,
]

# PDF filename mapping (relative to source_documents/)
PDF_FILENAMES = {
    "IT":    "THE INFORMATION TECHNOLOGY ACT, 2000.pdf",
    "JJA":   "THE JUVENILE JUSTICE (CARE AND PROTECTION OF CHILDREN) ACT, 2015.pdf",
    "POCSO": "THE PROTECTION OF CHILDREN FROM SEXUAL OFFENCES ACT, 2012.pdf",
    "NDPS":  "The Narcotic Drugs and Psychotropic Substances Act, 1985.pdf",
    "PCA":   "The Prevention of Corruption Act, 1988.pdf",
}
