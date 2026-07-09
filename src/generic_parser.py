"""
src/generic_parser.py
---------------------
A configurable PDF parser for Indian statutes using per-act adapter configs.
Reuses the same coordinate-based layout logic as parser.py, but accepts
an ActAdapter dataclass to configure act-specific regexes, page offsets, and metadata.

Acts supported: IT, JJA, POCSO, NDPS, PCA (and any future additions).
"""

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Optional

import fitz
import pandas as pd

# ---------------------------------------------------------------------------
# Shared regex patterns (same as parser.py)
# ---------------------------------------------------------------------------
PAGE_NUM_NOISE_RE = re.compile(r"^\d{1,3}$")

# Cross-reference patterns: updated to recognise all 8 corpora
XREF_CROSSACT_RE = re.compile(
    r"\bsection\s+(\d+[A-Za-z]?)\s+of\s+(?:the\s+)?"
    r"(Bharatiya Nyaya Sanhita|Bharatiya Nagarik Suraksha Sanhita|"
    r"Bharatiya Sakshya Adhiniyam|BNS|BNSS|BSA|"
    r"Information Technology Act|IT Act|"
    r"Juvenile Justice|JJ Act|"
    r"Protection of Children|POCSO|"
    r"Narcotic Drugs|NDPS|"
    r"Prevention of Corruption|PCA)",
    re.IGNORECASE,
)
XREF_INTERNAL_RE = re.compile(r"\bsection\s+(\d+[A-Za-z]?)\b", re.IGNORECASE)

# Mapping of cross-act name fragments to act codes
_XREF_ACT_MAP = {
    "nyaya":                "BNS",
    "bns":                  "BNS",
    "nagarik":              "BNSS",
    "bnss":                 "BNSS",
    "sakshya":              "BSA",
    "bsa":                  "BSA",
    "information technolog": "IT",
    "it act":               "IT",
    "juvenile justice":     "JJA",
    "jj act":               "JJA",
    "protection of children":"POCSO",
    "pocso":                "POCSO",
    "narcotic":             "NDPS",
    "ndps":                 "NDPS",
    "prevention of corruption":"PCA",
    "pca":                  "PCA",
}


def _resolve_act_code(act_fragment: str) -> str:
    """Maps a raw act name fragment (from regex capture) to an act code."""
    frag = act_fragment.lower()
    for key, code in _XREF_ACT_MAP.items():
        if key in frag:
            return code
    return act_fragment.upper()[:4]


# ---------------------------------------------------------------------------
# Adapter dataclass
# ---------------------------------------------------------------------------
@dataclass
class ActAdapter:
    """Configuration for a single statutory act's PDF layout."""
    act_code: str
    act_full_name: str
    body_start_page: int          # 0-indexed first body page (skip TOC/preamble)
    chapter_re: re.Pattern        # Matches the roman/arabic chapter heading line
    section_re: re.Pattern        # Matches a section line that includes the em-dash separator
    section_start_re: re.Pattern  # Matches first line of a section (no em-dash required)


