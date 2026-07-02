import os
import json
import asyncio
import itertools
import time
import pandas as pd
from dotenv import load_dotenv
from google import genai

load_dotenv(override=True)

# Initialize API client
api_key = os.getenv("GOOGLE_API_KEY")
client = None
if api_key:
    client = genai.Client(api_key=api_key)
else:
    print("Warning: GOOGLE_API_KEY is not set in environment.")

MODELS = ["models/gemma-4-26b-a4b-it", "models/gemma-4-31b-it"]
MIN_INTERVAL = 6.0  # 6 seconds between calls to same model (= 10 RPM safety pace)

model_next_allowed_time = {m: 0.0 for m in MODELS}
model_locks = {m: asyncio.Lock() for m in MODELS}
model_cycle = itertools.cycle(MODELS)

# Metrics tracking
new_calls_count = 0
model_calls_tracker = {m: 0 for m in MODELS}

async def call_model(prompt: str) -> str:
    """
    Alternates between Gemma models and enforces 15 RPM per model rate limits
    using an async leaky bucket slot reservation system.
    """
    global new_calls_count
    model_name = next(model_cycle)
    
    async with model_locks[model_name]:
        now = asyncio.get_event_loop().time()
        target_time = max(now, model_next_allowed_time[model_name])
        delay = target_time - now
        model_next_allowed_time[model_name] = target_time + MIN_INTERVAL

    # Wait outside the lock so other tasks can reserve their slots concurrently
    if delay > 0:
        await asyncio.sleep(delay)
        
    if not client:
        raise ValueError("Google GenAI client is not configured (missing GOOGLE_API_KEY).")
    
    # Call SDK in executor thread
    response = await asyncio.to_thread(
        lambda: client.models.generate_content(model=model_name, contents=prompt)
    )
    
    model_calls_tracker[model_name] += 1
    new_calls_count += 1
    return response.text.strip()

def extract_final_summary(text: str) -> str:
    """
    Extracts only the final summary paragraph from Gemma's output,
    ignoring thinking process, scratchpads, and bullet points.
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    if not paragraphs:
        return ""
    for p in reversed(paragraphs):
        p_clean = p.replace("```", "").strip()
        if not p_clean:
            continue
        # Skip markdown lists or analysis steps
        if p_clean.startswith(("*", "-", "1.", "2.", "3.", "Sentence ", "Draft ", "Option ", "Check ", "Topic:", "Source:", "Task:", "Constraint ")):
            continue
        if len(p_clean) > 80:
            return p_clean
    return paragraphs[-1].replace("```", "").strip()

async def call_model_with_retry(prompt: str, retries=5) -> str:
    """
    Helper with retry and exponential backoff, handling rate limits specifically.
    """
    for attempt in range(retries):
        try:
            raw_text = await call_model(prompt)
            return extract_final_summary(raw_text)
        except Exception as e:
            err_msg = str(e)
            print(f"Error calling model (attempt {attempt+1}/{retries}): {e}")
            if "429" in err_msg or "Quota" in err_msg or "ResourceExhausted" in err_msg:
                backoff = 35 + (attempt * 15)
                print(f"Rate limit (429) hit. Backing off for {backoff} seconds...")
                await asyncio.sleep(backoff)
            else:
                await asyncio.sleep(2 ** attempt + 5)
            if attempt == retries - 1:
                raise e

# Cache Management
CACHE_FILE = "tree/summary_cache.json"
summary_cache = {}

def load_cache():
    global summary_cache
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                summary_cache = json.load(f)
            print(f"Loaded {len(summary_cache)} summaries from cache.")
        except Exception as e:
            print(f"Error loading cache: {e}. Starting fresh.")
            summary_cache = {}
    else:
        summary_cache = {}

def save_cache():
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(summary_cache, f, indent=2, ensure_ascii=False)

def format_schedule_row_summary(node):
    """
    Auto-formats a one-line summary for schedule rows without LLM calls.
    """
    content = node.get("content", "")
    lines = content.split("\n")
    data = {}
    for line in lines:
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip().lower()] = v.strip()
            
    section = data.get("section", "N/A")
    offence = data.get("offence", "N/A")
    punishment = data.get("punishment", "N/A")
    
    offence_summary = offence[:80] + "..." if len(offence) > 80 else offence
    punishment_summary = punishment[:60] + "..." if len(punishment) > 60 else punishment
    return f"Section {section}: {offence_summary} — {punishment_summary}"

def chunk_text(text, max_chars=14000):
    """
    Groups paragraphs to stay safely under token limits, preserving paragraph integrity.
    """
    paragraphs = text.split("\n")
    chunks = []
    current_chunk = []
    current_len = 0
    for para in paragraphs:
        para_len = len(para)
        if current_len + para_len > max_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [para]
            current_len = para_len
        else:
            current_chunk.append(para)
            current_len += para_len + 1
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks

ACT_FULL_NAMES = {
    "BNS": "Bharatiya Nyaya Sanhita, 2023",
    "BNSS": "Bharatiya Nagarik Suraksha Sanhita, 2023",
    "BSA": "Bharatiya Sakshya Adhiniyam, 2023",
    "SOP": "Telangana Police Standard Operating Procedures"
}

def get_leaf_prompt(act_code, section_no, title, content, node_id):
    act_name = ACT_FULL_NAMES.get(act_code, act_code)
    
    special_instruction = ""
    if node_id == "BNSS_S193":
        special_instruction = (
            "\nNote: This section may reference other BNS sections without incorporating their definitions. "
            "Do NOT describe referenced BNS sections as if they are defined inside this section.\n"
        )
        
    if act_code == "SOP":
        return f"""You are a precise legal procedure summarizer for Indian police officers. Summarize the following Standard Operating Procedure of the {act_name} in 2–4 sentences.

