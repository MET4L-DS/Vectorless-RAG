import os
import re
import hashlib
import json
import fitz
import pandas as pd

# Define the body start pages (0-indexed) for the three Acts
BODY_START_PAGES = {
    "BNS": 15,
    "BNSS": 15,
    "BSA": 9
}

# Act full names mapping
ACT_NAMES = {
    "BNS": "BHARATIYA NYAYA SANHITA, 2023",
    "BNSS": "BHARATIYA NAGARIK SURAKSHA SANHITA, 2023",
    "BSA": "BHARATIYA SAKSHYA ADHINIYAM, 2023"
}

# Define the First Schedule page range (0-indexed) in BNSS
BNSS_FIRST_SCHEDULE_PAGES = range(172, 219)

CHAPTER_RE = re.compile(r'^CHAPTER\s+([IVXLCM]+)$', re.IGNORECASE)
SECTION_RE = re.compile(r'^(\d{1,3}[A-Z]?)\s*\.\s*(.+?)(?:\s*\.)?\s*[-——–—\u2010-\u2015]\s*', re.IGNORECASE)
SECTION_START_RE = re.compile(r'^(\d{1,3}[A-Z]?)\s*\.\s*(.+)$', re.IGNORECASE)
PAGE_NUM_NOISE_RE = re.compile(r'^\d{1,3}$')

# Cross-reference regular expressions
XREF_INTERNAL_RE = re.compile(r'\bsection\s+(\d+[A-Za-z]?)\b', re.IGNORECASE)
XREF_CROSSACT_RE = re.compile(
    r'\bsection\s+(\d+[A-Za-z]?)\s+of\s+(?:the\s+)?'
    r'(Bharatiya Nyaya Sanhita|Bharatiya Nagarik Suraksha Sanhita|'
    r'Bharatiya Sakshya Adhiniyam|BNS|BNSS|BSA)',
    re.IGNORECASE,
)