# ---------------------------------------------------------------------------
# Generic PDF Parser
# ---------------------------------------------------------------------------
class GenericPDFParser:
    """
    Parses an Indian statute PDF using an ActAdapter config.
    Produces the same four DataFrames as PDFParser.parse():
        page_df, line_df, toc_df, schedule_df (always empty for new acts)
    """

    def __init__(self, adapter: ActAdapter, pdf_path: str):
        self.adapter = adapter
        self.pdf_path = pdf_path

    # ------------------------------------------------------------------
    def parse(self) -> tuple:
        """Return (page_df, line_df, toc_df, schedule_df)."""
        doc = fitz.open(self.pdf_path)
        adapter = self.adapter
        act = adapter.act_code

        pages_data = []
        lines_data = []
        toc_nodes = []

        # ---- Root node ----
        root_id = f"{act}_root"
        toc_nodes.append({
            "section_id":       root_id,
            "act_code":         act,
            "level":            0,
            "parent_id":        None,
            "title":            adapter.act_full_name,
            "chapter_no":       None,
            "section_no":       None,
            "start_page":       1,
            "end_page":         len(doc),
            "node_type":        "root",
            "cross_references": json.dumps([]),
            "stable_hash":      hashlib.sha1(f"{act}_root".encode()).hexdigest(),
        })

        # ---- Front-matter node ----
        front_matter_id = f"{act}_front_matter"
        toc_nodes.append({
            "section_id":       front_matter_id,
            "act_code":         act,
            "level":            1,
            "parent_id":        root_id,
            "title":            "Front Matter (Arrangement of Sections & Preamble)",
            "chapter_no":       None,
            "section_no":       None,
            "start_page":       1,
            "end_page":         adapter.body_start_page,
            "node_type":        "front_matter",
            "cross_references": json.dumps([]),
            "stable_hash":      hashlib.sha1(f"{act}_front_matter".encode()).hexdigest(),
        })

        # ---- State variables ----
        current_chapter_no    = None
        current_chapter_title = None
        current_chapter_id    = None
        current_section_no    = None
        current_section_title = None
        current_section_id    = None
        global_line_counter   = 1

        # ---- Page loop ----
        for p_idx in range(len(doc)):
            page    = doc[p_idx]
            page_no = p_idx + 1

            page_text_raw = page.get_text()
            blocks        = page.get_text("dict")["blocks"]

            spans = []
            for b in blocks:
                if "lines" in b:
                    for l in b["lines"]:
                        for s in l["spans"]:
                            text = s["text"].strip()
                            if text:
                                spans.append({
                                    "text":  text,
                                    "bbox":  s["bbox"],
                                    "font":  s["font"],
                                    "size":  s["size"],
                                    "flags": s["flags"],
                                })

            # Sort spans top-to-bottom, left-to-right
            spans.sort(key=lambda s: (round(s["bbox"][1], 1), s["bbox"][0]))

            # Group into physical lines by Y-centroid proximity
            lines_dict: dict = {}
            for s in spans:
                y = (s["bbox"][1] + s["bbox"][3]) / 2
                matched = False
                for ly in lines_dict:
                    if abs(ly - y) < 3.0:
                        lines_dict[ly].append(s)
                        matched = True
                        break
                if not matched:
                    lines_dict[y] = [s]

            page_lines = []
            for y_val in sorted(lines_dict):
                line_spans = sorted(lines_dict[y_val], key=lambda s: s["bbox"][0])
                dominant   = max(line_spans, key=lambda s: len(s["text"]))
                line_text  = " ".join(s["text"] for s in line_spans).strip()
                line_bbox  = (
                    min(s["bbox"][0] for s in line_spans),
                    min(s["bbox"][1] for s in line_spans),
                    max(s["bbox"][2] for s in line_spans),
                    max(s["bbox"][3] for s in line_spans),
                )
                is_bold = (
                    bool(dominant["flags"] & 2)
                    or "bold" in dominant["font"].lower()
                    or "bd" in dominant["font"].lower()
                )
                page_lines.append({
                    "text":      line_text,
                    "bbox":      line_bbox,
                    "font_name": dominant["font"],
                    "font_size": dominant["size"],
                    "is_bold":   is_bold,
                })

            # Strip lone page-number header/footer
            header_text = None
            footer_text = None
            cleaned_lines = []
            for idx, line in enumerate(page_lines):
                t = line["text"]
                if idx == 0 and PAGE_NUM_NOISE_RE.match(t):
                    header_text = t
                    continue
                if idx == len(page_lines) - 1 and PAGE_NUM_NOISE_RE.match(t):
                    footer_text = t
                    continue
                cleaned_lines.append(line)

            pages_data.append({
                "act_code":      act,
                "page_no":       page_no,
                "page_text_raw": page_text_raw,
                "header_text":   header_text,
                "footer_text":   footer_text,
            })

            is_body_page = p_idx >= adapter.body_start_page
            skip_next_line = False

            for l_idx, line in enumerate(cleaned_lines):
                text = line["text"]
                assigned_section_id = front_matter_id

                if is_body_page:
                    if skip_next_line:
                        skip_next_line = False
                        assigned_section_id = current_chapter_id or front_matter_id
                    else:
                        # ---- Section detection ----
                        sec_match = adapter.section_re.match(text)
                        if not sec_match:
                            start_match = adapter.section_start_re.match(text)
                            if start_match and l_idx + 1 < len(cleaned_lines):
                                next_text   = cleaned_lines[l_idx + 1]["text"].strip()
                                joined_text = text + " " + next_text
                                sec_match   = adapter.section_re.match(joined_text)

                        # ---- Chapter detection ----
                        chap_match = adapter.chapter_re.match(text)

                        if chap_match:
                            current_chapter_no = chap_match.group(1)
                            next_text = ""
                            if l_idx + 1 < len(cleaned_lines):
                                next_text      = cleaned_lines[l_idx + 1]["text"].strip()
                                skip_next_line = True

                            current_chapter_title = next_text
                            current_chapter_id    = f"{act}_C{current_chapter_no}"
                            assigned_section_id   = current_chapter_id

                            toc_nodes.append({
                                "section_id":       current_chapter_id,
                                "act_code":         act,
                                "level":            1,
                                "parent_id":        root_id,
                                "title":            f"CHAPTER {current_chapter_no}: {current_chapter_title}",
                                "chapter_no":       current_chapter_no,
                                "section_no":       None,
                                "start_page":       page_no,
                                "end_page":         page_no,
                                "node_type":        "chapter",
                                "cross_references": json.dumps([]),
                                "stable_hash":      hashlib.sha1(
                                    f"{act}_{current_chapter_id}".encode()
                                ).hexdigest(),
                            })

                        elif sec_match:
                            new_sec_no  = sec_match.group(1)
                            # Normalise section number to integer for monotonic guard
                            new_sec_int = int(re.sub(r"\D", "", new_sec_no)) if re.search(r"\d", new_sec_no) else 0
                            cur_sec_int = (
                                int(re.sub(r"\D", "", current_section_no))
                                if current_section_no and re.search(r"\d", current_section_no) else 0
                            )

                            # Monotonic guard: filter footnotes / backward references
                            if current_section_no and (
                                new_sec_int < cur_sec_int
                                or (new_sec_int == cur_sec_int and new_sec_no == current_section_no)
                            ):
                                assigned_section_id = (
                                    current_section_id or current_chapter_id or front_matter_id
                                )
                            else:
                                current_section_no    = new_sec_no
                                current_section_title = sec_match.group(2)
                                current_section_id    = f"{act}_S{current_section_no}"
                                assigned_section_id   = current_section_id

                                xrefs = self._extract_xrefs(text, act)

                                toc_nodes.append({
                                    "section_id":       current_section_id,
                                    "act_code":         act,
                                    "level":            2,
                                    "parent_id":        current_chapter_id,
                                    "title":            f"{current_section_no}. {current_section_title}",
                                    "chapter_no":       current_chapter_no,
                                    "section_no":       current_section_no,
                                    "start_page":       page_no,
                                    "end_page":         page_no,
                                    "node_type":        "section",
                                    "cross_references": json.dumps(xrefs),
                                    "stable_hash":      hashlib.sha1(
                                        f"{act}_{current_section_id}".encode()
                                    ).hexdigest(),
                                })

                        else:
                            assigned_section_id = (
                                current_section_id or current_chapter_id or front_matter_id
                            )

                lines_data.append({
                    "act_code":    act,
                    "page_no":     page_no,
                    "line_no":     global_line_counter,
                    "text":        text,
                    "bbox":        line["bbox"],
                    "font_name":   line["font_name"],
                    "font_size":   line["font_size"],
                    "is_bold":     line["is_bold"],
                    "section_id":  assigned_section_id,
                })
                global_line_counter += 1

        # ---- Build DataFrames and update end_page dynamically ----
        toc_df = pd.DataFrame(toc_nodes)
        if not toc_df.empty:
            for idx, row in toc_df.iterrows():
                level   = row["level"]
                start_p = row["start_page"]
                next_nodes         = toc_df.iloc[idx + 1:]
                next_same_or_higher = next_nodes[next_nodes["level"] <= level]
                if not next_same_or_higher.empty:
                    end_p = next_same_or_higher.iloc[0]["start_page"]
                    toc_df.at[idx, "end_page"] = max(start_p, end_p - 1)
                else:
                    toc_df.at[idx, "end_page"] = len(doc)

        page_df     = pd.DataFrame(pages_data)
        line_df     = pd.DataFrame(lines_data)
        schedule_df = pd.DataFrame()  # New acts have no special schedule tables

        return page_df, line_df, toc_df, schedule_df

    # ------------------------------------------------------------------
    def _extract_xrefs(self, text: str, current_act: str) -> list:
        xrefs = []
        cross_matches = XREF_CROSSACT_RE.findall(text)
        for num, act_fragment in cross_matches:
            target_act = _resolve_act_code(act_fragment)
            xrefs.append(f"{target_act}_S{num}")

        internal_matches = XREF_INTERNAL_RE.findall(text)
        for num in internal_matches:
            already = any(t.endswith(f"_S{num}") for t in xrefs)
            if not already:
                xrefs.append(f"{current_act}_S{num}")

        return list(set(xrefs))