Rules:
- Make the summary highly keyword-rich and dense, preserving all specific procedural steps, officer roles, timelines, and required actions.
- Preserve exact numbers, timelines (e.g. days, hours), and forms verbatim.
- If it references specific sections of BNSS, BNS, or BSA, name them explicitly.
- Do not add interpretation or inference beyond what is stated.

SOP {section_no}. {title}:
{content}"""

    return f"""You are a precise legal summarizer. Summarize the following section of the {act_name} in 2–4 sentences.

Rules:
- Make the summary highly keyword-rich and dense, preserving all specific legal concepts, offences, actors, and mechanisms mentioned.
- Preserve exact numbers, thresholds, punishment durations, and defined terms verbatim.
- Do not paraphrase numeric penalties (e.g., "not less than seven years" must not become "several years").
- Do not add interpretation or inference beyond what is stated.
- If the section contains Provisos, Exceptions, or Explanations, mention them explicitly.{special_instruction}

Section {section_no}. {title}:
{content}"""

async def summarize_section(node):
    """
    Summarizes a single section (leaf) node, supporting caching and chunked fallback.
    """
    node_id = node["node_id"]
    stable_hash = node["metadata"]["stable_hash"]
    cache_key = f"{node_id}:{stable_hash}"
    
    if cache_key in summary_cache:
        node["summary"] = extract_final_summary(summary_cache[cache_key])
        return
        
    act_code = node["metadata"]["act_code"]
    title = node["title"]
    content = node.get("content", "")
    
    # Extract section number from title
    section_no = node_id.split("_S")[-1] if "_S" in node_id else ""
    
    # Check if we need chunked fallback
    est_tokens = node["metadata"]["token_estimate"]
    try:
        if est_tokens > 4000:
            print(f"[{node_id}] Content is very long ({est_tokens} est. tokens). Running chunked summarization fallback...")
            chunks = chunk_text(content)
            chunk_summaries = []
            for idx, chunk in enumerate(chunks):
                chunk_prompt = get_leaf_prompt(act_code, f"{section_no} (Part {idx+1})", title, chunk, node_id)
                summary = await call_model_with_retry(chunk_prompt)
                chunk_summaries.append(summary)
                
            # Merge summaries
            merged_content = "\n\n".join(chunk_summaries)
            merge_prompt = f"""You are a precise legal summarizer. The following are summaries of different parts of Section {section_no} of the {act_code} ({title}).
Combine them into a single, cohesive, keyword-dense summary of 2-4 sentences.

Part summaries:
{merged_content}"""
            final_summary = await call_model_with_retry(merge_prompt)
        else:
            prompt = get_leaf_prompt(act_code, section_no, title, content, node_id)
            final_summary = await call_model_with_retry(prompt)
    except Exception as e:
        print(f"\nCRITICAL WARNING: Failed to summarize leaf {node_id}: {e}. Using fallback snippet.")
        snippet = content[:180].strip() if content else ""
        final_summary = f"Summary of Section {section_no or title}: {snippet}..."
        
    summary_cache[cache_key] = final_summary
    node["summary"] = final_summary
    save_cache()

async def summarize_schedule_chapter(node):
    """
    Summarizes the First Schedule chapter node (non-leaf description).
    """
    node_id = node["node_id"]
    stable_hash = node["metadata"]["stable_hash"]
    cache_key = f"{node_id}:{stable_hash}"
    
    if cache_key in summary_cache:
        node["summary"] = extract_final_summary(summary_cache[cache_key])
        return
        
    prompt = """Summarize the First Schedule of the Bharatiya Nagarik Suraksha Sanhita, 2023.