class PDFParser:
    def __init__(self, act_code: str, pdf_path: str):
        self.act_code = act_code
        self.pdf_path = pdf_path
        self.body_start_page = BODY_START_PAGES.get(act_code, 0)
        
    def parse(self):
        doc = fitz.open(self.pdf_path)
        
        pages_data = []
        lines_data = []
        toc_nodes = []
        
        # Initialize active parent nodes
        current_chapter_no = None
        current_chapter_title = None
        current_chapter_id = None
        
        current_section_no = None
        current_section_title = None
        current_section_id = None
        
        # Chapter V injection state for BNSS
        injected_chapter_v = False
        
        # 1. Create a root node for the Act
        root_id = f"{self.act_code}_root"
        act_title = ACT_NAMES.get(self.act_code, self.act_code)
        toc_nodes.append({
            "section_id": root_id,
            "act_code": self.act_code,
            "level": 0,
            "parent_id": None,
            "title": act_title,
            "chapter_no": None,
            "section_no": None,
            "start_page": 1,
            "end_page": len(doc),
            "node_type": "root",
            "cross_references": json.dumps([]),
            "stable_hash": hashlib.sha1(f"{self.act_code}_root".encode()).hexdigest()
        })
        
        # 2. Create a default front-matter node in TOC (under the root node)
        front_matter_id = f"{self.act_code}_front_matter"
        toc_nodes.append({
            "section_id": front_matter_id,
            "act_code": self.act_code,
            "level": 1,
            "parent_id": root_id,
            "title": "Front Matter (Arrangement of Sections & Preamble)",
            "chapter_no": None,
            "section_no": None,
            "start_page": 1,
            "end_page": self.body_start_page,
            "node_type": "front_matter",
            "cross_references": json.dumps([]),
            "stable_hash": hashlib.sha1(f"{self.act_code}_front_matter".encode()).hexdigest()
        })
        
        # Track line number globally across the document
        global_line_counter = 1
        
        for p_idx in range(len(doc)):
            page = doc[p_idx]
            page_no = p_idx + 1 # 1-indexed page number
            
            # Extract raw page text
            page_text_raw = page.get_text()
            
            # Retrieve detailed layout dictionary
            blocks = page.get_text("dict")["blocks"]
            spans = []
            for b in blocks:
                if "lines" in b:
                    for l in b["lines"]:
                        for s in l["spans"]:
                            text = s["text"].strip()
                            if text:
                                spans.append({
                                    "text": text,
                                    "bbox": s["bbox"],
                                    "font": s["font"],
                                    "size": s["size"],
                                    "flags": s["flags"]
                                })
            
            # Sort spans top-to-bottom, then left-to-right
            spans.sort(key=lambda s: (round(s["bbox"][1], 1), s["bbox"][0]))
            
            # Group spans into physical lines
            lines_dict = {}
            for s in spans:
                y = (s["bbox"][1] + s["bbox"][3]) / 2
                found = False
                for ly in lines_dict:
                    if abs(ly - y) < 3.0:
                        lines_dict[ly].append(s)
                        found = True
                        break
                if not found:
                    lines_dict[y] = [s]
            
            sorted_y = sorted(lines_dict.keys())
            page_lines = []
            
            for y_val in sorted_y:
                line_spans = lines_dict[y_val]
                line_spans.sort(key=lambda s: s["bbox"][0])
                
                # Find dominant span (longest text span)
                dominant_span = max(line_spans, key=lambda s: len(s["text"]))
                
                # Concatenate span text within the line
                line_text = " ".join(s["text"] for s in line_spans).strip()
                
                # Compute line bounding box enclosing all its spans
                line_bbox = (
                    min(s["bbox"][0] for s in line_spans),
                    min(s["bbox"][1] for s in line_spans),
                    max(s["bbox"][2] for s in line_spans),
                    max(s["bbox"][3] for s in line_spans)
                )
                
                is_bold = bool(dominant_span["flags"] & 2) or "bold" in dominant_span["font"].lower() or "bd" in dominant_span["font"].lower()
                
                page_lines.append({
                    "text": line_text,
                    "bbox": line_bbox,
                    "font_name": dominant_span["font"],
                    "font_size": dominant_span["size"],
                    "is_bold": is_bold
                })
            
            # Running header/footer cleaning:
            # Check if first or last line is a lone page number
            header_text = None
            footer_text = None
            cleaned_lines = []
            
            for idx, line in enumerate(page_lines):
                t = line["text"]
                # Header check (first line)
                if idx == 0 and PAGE_NUM_NOISE_RE.match(t):
                    header_text = t
                    continue
                # Footer check (last line)
                if idx == len(page_lines) - 1 and PAGE_NUM_NOISE_RE.match(t):
                    footer_text = t
                    continue
                cleaned_lines.append(line)
            
            # Save page metadata
            pages_data.append({
                "act_code": self.act_code,
                "page_no": page_no,
                "page_text_raw": page_text_raw,
                "header_text": header_text,
                "footer_text": footer_text
            })
            
            # Process lines for line_df and structure detection
            # Pages before the body start are assigned entirely to front_matter
            is_body_page = p_idx >= self.body_start_page
            
            # Identify if this page falls inside the First Schedule in BNSS
            is_schedule_page = (self.act_code == "BNSS" and p_idx in BNSS_FIRST_SCHEDULE_PAGES)
            
            # Lookahead chapter parsing buffer
            skip_next_line = False
            
            for l_idx, line in enumerate(cleaned_lines):
                text = line["text"]
                
                # Determine which section ID to assign to this line
                assigned_section_id = front_matter_id
                
                if is_body_page and not is_schedule_page:
                    if skip_next_line:
                        skip_next_line = False
                        # This line was part of a chapter title, map it to the active chapter
                        assigned_section_id = current_chapter_id
                    else:
                        # 2. Section Heading Detection
                        sec_match = SECTION_RE.match(text)
                        if not sec_match:
                            start_match = SECTION_START_RE.match(text)
                            if start_match and l_idx + 1 < len(cleaned_lines):
                                next_line_text = cleaned_lines[l_idx + 1]["text"].strip()
                                joined_text = text + " " + next_line_text
                                sec_match = SECTION_RE.match(joined_text)
                        
                        # 3. Chapter Heading Detection
                        chap_match = CHAPTER_RE.match(text)
                        
                        # 4. BNSS Chapter V Injection Heuristic
                        if self.act_code == "BNSS" and not injected_chapter_v and sec_match:
                            s_no = sec_match.group(1)
                            if s_no == "35":
                                # Inject Chapter V node first!
                                injected_chapter_v = True
                                current_chapter_no = "V"
                                current_chapter_title = "ARREST OF PERSONS"
                                current_chapter_id = f"{self.act_code}_C{current_chapter_no}"
                                
                                toc_nodes.append({
                                    "section_id": current_chapter_id,
                                    "act_code": self.act_code,
                                    "level": 1,
                                    "parent_id": root_id,
                                    "title": f"CHAPTER {current_chapter_no}: {current_chapter_title}",
                                    "chapter_no": current_chapter_no,
                                    "section_no": None,
                                    "start_page": page_no,
                                    "end_page": page_no, # Will update dynamically
                                    "node_type": "chapter",
                                    "cross_references": json.dumps([]),
                                    "stable_hash": hashlib.sha1(f"{self.act_code}_{current_chapter_id}".encode()).hexdigest()
                                })
                        
                        if chap_match:
                            current_chapter_no = chap_match.group(1)
                            # Retrieve chapter title from next line
                            next_text = ""
                            if l_idx + 1 < len(cleaned_lines):
                                next_text = cleaned_lines[l_idx + 1]["text"].strip()
                                skip_next_line = True
                            
                            current_chapter_title = next_text
                            current_chapter_id = f"{self.act_code}_C{current_chapter_no}"
                            assigned_section_id = current_chapter_id
                            
                            # Add chapter node
                            toc_nodes.append({
                                "section_id": current_chapter_id,
                                "act_code": self.act_code,
                                "level": 1,
                                "parent_id": root_id,
                                "title": f"CHAPTER {current_chapter_no}: {current_chapter_title}",
                                "chapter_no": current_chapter_no,
                                "section_no": None,
                                "start_page": page_no,
                                "end_page": page_no,
                                "node_type": "chapter",
                                "cross_references": json.dumps([]),
                                "stable_hash": hashlib.sha1(f"{self.act_code}_{current_chapter_id}".encode()).hexdigest()
                            })
                            
                        elif sec_match:
                            new_sec_no = sec_match.group(1)
                            new_sec_int = int(re.sub(r'\D', '', new_sec_no))
                            current_sec_int = int(re.sub(r'\D', '', current_section_no)) if current_section_no else 0
                            
                            # Filter out footnotes and duplicate Object & Reasons entries
                            if current_section_no and (new_sec_int < current_sec_int or (new_sec_int == current_sec_int and new_sec_no == current_section_no)):
                                # Treat as normal body line
                                assigned_section_id = current_section_id or current_chapter_id or front_matter_id
                            else:
                                current_section_no = new_sec_no
                                current_section_title = sec_match.group(2)
                                current_section_id = f"{self.act_code}_S{current_section_no}"
                                assigned_section_id = current_section_id
                                
                                # Extract cross-references in the body text of the section title or inline text
                                xrefs = self.extract_xrefs(text)
                                
                                # Add section node
                                toc_nodes.append({
                                    "section_id": current_section_id,
                                    "act_code": self.act_code,
                                    "level": 2,
                                    "parent_id": current_chapter_id,
                                    "title": f"{current_section_no}. {current_section_title}",
                                    "chapter_no": current_chapter_no,
                                    "section_no": current_section_no,
                                    "start_page": page_no,
                                    "end_page": page_no,
                                    "node_type": "section",
                                    "cross_references": json.dumps(xrefs),
                                    "stable_hash": hashlib.sha1(f"{self.act_code}_{current_section_id}".encode()).hexdigest()
                                })
                            
                        else:
                            # Standard body lines belong to the active section (or chapter if before first section)
                            assigned_section_id = current_section_id or current_chapter_id or front_matter_id
                
                elif is_schedule_page:
                    # Lines inside the schedule page are mapped to a generic schedule node
                    assigned_section_id = f"{self.act_code}_SCH1"
                
                # Append line record
                lines_data.append({
                    "act_code": self.act_code,
                    "page_no": page_no,
                    "line_no": global_line_counter,
                    "text": text,
                    "bbox": line["bbox"],
                    "font_name": line["font_name"],
                    "font_size": line["font_size"],
                    "is_bold": line["is_bold"],
                    "section_id": assigned_section_id
                })
                global_line_counter += 1
                
        # 5. Build trees & update end pages dynamically
        toc_df = pd.DataFrame(toc_nodes)
        if not toc_df.empty:
            # Dynamically set end_page to the start_page of the next node of the same or higher level - 1
            for idx, row in toc_df.iterrows():
                level = row["level"]
                start_p = row["start_page"]
                # Find the next node that has level <= row's level
                next_nodes = toc_df.iloc[idx+1:]
                next_same_or_higher = next_nodes[next_nodes["level"] <= level]
                if not next_same_or_higher.empty:
                    end_p = next_same_or_higher.iloc[0]["start_page"]
                    # If same page, end page is same. Else, end page is next start page - 1
                    toc_df.at[idx, "end_page"] = max(start_p, end_p - 1)
                else:
                    # Last node goes to end of document
                    toc_df.at[idx, "end_page"] = len(doc)
                    
        # We also need to add a node for the Schedule in BNSS's TOC
        if self.act_code == "BNSS":
            schedule_id = "BNSS_SCH1"
            toc_df = pd.concat([toc_df, pd.DataFrame([{
                "section_id": schedule_id,
                "act_code": "BNSS",
                "level": 1,
                "parent_id": "BNSS_root",
                "title": "THE FIRST SCHEDULE (Classification of Offences)",
                "chapter_no": None,
                "section_no": None,
                "start_page": min(BNSS_FIRST_SCHEDULE_PAGES) + 1,
                "end_page": max(BNSS_FIRST_SCHEDULE_PAGES) + 1,
                "node_type": "schedule",
                "cross_references": json.dumps([]),
                "stable_hash": hashlib.sha1(b"BNSS_SCH1").hexdigest()
            }])], ignore_index=True)
            
        page_df = pd.DataFrame(pages_data)
        line_df = pd.DataFrame(lines_data)
        
        # 6. Extract the Schedule DataFrame if BNSS
        schedule_df = pd.DataFrame()
        if self.act_code == "BNSS":
            schedule_df = self.parse_bnss_schedule(doc)
            
        return page_df, line_df, toc_df, schedule_df

    def extract_xrefs(self, text: str) -> list:
        xrefs = []
        # Find cross-act references
        cross_matches = XREF_CROSSACT_RE.findall(text)
        for num, act in cross_matches:
            # Map full act names to short codes
            act_clean = act.lower()
            if "nyaya" in act_clean or "bns" == act_clean:
                target = f"BNS_S{num}"
            elif "nagarik" in act_clean or "bnss" == act_clean:
                target = f"BNSS_S{num}"
            elif "sakshya" in act_clean or "bsa" == act_clean:
                target = f"BSA_S{num}"
            else:
                target = f"{act}_S{num}"
            xrefs.append(target)
            
        # Find internal references (not caught in cross-act references)
        # Avoid matches that were already part of cross-act matches by checking if text matches both
        # A simple check: only add internal match if the numbers aren't already included in cross_matches targets
        internal_matches = XREF_INTERNAL_RE.findall(text)
        for num in internal_matches:
            # Check if this num was already resolved to a cross-act target
            already_in_cross = False
            for target in xrefs:
                if target.endswith(f"_S{num}"):
                    already_in_cross = True
                    break
            if not already_in_cross:
                target = f"{self.act_code}_S{num}"
                xrefs.append(target)
                
        return list(set(xrefs))

    def parse_bnss_schedule(self, doc) -> pd.DataFrame:
        all_rows = []
        for p_idx in BNSS_FIRST_SCHEDULE_PAGES:
            page = doc[p_idx]
            page_no = p_idx + 1
            blocks = page.get_text("dict")["blocks"]
            
            # Extract raw spans
            spans = []
            for b in blocks:
                if "lines" in b:
                    for l in b["lines"]:
                        for s in l["spans"]:
                            text = s["text"].strip()
                            if text:
                                spans.append({
                                    "text": text,
                                    "bbox": s["bbox"],
                                    "x_center": (s["bbox"][0] + s["bbox"][2]) / 2,
                                    "y0": s["bbox"][1],
                                    "y1": s["bbox"][3]
                                })
            
            # Filter page noise and table headers
            clean_spans = []
            for s in spans:
                t = s["text"]
                if t.isdigit() and len(t) <= 3 and s["y0"] < 80:
                    continue
                if any(w in t for w in ["THE FIRST SCHEDULE", "CLASSIFICATION OF OFFENCES", "EXPLANATORY NOTES", "I.--OFFENCES", "Section Offence", "Punishment"]):
                    continue
                clean_spans.append(s)
                
            if not clean_spans:
                continue
                
            is_part_ii = any("AGAINST OTHER LAWS" in s["text"] for s in clean_spans)
            
            # Column mapping
            for s in clean_spans:
                xc = s["x_center"]
                if is_part_ii:
                    # Part II: 4 columns
                    if xc < 250:
                        col = 2 # Offence
                    elif xc < 330:
                        col = 4 # Cognizable
                    elif xc < 400:
                        col = 5 # Bailable
                    else:
                        col = 6 # Court
                else:
                    # Part I: 6 columns
                    if xc < 105:
                        col = 1 # Section
                    elif xc < 222:
                        col = 2 # Offence
                    elif xc < 290:
                        col = 3 # Punishment
                    elif xc < 365:
                        col = 4 # Cognizable
                    elif xc < 450:
                        col = 5 # Bailable
                    else:
                        col = 6 # Court
                s["col"] = col
                
            # Group by y_center into physical lines (tolerance of 3 points)
            lines_dict = {}
            for s in clean_spans:
                y = (s["y0"] + s["y1"]) / 2
                found = False
                for ly in lines_dict:
                    if abs(ly - y) < 3.0:
                        lines_dict[ly].append(s)
                        found = True
                        break
                if not found:
                    lines_dict[y] = [s]
                    
            sorted_y = sorted(lines_dict.keys())
            lines = []
            
            def is_header_line(cols):
                c1, c2, c3, c4, c5, c6 = [cols[i].strip() for i in range(1, 7)]
                if all(c in ["1", "2", "3", "4", "5", "6", ""] for c in [c1, c2, c3, c4, c5, c6]):
                    if any([c1, c2, c3, c4, c5, c6]):
                        return True
                words = ["Section", "Offence", "Punishment", "Cognizable", "Bailable", "Court", "triable", "non-cognizable", "bailable", "non-bailable"]
                has_content = False
                all_header = True
                for c in [c1, c2, c3, c4, c5, c6]:
                    if c:
                        has_content = True
                        if not any(w.lower() in c.lower() for w in words):
                            all_header = False
                            break
                return has_content and all_header
                
            for y in sorted_y:
                col_texts = {1: "", 2: "", 3: "", 4: "", 5: "", 6: ""}
                line_spans = lines_dict[y]
                line_spans.sort(key=lambda s: s["bbox"][0])
                for s in line_spans:
                    c = s["col"]
                    if col_texts[c]:
                        col_texts[c] += " " + s["text"]
                    else:
                        col_texts[c] = s["text"]
                if is_header_line(col_texts):
                    continue
                lines.append({
                    "y": y,
                    "cols": col_texts
                })
                
            # Assemble physical lines into logical table rows
            page_rows = []
            current_row = None
            table_started = (p_idx != 172)
            
            for line in lines:
                c1 = line["cols"][1].strip()
                c2 = line["cols"][2].strip()
                c3 = line["cols"][3].strip()
                c4 = line["cols"][4].strip()
                c5 = line["cols"][5].strip()
                c6 = line["cols"][6].strip()
                
                if not table_started:
                    if c1 and any(ch.isdigit() for ch in c1):
                        table_started = True
                    else:
                        continue
                        
                starts_new = False
                if is_part_ii:
                    if c2.startswith("If ") or (c4 and c5):
                        starts_new = True
                else:
                    c4_clean = c4.strip()
                    c5_clean = c5.strip()
                    
                    # Case-sensitive checks for first letter capitalization of keywords
                    def is_start_word(text, starts_list):
                        if not text:
                            return False
                        if not text[0].isupper():
                            return False
                        text_lower = text.lower()
                        return any(text_lower.startswith(p) for p in starts_list)
                        
                    has_cog = is_start_word(c4_clean, ["cognizable", "non-cognizable", "according"])
                    has_bail = is_start_word(c5_clean, ["bailable", "non-bailable", "according"])
                    
                    if has_cog and has_bail:
                        starts_new = True
                        
                    if c1 and any(ch.isdigit() for ch in c1):
                        if not starts_new:
                            if current_row is not None and current_row["section"] == "":
                                current_row["section"] = c1
                            else:
                                starts_new = True
                        else:
                            pass
                            
                if starts_new:
                    if current_row:
                        page_rows.append(current_row)
                    current_row = {
                        "page_no": page_no,
                        "section": c1,
                        "offence": c2,
                        "punishment": c3,
                        "cognizable": c4,
                        "bailable": c5,
                        "court": c6
                    }
                else:
                    if current_row is None:
                        current_row = {
                            "page_no": page_no,
                            "section": c1,
                            "offence": c2,
                            "punishment": c3,
                            "cognizable": c4,
                            "bailable": c5,
                            "court": c6
                        }
                    else:
                        # Append content ensuring no duplicate section mappings
                        for col_idx, text in line["cols"].items():
                            key_map = {1: "section", 2: "offence", 3: "punishment", 4: "cognizable", 5: "bailable", 6: "court"}
                            key = key_map[col_idx]
                            if text:
                                if col_idx == 1 and current_row[key] == text.strip():
                                    continue
                                if current_row[key]:
                                    current_row[key] += " " + text
                                else:
                                    current_row[key] = text
            if current_row:
                page_rows.append(current_row)
            all_rows.extend(page_rows)
            
        # Post-process schedule rows to clean up and split merged cells
        schedule_df = pd.DataFrame(all_rows)
        if not schedule_df.empty:
            schedule_df["act_code"] = "BNSS"
            for col in ["section", "offence", "punishment", "cognizable", "bailable", "court"]:
                schedule_df[col] = schedule_df[col].astype(str).str.strip().replace("nan", "")
                
            schedule_df["section"] = schedule_df["section"].replace("", None).ffill()
            
            for idx, row in schedule_df.iterrows():
                cog = row["cognizable"]
                bail = row["bailable"]
                
                merged_text = None
                if "Cognizable" in bail and "Court" in bail:
                    merged_text = bail
                elif "Cognizable" in cog and "Court" in cog:
                    merged_text = cog
                    
                if merged_text:
                    parts = [p.strip() for p in merged_text.split(".") if p.strip()]
                    if len(parts) >= 3:
                        schedule_df.at[idx, "cognizable"] = parts[0]
                        schedule_df.at[idx, "bailable"] = parts[1]
                        schedule_df.at[idx, "court"] = ".".join(parts[2:])
                    elif len(parts) == 2:
                        schedule_df.at[idx, "cognizable"] = parts[0]
                        schedule_df.at[idx, "bailable"] = parts[1]
                        
        return schedule_df
