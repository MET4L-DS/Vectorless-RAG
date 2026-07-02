import os
import re
import hashlib
import json
import fitz
import pandas as pd

# Regular expressions
XREF_INTERNAL_RE = re.compile(r'\bsection\s+(\d+[A-Za-z]?)\b', re.IGNORECASE)
XREF_CROSSACT_RE = re.compile(
    r'\bsection\s+(\d+[A-Za-z]?)\s+of\s+(?:the\s+)?'
    r'(Bharatiya Nyaya Sanhita|Bharatiya Nagarik Suraksha Sanhita|'
    r'Bharatiya Sakshya Adhiniyam|BNS|BNSS|BSA)',
    re.IGNORECASE,
)

class SOPParser:
    def __init__(self, pdf_path: str):
        self.act_code = "SOP"
        self.pdf_path = pdf_path
        
    def parse_sop_index(self, doc) -> list[dict]:
        """
        Parses pages 8, 9, and 10 of the PDF to extract index items,
        handling multi-line topics and mapping printed page numbers to PDF pages.
        """
        raw_lines = []
        for p_idx in [7, 8, 9]:
            page = doc[p_idx]
            blocks = page.get_text('dict')['blocks']
            spans = []
            for b in blocks:
                if 'lines' in b:
                    for l in b['lines']:
                        for s in l['spans']:
                            txt = s['text'].strip()
                            if txt:
                                # Exclude footer at the bottom (y > 765)
                                y = (s['bbox'][1] + s['bbox'][3]) / 2
                                if y > 765:
                                    continue
                                spans.append({
                                    'text': txt,
                                    'bbox': s['bbox']
                                })
                                
            # Group spans by y coordinate (with 4.0 tolerance)
            lines_dict = {}
            for s in spans:
                y = (s['bbox'][1] + s['bbox'][3]) / 2
                found = False
                for ly in lines_dict:
                    if abs(ly - y) < 4.0:
                        lines_dict[ly].append(s)
                        found = True
                        break
                if not found:
                    lines_dict[y] = [s]
                    
            sorted_y = sorted(lines_dict.keys())
            for y in sorted_y:
                line_spans = lines_dict[y]
                line_spans.sort(key=lambda s: s['bbox'][0])
                
                # Segment spans into topic parts and page parts based on x coordinate (threshold 440)
                topic_spans = [s for s in line_spans if s['bbox'][0] < 440]
                page_spans = [s for s in line_spans if s['bbox'][0] >= 440]
                
                topic_text = ' '.join([s['text'] for s in topic_spans]).strip()
                page_text = ' '.join([s['text'] for s in page_spans]).strip()
                
                if not topic_text or topic_text == 'INDEX' or topic_text == 'Sl.No. TOPIC':
                    continue
                raw_lines.append((topic_text, page_text))

        index_items = []
        current_item = None

        for topic_text, page_text in raw_lines:
            m = re.match(r'^(\d+)\.\s*(.*)', topic_text)
            if m:
                if current_item:
                    index_items.append(current_item)
                sl_no = int(m.group(1))
                topic = m.group(2).strip()
                current_item = {
                    'sl_no': sl_no,
                    'topic': topic,
                    'page_str': page_text
                }
            else:
                if current_item:
                    current_item['topic'] += ' ' + topic_text
                    if page_text and not current_item['page_str']:
                        current_item['page_str'] = page_text

        if current_item:
            index_items.append(current_item)

        # Parse start/end page numbers (printed pages + 10 = PDF 1-indexed page)
        for item in index_items:
            topic = item['topic']
            topic = re.sub(r'[\s\u200b\u00a0\ufffd]+', ' ', topic).strip()
            item['topic'] = topic
            
            page_str = item['page_str']
            page_str = re.sub(r'[\s\u200b\u00a0\ufffd]+', ' ', page_str).strip()
            
            m_range = re.match(r'^(\d+)\s*[\-–—to\s]+\s*(\d+)$', page_str)
            if m_range:
                item['start_page'] = int(m_range.group(1))
                item['end_page'] = int(m_range.group(2))
            else:
                m_single = re.match(r'^(\d+)$', page_str)
                if m_single:
                    item['start_page'] = int(m_single.group(1))
                    item['end_page'] = int(m_single.group(1))
                else:
                    item['start_page'] = None
                    item['end_page'] = None
                    
        return index_items

    def extract_xrefs(self, text: str) -> list:
        """
        Extracts cross-references to BNS/BNSS/BSA from text.
        Plain internal 'Section X' references inside SOP map to BNSS.
        """
        xrefs = []
        cross_matches = XREF_CROSSACT_RE.findall(text)
        for num, act in cross_matches:
            act_clean = act.lower()
            if "nyaya" in act_clean or "bns" == act_clean:
                target = f"BNS_S{num}"
            elif "nagarik" in act_clean or "bnss" == act_clean:
                target = f"BNSS_S{num}"
            elif "sakshya" in act_clean or "bsa" == act_clean:
                target = f"BSA_S{num}"
            else:
                target = f"{act.upper()}_S{num}"
            xrefs.append(target)
            
        internal_matches = XREF_INTERNAL_RE.findall(text)
        for num in internal_matches:
            already_in_cross = False
            for target in xrefs:
                if target.endswith(f"_S{num}"):
                    already_in_cross = True
                    break
            if not already_in_cross:
                target = f"BNSS_S{num}"
                xrefs.append(target)
                
        return list(set(xrefs))

    def parse(self):
        doc = fitz.open(self.pdf_path)
        
        pages_data = []
        lines_data = []
        toc_nodes = []
        
        # 1. Parse Index
        index_items = self.parse_sop_index(doc)
        
        # 2. Add root node
        root_id = "SOP_root"
        toc_nodes.append({
            "section_id": root_id,
            "act_code": self.act_code,
            "level": 0,
            "parent_id": None,
            "title": "Standard Operating Procedures (SOP) for Police Officers",
            "chapter_no": None,
            "section_no": None,
            "start_page": 1,
            "end_page": len(doc),
            "node_type": "root",
            "cross_references": json.dumps([]),
            "stable_hash": hashlib.sha1(root_id.encode()).hexdigest()
        })
        
        # 3. Add front-matter node
        front_matter_id = "SOP_front_matter"
        toc_nodes.append({
            "section_id": front_matter_id,
            "act_code": self.act_code,
            "level": 1,
            "parent_id": root_id,
            "title": "Front Matter (Preface, Messages, and Index)",
            "chapter_no": None,
            "section_no": None,
            "start_page": 1,
            "end_page": 10,
            "node_type": "front_matter",
            "cross_references": json.dumps([]),
            "stable_hash": hashlib.sha1(front_matter_id.encode()).hexdigest()
        })
        
        # 4. Add SOP nodes from parsed index
        for item in index_items:
            sl_no = item['sl_no']
            topic = item['topic']
            start_p = item['start_page'] + 10 if item['start_page'] is not None else 11
            end_p = item['end_page'] + 10 if item['end_page'] is not None else 11
            
            section_id = f"SOP_S{sl_no}"
            
            # Map node type
            if sl_no == 44:
                node_type = "sop_form"
            elif sl_no == 45:
                node_type = "sop_reference"
            elif sl_no == 47:
                node_type = "sop_table"
            else:
                node_type = "sop_procedure"
                
            toc_nodes.append({
                "section_id": section_id,
                "act_code": self.act_code,
                "level": 1,
                "parent_id": root_id,
                "title": topic,
                "chapter_no": None,
                "section_no": str(sl_no),
                "start_page": start_p,
                "end_page": end_p,
                "node_type": node_type,
                "cross_references": json.dumps([]), # Will update after line parsing
                "stable_hash": hashlib.sha1(section_id.encode()).hexdigest()
            })
            
        global_line_counter = 1
        
        # 5. Extract pages and lines
        for p_idx in range(len(doc)):
            page = doc[p_idx]
            page_no = p_idx + 1
            
            page_text_raw = page.get_text()
            
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
                                
            # Sort spans top-to-bottom, left-to-right
            spans.sort(key=lambda s: (round(s["bbox"][1], 1), s["bbox"][0]))
            
            # Group spans into lines
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
            
            cleaned_lines = []
            header_text = None
            footer_text = None
            
            for idx, y_val in enumerate(sorted_y):
                line_spans = lines_dict[y_val]
                line_spans.sort(key=lambda s: s["bbox"][0])
                
                dominant_span = max(line_spans, key=lambda s: len(s["text"]))
                font_name = dominant_span["font"]
                font_size = round(dominant_span["size"], 1)
                is_bold = "Bold" in font_name or dominant_span["flags"] & 2 > 0
                
                line_text = " ".join([s["text"] for s in line_spans]).strip()
                
                line_bbox = (
                    min(s["bbox"][0] for s in line_spans),
                    min(s["bbox"][1] for s in line_spans),
                    max(s["bbox"][2] for s in line_spans),
                    max(s["bbox"][3] for s in line_spans)
                )
                
                # Check for footer page noise
                y_center = (line_bbox[1] + line_bbox[3]) / 2
                if y_center > 765:
                    if "| P a g e" in line_text or re.search(r'^\d+$', line_text):
                        footer_text = line_text
                        continue
                        
                cleaned_lines.append({
                    "text": line_text,
                    "bbox": line_bbox,
                    "font_name": font_name,
                    "font_size": font_size,
                    "is_bold": is_bold
                })
                
            pages_data.append({
                "act_code": self.act_code,
                "page_no": page_no,
                "page_text_raw": page_text_raw,
                "header_text": header_text,
                "footer_text": footer_text
            })
            
            # Map lines to TOC nodes
            assigned_section_id = "SOP_root"
            if page_no <= 10:
                assigned_section_id = "SOP_front_matter"
            else:
                for item in index_items:
                    start_p = item["start_page"] + 10 if item["start_page"] is not None else 11
                    end_p = item["end_page"] + 10 if item["end_page"] is not None else 11
                    if start_p <= page_no <= end_p:
                        assigned_section_id = f"SOP_S{item['sl_no']}"
                        break
                # Fallback for page 238 or any unmapped page above page 10
                if assigned_section_id == "SOP_root" and page_no > 10:
                    assigned_section_id = f"SOP_S{index_items[-1]['sl_no']}"
                    
            for line in cleaned_lines:
                lines_data.append({
                    "act_code": self.act_code,
                    "page_no": page_no,
                    "line_no": global_line_counter,
                    "text": line["text"],
                    "bbox": line["bbox"],
                    "font_name": line["font_name"],
                    "font_size": line["font_size"],
                    "is_bold": line["is_bold"],
                    "section_id": assigned_section_id
                })
                global_line_counter += 1
                
        # 6. Extract cross-references per node by scanning lines
        node_xrefs = {}
        for line in lines_data:
            sid = line["section_id"]
            if sid not in node_xrefs:
                node_xrefs[sid] = []
            xrefs = self.extract_xrefs(line["text"])
            node_xrefs[sid].extend(xrefs)
            
        for node in toc_nodes:
            sid = node["section_id"]
            refs = list(set(node_xrefs.get(sid, [])))
            node["cross_references"] = json.dumps(refs)
            
        page_df = pd.DataFrame(pages_data)
        line_df = pd.DataFrame(lines_data)
        toc_df = pd.DataFrame(toc_nodes)
        schedule_df = pd.DataFrame()
        
        return page_df, line_df, toc_df, schedule_df