It is a structured table classifying Bharatiya Nyaya Sanhita offences by section number, offence description, punishment, cognizability, bailability, and triable court.
Provide a keyword-dense 2–3 sentence summary covering its overall structure, purpose, and columns."""
    
    summary = await call_model_with_retry(prompt)
    summary_cache[cache_key] = summary
    node["summary"] = summary
    save_cache()

async def summarize_chapter(node):
    """
    Summarizes a chapter node from its child section summaries.
    """
    node_id = node["node_id"]
    stable_hash = node["metadata"]["stable_hash"]
    cache_key = f"{node_id}:{stable_hash}"
    
    if cache_key in summary_cache:
        node["summary"] = extract_final_summary(summary_cache[cache_key])
        return
        
    act_code = node["metadata"]["act_code"]
    act_name = ACT_FULL_NAMES.get(act_code, act_code)
    
    children_summaries = []
    for child in node["children"]:
        # Only use sections/schedule/front_matter, or sub-summaries
        c_title = child["title"]
        c_sum = child.get("summary", "")
        if c_sum:
            children_summaries.append(f"- {c_title}: {c_sum}")
            
    summaries_text = "\n".join(children_summaries)
    
    # Cap input text length if it gets too large
    if len(summaries_text) > 40000:
        summaries_text = summaries_text[:40000] + "\n...[truncated for length]..."
        
    prompt = f"""You are a precise legal summarizer. The following are summaries of all sections in {node['title']} of the {act_name}.
Provide a keyword-rich and dense 2–3 sentence summary of this chapter's scope, primary offences/topics, and legal subject matter. Preserve key terms.

Section summaries:
{summaries_text}"""

    summary = await call_model_with_retry(prompt)
    summary_cache[cache_key] = summary
    node["summary"] = summary
    save_cache()

async def summarize_root(node):
    """
    Summarizes the entire Act's root node using its chapter summaries.
    """
    node_id = node["node_id"]
    stable_hash = node["metadata"]["stable_hash"]
    cache_key = f"{node_id}:{stable_hash}"
    
    if cache_key in summary_cache:
        node["summary"] = extract_final_summary(summary_cache[cache_key])
        return
        
    act_code = node["metadata"]["act_code"]
    act_name = ACT_FULL_NAMES.get(act_code, act_code)
    
    chapter_summaries = []
    for child in node["children"]:
        c_title = child["title"]
        c_sum = child.get("summary", "")
        if c_sum:
            chapter_summaries.append(f"- {c_title}: {c_sum}")
            
    summaries_text = "\n".join(chapter_summaries)
    
    if act_code == "SOP":
        prompt = f"""You are a precise legal procedure summarizer. The following are summaries of individual Standard Operating Procedures for the {act_name}.
Provide a dense, keyword-rich one-paragraph summary (3–5 sentences) of the overall scope, key procedural workflows (such as investigation, arrest, and electronic evidence), and operational guidelines introduced by this manual.

SOP summaries:
{summaries_text}"""
    else:
        prompt = f"""You are a precise legal summarizer. The following are chapter summaries for the {act_name}.
Provide a dense, keyword-rich one-paragraph summary (3–5 sentences) of the overall scope, structure, and main legal systems/topics introduced by this Act.

Chapter summaries:
{summaries_text}"""

    summary = await call_model_with_retry(prompt)
    summary_cache[cache_key] = summary
    node["summary"] = summary
    save_cache()

async def run_summarization_pipeline(trees):
    """
    Runs the bottom-up summarization pipeline: leaf nodes -> chapter nodes -> root nodes.
    """
    load_cache()
    
    # 1. Flatten all leaf nodes across the acts
    print("Flattening and preparing leaf nodes...")
    sections = []
    schedule_rows = []
    front_matters = []
    schedules = []
    chapters = []
    roots = []
    
    def traverse(node):
        nt = node["node_type"]
        if nt == "root":
            roots.append(node)
        elif nt == "chapter":
            chapters.append(node)
        elif nt == "front_matter":
            front_matters.append(node)
        elif nt == "schedule":
            schedules.append(node)
        elif nt in ["section", "sop_procedure", "sop_form", "sop_reference", "sop_table"]:
            sections.append(node)
        elif nt == "schedule_row":
            schedule_rows.append(node)
            
        for child in node["children"]:
            traverse(child)
            
    for act_root in trees.values():
        traverse(act_root)
        
    print(f"Found: {len(sections)} sections, {len(schedule_rows)} schedule rows, {len(front_matters)} front matters, {len(schedules)} schedule chapters, {len(chapters)} chapters, {len(roots)} roots.")
    
    # 2. Process schedule rows (free, no LLM calls)
    print("Processing schedule rows...")
    cache_hits = 0
    new_rows = 0
    for row in schedule_rows:
        node_id = row["node_id"]
        stable_hash = row["metadata"]["stable_hash"]
        cache_key = f"{node_id}:{stable_hash}"
        
        if cache_key in summary_cache:
            row["summary"] = summary_cache[cache_key]
            cache_hits += 1
        else:
            summary = format_schedule_row_summary(row)
            summary_cache[cache_key] = summary
            row["summary"] = summary
            new_rows += 1
            
    save_cache()
    print(f"Schedule rows formatted: {cache_hits} cached, {new_rows} newly generated.")
    
    # 3. Summarize normal section leaves and the schedule chapters
    # We do sections and front_matters as leaf nodes
    leaves_to_summarize = sections + front_matters + schedules
    
    # Check cache hits for leaves
    uncached_leaves = []
    cached_leaves_count = 0
    for leaf in leaves_to_summarize:
        node_id = leaf["node_id"]
        stable_hash = leaf["metadata"]["stable_hash"]
        cache_key = f"{node_id}:{stable_hash}"
        if cache_key in summary_cache:
            leaf["summary"] = extract_final_summary(summary_cache[cache_key])
            cached_leaves_count += 1
        else:
            uncached_leaves.append(leaf)
            
    print(f"Leaves: {cached_leaves_count} cached, {len(uncached_leaves)} to call via API.")
    
    # Concurrency limit with locks / pacing
    if uncached_leaves:
        print("Starting rate-paced Leaf Summarization LLM calls...")
        start_time = time.time()
        
        async def summarize_task(node, idx, total):
            if node["node_type"] == "schedule":
                await summarize_schedule_chapter(node)
            else:
                await summarize_section(node)
                
            # Print progress every 50 calls
            if idx > 0 and idx % 50 == 0:
                elapsed = time.time() - start_time
                avg_time = elapsed / idx
                rem_calls = total - idx
                est_rem = avg_time * rem_calls
                print(f"Progress: {idx}/{total} leaf calls completed. Elapsed: {elapsed:.1f}s. Est. remaining: {est_rem:.1f}s.")
                
        # Fire async tasks
        tasks = [summarize_task(node, i+1, len(uncached_leaves)) for i, node in enumerate(uncached_leaves)]
        await asyncio.gather(*tasks)
        print("Leaf Summarization complete.")
    else:
        print("All leaf nodes retrieved from cache. No LLM calls needed.")
        
    # 4. Chapters Roll-Up Summarization (Bottom-up level 1)
    uncached_chapters = []
    cached_chapters_count = 0
    for chap in chapters:
        node_id = chap["node_id"]
        stable_hash = chap["metadata"]["stable_hash"]
        cache_key = f"{node_id}:{stable_hash}"
        if cache_key in summary_cache:
            chap["summary"] = extract_final_summary(summary_cache[cache_key])
            cached_chapters_count += 1
        else:
            uncached_chapters.append(chap)
            
    print(f"Chapters: {cached_chapters_count} cached, {len(uncached_chapters)} to call via API.")
    if uncached_chapters:
        print("Starting Chapter roll-up LLM calls...")
        tasks = [summarize_chapter(chap) for chap in uncached_chapters]
        await asyncio.gather(*tasks)
        print("Chapter summaries complete.")
        
    # 5. Roots Roll-Up Summarization (Bottom-up level 0)
    uncached_roots = []
    cached_roots_count = 0
    for r in roots:
        node_id = r["node_id"]
        stable_hash = r["metadata"]["stable_hash"]
        cache_key = f"{node_id}:{stable_hash}"
        if cache_key in summary_cache:
            r["summary"] = extract_final_summary(summary_cache[cache_key])
            cached_roots_count += 1
        else:
            uncached_roots.append(r)
            
    print(f"Roots: {cached_roots_count} cached, {len(uncached_roots)} to call via API.")
    if uncached_roots:
        print("Starting Root roll-up LLM calls...")
        tasks = [summarize_root(r) for r in uncached_roots]
        await asyncio.gather(*tasks)
        print("Root summaries complete.")
        
    # Save final cache
    save_cache()
    print("Summarization pipeline completed successfully.")
