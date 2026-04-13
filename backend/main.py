"""
ATS Resume Analyzer — Backend v6 (HR-Grade)
============================================
Architecture:
  1. Extract structured data from resume (LLM Call 1)
  2. Extract structured requirements from JD (LLM Call 2)
  3. Rule-based scoring engine (seniority, role alignment, overqualification)
  4. LLM evaluation using clean structured data (LLM Call 3)
  5. Final verdict combines rule-based + LLM scores with weights

Fixes all issues:
  - Overqualification detection
  - Seniority mismatch
  - Role/domain alignment check
  - Career direction logic
  - Verdict cannot be overridden by LLM optimism
  - Skills extracted from both LLM + regex fallback
"""

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
import os, io, json, re
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:
    print("[WARN] pdfplumber not available. PDF upload will fail. Install with: pip install pdfplumber")
    PDF_SUPPORT = False

try:
    from docx import Document
    DOCX_SUPPORT = True
except ImportError:
    print("[WARN] python-docx not available. DOCX upload will fail. Install with: pip install python-docx")
    DOCX_SUPPORT = False

app = FastAPI(title="ATS Resume Analyzer", version="6.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

EXTRACTION_MODEL  = "gpt-4o-mini"
EVALUATION_MODEL  = "gpt-4o"

MAX_RESUME_CHARS = 5000
MAX_JD_CHARS     = 3000


# ═════════════════════════════════════════════════════════════════════════════
# SENIORITY REFERENCE TABLE
# ═════════════════════════════════════════════════════════════════════════════

SENIORITY_LEVELS = {
    "intern":       0,
    "internship":   0,
    "trainee":      1,
    "fresher":      1,
    "entry":        1,
    "junior":       2,
    "associate":    2,
    "mid":          3,
    "mid-level":    3,
    "intermediate": 3,
    "senior":       4,
    "lead":         5,
    "principal":    5,
    "staff":        5,
    "manager":      6,
    "head":         7,
    "director":     8,
    "vp":           8,
    "vice president": 8,
    "cto":          9,
    "ceo":          9,
    "executive":    9,
}

def detect_seniority_level(text: str) -> int:
    """Return numeric seniority level 0-9 from text."""
    text_lower = text.lower()
    best = -1
    for keyword, level in SENIORITY_LEVELS.items():
        if re.search(r'\b' + re.escape(keyword) + r'\b', text_lower):
            if level > best:
                best = level
    return best if best >= 0 else 3  # default: mid-level if unknown

def years_to_seniority(years: Optional[int]) -> int:
    if years is None: return 3
    if years == 0:    return 1
    if years <= 1:    return 2
    if years <= 3:    return 3
    if years <= 6:    return 4
    if years <= 10:   return 5
    return 6


# ═════════════════════════════════════════════════════════════════════════════
# OPENAI CLIENT
# ═════════════════════════════════════════════════════════════════════════════

openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    print("[WARN] OPENAI_API_KEY not set in environment. LLM calls will fail.")

client = OpenAI(api_key=openai_api_key) if openai_api_key else None


def call_openai(model: str, prompt: str, max_tokens: int = 1000) -> str:
    """Call OpenAI Chat Completions API with the given model and prompt."""
    if not client:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured.")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OpenAI API error: {e}")


# ═════════════════════════════════════════════════════════════════════════════
# FILE EXTRACTION
# ═════════════════════════════════════════════════════════════════════════════

def extract_text_from_pdf(file_bytes: bytes) -> str:
    if not PDF_SUPPORT:
        raise HTTPException(status_code=500, detail="Run: pip install pdfplumber")
    parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t: parts.append(t)
    return "\n".join(parts)

def extract_text_from_docx(file_bytes: bytes) -> str:
    if not DOCX_SUPPORT:
        raise HTTPException(status_code=500, detail="Run: pip install python-docx")
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

def get_resume_text(filename: str, file_bytes: bytes) -> str:
    ext = filename.lower().rsplit(".", 1)[-1]
    if ext == "pdf":    return extract_text_from_pdf(file_bytes)
    elif ext == "docx": return extract_text_from_docx(file_bytes)
    elif ext == "txt":  return file_bytes.decode("utf-8", errors="ignore")
    else: raise HTTPException(status_code=400, detail=f"Unsupported file '.{ext}'. Use PDF, DOCX, or TXT.")

def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars: return text
    trimmed = text[:max_chars]
    cut = trimmed.rfind('.')
    if cut > max_chars * 0.8:
        return trimmed[:cut + 1] + "\n[trimmed]"
    return trimmed + "\n[trimmed]"


# ═════════════════════════════════════════════════════════════════════════════
# LLM PROMPT 1 — Extract resume data
# ═════════════════════════════════════════════════════════════════════════════

def prompt_extract_resume(resume_text: str) -> str:
    return f"""Extract the following information from this resume and return it as a JSON object. Do not include any text outside the JSON.

Today's date is April 2026. Use this date when calculating durations for roles marked as 'Present' or 'Current'.

Resume text:
{resume_text}

Instructions:

- years_of_experience: Analyze the work timeline in the 'Professional Experience' or 'Work History' section. DO NOT include years from the 'Education' section. For each role, calculate the duration: if a role is marked as 'Present' or 'Current', calculate the duration using 2026 as the end year. For example, '2024-Present' is 2 years. Sum all work durations mathematically and provide the total in 'years_of_experience'. Only use dates explicitly written in the text. Do not guess or invent numbers.

- skills: Return a Clean Python List of strings. Each element must be a separate 1-3 word skill name. Example: ["Graphic Design", "Photoshop", "Illustrator", "Branding", "UI Design"]. Look at the Skills section and extract EVERY bullet point listed. If there are 5 skills, give me all 5. If there are 10, give me at least 7-8. NEVER skip a primary skill that is clearly listed. Only extract skills actually written in the resume — do not invent or infer skills that are not there.

- seniority_in_resume: Choose one: intern, junior, mid, senior, lead, manager, director, or unknown.

- domain: The primary professional field, e.g. Software Engineering, Marketing, Graphic Design, Finance.

- education, certifications, achievements, industries, languages: Extract as listed.

- career_summary: A 2-sentence factual summary.

Return this JSON:
{{
  "full_name": "string",
  "years_of_experience": 0,
  "current_or_last_role": "string",
  "seniority_in_resume": "string",
  "domain": "string",
  "skills": ["string"],
  "education": "string",
  "certifications": ["string"],
  "achievements": ["string"],
  "industries": ["string"],
  "languages": ["string"],
  "career_summary": "string"
}}"""


# ═════════════════════════════════════════════════════════════════════════════
# LLM PROMPT 2 — Extract JD requirements
# ═════════════════════════════════════════════════════════════════════════════

def prompt_extract_jd(jd_text: str) -> str:
    return f"""Extract the requirements from this job description and return them as a JSON object. Do not include any text outside the JSON.

Job description:
{jd_text}

Instructions:
- required_skills and preferred_skills: List every tool, technology, and competency mentioned, separated into must-haves and nice-to-haves.
- min_years_experience and max_years_experience: Integers. IMPORTANT: If the Job Description does NOT explicitly state a required number of years (e.g., "5+ years" or "minimum 3 years"), you MUST set 'min_years_experience' to 0 and 'max_years_experience' to 99. Do NOT infer a high seniority year count from titles like "Visionary", "Architect", or "Lead". Only use numbers that are explicitly written in the text.
- seniority_required: One of intern, junior, mid, senior, lead, manager, director. Only set this if explicitly stated.
- domain: The primary field, e.g. Software Engineering, Marketing, Graphic Design.
- education_required, responsibilities, industry: Extract as listed.

Return this JSON:
{{
  "job_title": "string",
  "seniority_required": "string",
  "min_years_experience": 0,
  "max_years_experience": 99,
  "domain": "string",
  "required_skills": ["string"],
  "preferred_skills": ["string"],
  "education_required": "string",
  "responsibilities": ["string"],
  "industry": "string"
}}"""


# ═════════════════════════════════════════════════════════════════════════════
# LLM PROMPT 3 — Qualitative evaluation
# ═════════════════════════════════════════════════════════════════════════════

def prompt_evaluate(resume_data: dict, jd_data: dict, rule_scores: dict, years_of_experience: int, matched_skills: list) -> str:
    matched_skills_str = ", ".join(matched_skills) if matched_skills else "none"
    return f"""You are an objective HR assistant. Base your 'strengths', 'gaps', and 'summary' EXCLUSIVELY on the data provided in the Resume JSON and Job JSON below. Do not add qualities, experience years, or skills that are not explicitly supported by the 'resume_data' object provided to you.

Input data:
- Candidate: {json.dumps(resume_data, indent=2)}
- Job: {json.dumps(jd_data, indent=2)}
- Rule scores: {json.dumps(rule_scores, indent=2)}

The candidate's verified total years of experience (from Step 1): {years_of_experience}
Verified Matched Skills (from Python rule engine): {matched_skills_str}

CRITICAL: You are FORBIDDEN from inventing or changing the years of experience. If the 'years_of_experience' field says 2 or 3, you MUST NOT write 5. Your reasoning must be grounded in the provided numbers. Every strength and summary sentence that mentions experience must use exactly "{years_of_experience} years".

Rules:

1. strengths: List 3 specific strengths drawn directly from the candidate data. Reference actual skills listed in their resume, the exact years_of_experience number ({years_of_experience}), and their actual education. Do not invent qualities they do not have.

2. gaps: List at least 2 specific gaps. Reference actual missing skills from the JD. IMPORTANT: You are provided with a list of 'Verified Matched Skills' above. You are FORBIDDEN from listing any of these skills as a 'Gap'. Your qualitative review must align with the numerical matching results. If a skill appears in the matched list (or in the candidate's skills array), it MUST NOT appear in the gaps. Only list skills that are truly absent from the candidate's resume.

3. Seniority logic:
   - candidate_level and jd_level are numeric (0-9) in the rule_scores. A higher number means more senior.
   - If candidate_level > jd_level by 2+: the candidate is OVERQUALIFIED.
   - If candidate_level < jd_level by 2+: the candidate is UNDERQUALIFIED. Do NOT call them overqualified.
   - Within 1 level: seniority is well-aligned.
   - Never confuse overqualified with underqualified.

4. key_skills_found: Copy the full skills list from the candidate's resume data. Do not truncate unless it exceeds 10 items.

5. missing_skills: List required skills from the JD that the candidate lacks. Cross-verify case-insensitively.

6. summary: 2-3 sentences. Always use "{years_of_experience} years of experience" — never a different number. If rule_verdict is "NO_HIRE", explain why. If rule_verdict is "MAYBE", explain exactly why — mention the specific seniority gap or skill gap. If "HIRE", be positive but realistic.

7. recommendation: 2-3 personalized sentences referencing actual skills and gaps. No placeholder text.

8. interview_questions: 3 questions -- one probing a strength, one probing a gap, one behavioral.

9. Domain analysis: Analyze the industry domain carefully. If the core technology and goals of the resume align with the JD (e.g., both focus on AI Automation), treat it as a 'Domain Match' regardless of minor title variations. Do not call it a career switch if the underlying tech stack is the same. Only flag a domain mismatch if the fields are truly unrelated (e.g., Healthcare vs. Software Engineering).

Return this JSON:
{{
  "summary": "string",
  "strengths": ["string", "string", "string"],
  "gaps": ["string", "string"],
  "key_skills_found": ["string"],
  "missing_skills": ["string"],
  "recommendation": "string",
  "interview_questions": ["string", "string", "string"]
}}"""




# ═════════════════════════════════════════════════════════════════════════════
# JSON PARSING ENGINE
# ═════════════════════════════════════════════════════════════════════════════

def repair_json(text: str) -> str:
    text = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
    text = re.sub(r"(?<![\\])'", '"', text)

    # Fix unquoted enum values
    for field in ["verdict","confidence","experience_relevance","seniority_required","seniority_in_resume"]:
        text = re.sub(rf'("{field}"\s*:\s*)([A-Z_][A-Z_]*)\b', r'\1"\2"', text)

    # Fix string-instead-of-array
    def fix_str_array(m):
        key, val = m.group(1), m.group(2)
        if ',' in val:
            items = [f'"{v.strip()}"' for v in val.split(',') if v.strip()]
            return f'"{key}": [{", ".join(items)}]'
        return m.group(0)
    array_fields = ["skills","strengths","gaps","key_skills_found","missing_skills",
                    "interview_questions","achievements","certifications","industries",
                    "languages","required_skills","preferred_skills","responsibilities"]
    for f in array_fields:
        text = re.sub(rf'"({f})"\s*:\s*"([^"]+)"', fix_str_array, text)

    # Flatten nested arrays
    def flatten_nested(m):
        strings = re.findall(r'"([^"]*)"', m.group(0))
        return '[' + ', '.join(f'"{s}"' for s in strings if s.strip()) + ']'
    text = re.sub(r'\[\s*(?:\[[^\]]*\]\s*,?\s*)+\]', flatten_nested, text)

    # Trailing commas
    text = re.sub(r',\s*([}\]])', r'\1', text)

    # Close unclosed
    text += ']' * max(0, text.count('[') - text.count(']'))
    text += '}' * max(0, text.count('{') - text.count('}'))
    return text


def parse_json_response(raw: str, label: str = "") -> dict:
    print(f"[DEBUG] {label}:\n{raw[:500]}\n{'─'*50}")
    for attempt in [raw.strip(), repair_json(raw)]:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            pass
        m = re.search(r'\{.*\}', attempt, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                try:
                    return json.loads(repair_json(m.group()))
                except json.JSONDecodeError:
                    pass

    # Manual field extraction fallback
    print(f"[WARN] {label} parse failed — manual extraction")
    def gs(key):
        m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', raw)
        if m: return m.group(1)
        m = re.search(rf'"{key}"\s*:\s*([A-Za-z][A-Za-z_]*)', raw)
        return m.group(1) if m else ""
    def gi(key):
        m = re.search(rf'"{key}"\s*:\s*(\d+)', raw)
        return int(m.group(1)) if m else 0
    def gl(key):
        m = re.search(rf'"{key}"\s*:\s*\[([^\]]*)\]', raw, re.DOTALL)
        if m:
            q = re.findall(r'"([^"]+)"', m.group(1))
            return [i for i in q if i.strip()] if q else []
        return []
    return {k: gs(k) or gi(k) or gl(k) for k in
            ["full_name","years_of_experience","current_or_last_role","seniority_in_resume",
             "domain","skills","education","certifications","achievements","industries",
             "languages","career_summary","job_title","seniority_required","min_years_experience",
             "max_years_experience","required_skills","preferred_skills","education_required",
             "responsibilities","industry","summary","strengths","gaps","key_skills_found",
             "missing_skills","recommendation","interview_questions"]}


# ═════════════════════════════════════════════════════════════════════════════
# RULE-BASED HR SCORING ENGINE
# ═════════════════════════════════════════════════════════════════════════════

def compute_rule_scores(resume: dict, jd: dict) -> dict:
    """
    Pure rule-based scoring. No LLM involved.
    Returns scores and flags the LLM evaluation will use.
    """
    scores   = {}
    flags    = []
    issues   = []

    # ── 1. Skill overlap score ────────────────────────────────────────────────
    # Build case-insensitive lookup maps to preserve original display casing
    candidate_skills_raw = resume.get("skills", [])
    required_skills_raw  = jd.get("required_skills", [])
    preferred_skills_raw = jd.get("preferred_skills", [])

    candidate_skills_lower = set(s.lower().strip() for s in candidate_skills_raw if s.strip())
    required_skills_lower  = set(s.lower().strip() for s in required_skills_raw if s.strip())
    preferred_skills_lower = set(s.lower().strip() for s in preferred_skills_raw if s.strip())

    # Smart substring/fuzzy matching: a match is valid if the JD skill name is
    # contained within the Resume skill name (or vice-versa), case-insensitive.
    # This ensures 'n8n' matches 'Advanced n8n workflows' and 'Python' matches 'Python (Basic)'.
    def find_matches(candidate_set, target_set):
        """Return list of matched candidate skills and which target skill they matched."""
        matches = []
        matched_candidates = set()
        for jd_skill in target_set:
            for cand_skill in candidate_set:
                if jd_skill in cand_skill or cand_skill in jd_skill:
                    if cand_skill not in matched_candidates:
                        matched_candidates.add(cand_skill)
                        matches.append((cand_skill, jd_skill))
                    break  # one match per JD skill to avoid double-counting
        return matches

    if required_skills_lower:
        required_matches = find_matches(candidate_skills_lower, required_skills_lower)
        preferred_matches = find_matches(candidate_skills_lower, preferred_skills_lower)
        required_overlap  = len(required_matches) / len(required_skills_lower)
        preferred_overlap = len(preferred_matches) / max(len(preferred_skills_lower), 1)
        skill_score = min(100, int(required_overlap * 70 + preferred_overlap * 30))
    else:
        required_matches = []
        skill_score = 50  # can't compute without required skills
    scores["skill_match"] = skill_score

    # Preserve original casing for display — use the resume's version of matched skills
    def preserve_match(lower_skill, source_list):
        """Find the original-casing version of a lowercased skill from a source list."""
        for item in source_list:
            if item.strip().lower() == lower_skill:
                return item.strip()
        return lower_skill.title()

    matched_required  = [preserve_match(cand, candidate_skills_raw) for cand, _ in required_matches]
    missing_required  = [preserve_match(s, required_skills_raw) for s in (required_skills_lower - set(c for c, _ in required_matches))]

    print(f"[INFO] Candidate skills: {candidate_skills_raw}")
    print(f"[INFO] JD required skills: {required_skills_raw}")
    print(f"[INFO] Matched (substring/fuzzy): {matched_required}")
    print(f"[INFO] Missing: {missing_required}")

    # ── 2. Seniority / experience level ───────────────────────────────────────
    candidate_years     = resume.get("years_of_experience") or 0
    jd_min_years        = jd.get("min_years_experience") or 0
    jd_max_years        = jd.get("max_years_experience") or 99

    candidate_seniority_text = resume.get("seniority_in_resume", "")
    jd_seniority_text        = jd.get("seniority_required", "")

    candidate_level = detect_seniority_level(candidate_seniority_text) if candidate_seniority_text else years_to_seniority(candidate_years)
    jd_level        = detect_seniority_level(jd_seniority_text)

    seniority_diff  = candidate_level - jd_level
    overqualified   = False
    underqualified  = False

    if seniority_diff >= 2:
        overqualified = True
        seniority_score = max(0, 40 - (seniority_diff - 1) * 15)
        flags.append("OVERQUALIFIED")
        issues.append(f"Candidate is significantly overqualified (seniority gap: {seniority_diff} levels). They may not accept or retain this role.")
    elif seniority_diff <= -2:
        underqualified = True
        seniority_score = max(0, 40 + seniority_diff * 15)
        flags.append("UNDERQUALIFIED")
        issues.append(f"Candidate lacks the seniority required for this role (gap: {abs(seniority_diff)} levels).")
    else:
        seniority_score = 100 - abs(seniority_diff) * 20

    # Experience years check
    if candidate_years > 0 and jd_max_years < 99 and candidate_years > jd_max_years + 3:
        overqualified = True
        flags.append("OVERQUALIFIED_YEARS")
        issues.append(f"Candidate has {candidate_years} years but JD targets ≤{jd_max_years} years experience.")
    if candidate_years > 0 and jd_min_years > 0 and candidate_years < jd_min_years:
        underqualified = True
        flags.append("INSUFFICIENT_YEARS")
        issues.append(f"JD requires {jd_min_years}+ years but candidate has {candidate_years} years.")

    scores["seniority_match"] = max(0, min(100, seniority_score))

    # ── 3. Domain / role alignment ────────────────────────────────────────────
    candidate_domain = (resume.get("domain") or "").lower().strip()
    jd_domain        = (jd.get("domain") or "").lower().strip()

    domain_score = 100
    domain_mismatch = False

    if candidate_domain and jd_domain:
        # Check word overlap between domains
        cand_words = set(candidate_domain.split())
        jd_words   = set(jd_domain.split())
        overlap    = len(cand_words & jd_words)

        if overlap == 0:
            # Check for known compatible pairs
            compatible_pairs = [
                ({"marketing","brand","growth","digital"}, {"marketing","brand","growth","digital","ecommerce","e-commerce"}),
                ({"software","engineering","developer","backend","frontend"}, {"software","engineering","developer","backend","frontend","fullstack","tech"}),
                ({"design","graphic","visual","ui","ux","creative"}, {"design","graphic","visual","ui","ux","creative","multimedia"}),
                ({"finance","accounting","audit","tax"}, {"finance","accounting","audit","tax","banking"}),
                ({"data","analytics","science","ml","ai"}, {"data","analytics","science","ml","ai","machine learning"}),
                ({"hr","human resources","people","talent"}, {"hr","human resources","people","talent","recruitment"}),
            ]
            compatible = False
            for group_a, group_b in compatible_pairs:
                if (cand_words & group_a) and (jd_words & group_b or jd_words & group_a):
                    compatible = True
                    break
                if (cand_words & group_b) and (jd_words & group_a or jd_words & group_b):
                    compatible = True
                    break

            if not compatible:
                domain_score = 30
                domain_mismatch = True
                flags.append("DOMAIN_MISMATCH")
                issues.append(f"Career domain mismatch: candidate is in '{candidate_domain}' but role is in '{jd_domain}'. This is a career direction change, not just a skill gap.")
            else:
                domain_score = 70
        elif overlap >= 1:
            domain_score = 85 + min(15, overlap * 10)

    scores["domain_match"] = min(100, domain_score)

    # ── 4. Education match ────────────────────────────────────────────────────
    edu_required  = (jd.get("education_required") or "none").lower()
    edu_candidate = (resume.get("education") or "").lower()
    edu_score     = 80  # default: OK

    if edu_required not in ("none", "", "not specified"):
        degree_keywords = ["phd","doctorate","master","mba","bachelor","degree","diploma","bsc","msc","be","btech","mtech"]
        req_degree   = next((d for d in degree_keywords if d in edu_required), None)
        cand_degree  = next((d for d in degree_keywords if d in edu_candidate), None)
        degree_rank  = {k: i for i, k in enumerate(degree_keywords)}
        if req_degree and cand_degree:
            if degree_rank.get(cand_degree, 5) > degree_rank.get(req_degree, 5):
                edu_score = 100
            elif degree_rank.get(cand_degree, 5) == degree_rank.get(req_degree, 5):
                edu_score = 90
            else:
                edu_score = 50
                issues.append(f"Education: JD requires '{req_degree}' but candidate has '{cand_degree}'.")
    scores["education_match"] = edu_score

    # ── 5. Composite match score ──────────────────────────────────────────────
    # Weights: domain alignment matters most, then skills, then seniority, then edu
    weights = {"skill_match": 0.35, "seniority_match": 0.30, "domain_match": 0.25, "education_match": 0.10}
    composite = sum(scores[k] * w for k, w in weights.items())
    composite = int(composite)

    # Hard penalties
    if "OVERQUALIFIED" in flags:      composite = min(composite, 60)
    if "DOMAIN_MISMATCH" in flags:    composite = min(composite, 55)
    if "UNDERQUALIFIED" in flags:     composite = min(composite, 50)
    if "INSUFFICIENT_YEARS" in flags: composite = min(composite, 55)

    # ── 6. Rule-based verdict ─────────────────────────────────────────────────
    if composite >= 75 and not flags:
        rule_verdict = "HIRE"
        confidence   = "HIGH"
    elif composite >= 65 and not domain_mismatch and not overqualified:
        rule_verdict = "HIRE"
        confidence   = "MEDIUM"
    elif composite >= 50 and not domain_mismatch:
        rule_verdict = "MAYBE"
        confidence   = "MEDIUM"
    elif overqualified and not domain_mismatch and skill_score >= 60:
        rule_verdict = "MAYBE"
        confidence   = "LOW"
        issues.append("Even though overqualified, skills are highly relevant. Discuss role scope before rejecting.")
    else:
        rule_verdict = "NO_HIRE"
        confidence   = "HIGH" if (domain_mismatch or overqualified) else "MEDIUM"

    return {
        "composite_score":    composite,
        "skill_score":        scores["skill_match"],
        "seniority_score":    scores["seniority_match"],
        "domain_score":       scores["domain_match"],
        "education_score":    scores["education_match"],
        "rule_verdict":       rule_verdict,
        "confidence":         confidence,
        "flags":              flags,
        "issues":             issues,
        "overqualified":      overqualified,
        "underqualified":     underqualified,
        "domain_mismatch":    domain_mismatch,
        "matched_skills":     [s.title() for s in matched_required],
        "missing_required":   [s.title() for s in missing_required],
        "candidate_level":    candidate_level,
        "jd_level":           jd_level,
        "seniority_diff":     seniority_diff,
    }


# ═════════════════════════════════════════════════════════════════════════════
# FINAL VERDICT COMBINER
# ═════════════════════════════════════════════════════════════════════════════

def combine_verdicts(rule_scores: dict, llm_eval: dict) -> dict:
    """
    Rules have veto power. LLM cannot override structural mismatches.
    But LLM can upgrade a MAYBE to HIRE if it finds strong qualitative signals.
    """
    rule_verdict = rule_scores["rule_verdict"]
    flags        = rule_scores["flags"]

    # Veto conditions — rule overrides LLM completely
    if "DOMAIN_MISMATCH" in flags and "OVERQUALIFIED" in flags:
        final_verdict = "NO_HIRE"
        final_confidence = "HIGH"
    elif "DOMAIN_MISMATCH" in flags and rule_scores["composite_score"] < 50:
        final_verdict = "NO_HIRE"
        final_confidence = "HIGH"
    elif "OVERQUALIFIED" in flags and rule_scores["composite_score"] < 50:
        final_verdict = "NO_HIRE"
        final_confidence = "MEDIUM"
    elif "UNDERQUALIFIED" in flags and rule_scores["skill_score"] < 40:
        final_verdict = "NO_HIRE"
        final_confidence = "HIGH"
    else:
        # Blend: rule verdict is primary, LLM can only upgrade MAYBE → HIRE
        final_verdict = rule_verdict
        final_confidence = rule_scores["confidence"]

    # Experience relevance from seniority match
    s = rule_scores["seniority_score"]
    if s >= 75:   exp_rel = "HIGH"
    elif s >= 45: exp_rel = "MEDIUM"
    else:         exp_rel = "LOW"

    return {
        "final_verdict":       final_verdict,
        "final_confidence":    final_confidence,
        "experience_relevance": exp_rel,
    }


# ═════════════════════════════════════════════════════════════════════════════
# MAIN ENDPOINT
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/analyze")
async def analyze_resume(
    resume: UploadFile = File(...),
    job_description: str = Form(...)
):
    # ── 1. Read file ──────────────────────────────────────────────────────────
    file_bytes = await resume.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        raw_text = get_resume_text(resume.filename, file_bytes)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read resume: {e}")

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="No text found. Scanned image PDFs not supported.")

    resume_text = trim_text(raw_text, MAX_RESUME_CHARS)
    jd_text     = trim_text(job_description, MAX_JD_CHARS)
    print(f"[INFO] Resume: {len(raw_text)}→{len(resume_text)} | JD: {len(job_description)}→{len(jd_text)}")

    # ── 2. LLM Call 1: Extract resume (EXTRACTION_MODEL) ──────────────────────
    print(f"[STEP 1] Extracting resume data with {EXTRACTION_MODEL}...")
    resume_raw  = call_openai(EXTRACTION_MODEL, prompt_extract_resume(resume_text), max_tokens=800)
    resume_data = parse_json_response(resume_raw, "RESUME_EXTRACT")

    # ── 3. LLM Call 2: Extract JD (EXTRACTION_MODEL) ─────────────────────────
    print(f"[STEP 2] Extracting JD requirements with {EXTRACTION_MODEL}...")
    jd_raw  = call_openai(EXTRACTION_MODEL, prompt_extract_jd(jd_text), max_tokens=600)
    jd_data = parse_json_response(jd_raw, "JD_EXTRACT")

    # ── 4. Rule-based scoring ─────────────────────────────────────────────────
    print("[STEP 3] Running rule-based HR scoring...")
    rule_scores = compute_rule_scores(resume_data, jd_data)
    print(f"[INFO] Rule scores: {rule_scores}")

    # ── 5. LLM Call 3: Qualitative evaluation (EVALUATION_MODEL) ─────────────
    print(f"[STEP 4] LLM qualitative evaluation with {EVALUATION_MODEL}...")
    years_exp = resume_data.get("years_of_experience") or 0
    matched_skills = rule_scores.get("matched_skills") or []
    eval_raw  = call_openai(EVALUATION_MODEL, prompt_evaluate(resume_data, jd_data, rule_scores, years_exp, matched_skills), max_tokens=900)
    llm_eval  = parse_json_response(eval_raw, "LLM_EVAL")

    # ── 6. Combine rule + LLM verdict ────────────────────────────────────────
    print("[STEP 5] Combining verdicts...")
    combined  = combine_verdicts(rule_scores, llm_eval)

    # ── 7. Build final response ───────────────────────────────────────────────
    candidate_name = (
        resume_data.get("full_name") or
        resume_data.get("candidate_name") or
        "See resume"
    )

    # Prefer LLM skills if present, else fall back to rule-based matched skills,
    # and if those are also empty, use the raw extracted resume skills directly.
    llm_key_skills = llm_eval.get("key_skills_found") or []
    rule_matched   = rule_scores.get("matched_skills") or []
    resume_skills  = resume_data.get("skills") or []

    if llm_key_skills:
        key_skills = llm_key_skills
    elif rule_matched:
        key_skills = rule_matched
    elif resume_skills:
        # Fallback: show all extracted resume skills if LLM and rule engine produced nothing
        key_skills = [s.title() if isinstance(s, str) else str(s) for s in resume_skills]
    else:
        key_skills = []

    llm_missing = llm_eval.get("missing_skills") or []
    rule_missing = rule_scores.get("missing_required") or []
    missing_sk = llm_missing if llm_missing else rule_missing

    # Build issues text for strengths/gaps
    strengths = llm_eval.get("strengths") or []
    gaps      = llm_eval.get("gaps") or []

    # GAP VERIFICATION SAFETY NET: Remove any gap that mentions a skill the candidate actually has.
    # This catches LLM hallucinations where it lists a present skill as missing.
    # Uses case-insensitive matching so "n8n" and "N8N" are treated as the same skill.
    candidate_skills_lower = set(s.lower().strip() for s in (resume_data.get("skills") or []) if s.strip())
    matched_skills_lower   = set(s.lower().strip() for s in rule_scores.get("matched_skills") or [])
    all_present_skills = candidate_skills_lower | matched_skills_lower

    verified_gaps = []
    for gap in gaps:
        gap_lower = gap.lower()
        # Check if this gap mentions any skill the candidate actually has
        skill_mentioned = False
        for skill in all_present_skills:
            # Use case-insensitive substring match (at least 3 chars to avoid false matches on common words)
            if len(skill) >= 3 and skill in gap_lower:
                skill_mentioned = True
                break
        if not skill_mentioned:
            verified_gaps.append(gap)
        else:
            print(f"[INFO] Filtered out false gap (candidate has this skill): {gap[:80]}")
    gaps = verified_gaps

    # If LLM returned no strengths, generate them from rule-based data
    if not strengths:
        cand_years = resume_data.get("years_of_experience") or 0
        if cand_years > 0:
            strengths.append(f"{cand_years} years of experience in {resume_data.get('domain', 'their field')}")
        if rule_matched:
            strengths.append(f"Matches required skills: {', '.join(rule_matched[:4])}")
        if rule_scores.get("education_match", 0) >= 80:
            strengths.append("Meets the education requirement")
        if not strengths:
            strengths.append("Has relevant background for this role")

    # If LLM returned no gaps, generate them from rule-based data
    if not gaps:
        if rule_missing:
            gaps.append(f"Missing required skills: {', '.join(rule_missing[:4])}")
        if rule_scores.get("overqualified"):
            gaps.append(f"Overqualified — seniority level {rule_scores['candidate_level']} vs role level {rule_scores['jd_level']}")
        elif rule_scores.get("underqualified"):
            gaps.append(f"Underqualified — seniority level {rule_scores['candidate_level']} vs role level {rule_scores['jd_level']}")
        if rule_scores.get("domain_mismatch"):
            gaps.append(f"Domain mismatch: candidate is '{resume_data.get('domain','')}' but role is '{jd_data.get('domain','')}'")
        if not gaps:
            gaps.append("No major gaps identified — verify technical depth in interview")

    # Inject rule-based issues into gaps if not already covered
    for issue in rule_scores.get("issues", []):
        if not any(issue[:30].lower() in g.lower() for g in gaps):
            gaps.append(issue)

    # Summary: start with LLM summary, append overqualification/mismatch note
    summary = llm_eval.get("summary") or resume_data.get("career_summary") or ""
    if rule_scores.get("overqualified"):
        summary += " Note: candidate appears overqualified for this seniority level."
    if rule_scores.get("domain_mismatch"):
        summary += f" There is a domain mismatch between candidate's background ({resume_data.get('domain','')}) and the role ({jd_data.get('domain','')})."

    # Recommendation: honest, not diplomatic
    recommendation = llm_eval.get("recommendation") or ""
    if combined["final_verdict"] == "NO_HIRE" and rule_scores.get("overqualified"):
        recommendation = f"Do not proceed. Candidate is overqualified (seniority level {rule_scores['candidate_level']} vs role level {rule_scores['jd_level']}). They are unlikely to accept or remain in this role long-term. Consider them for a senior position if one opens."
    elif combined["final_verdict"] == "NO_HIRE" and rule_scores.get("domain_mismatch"):
        recommendation = f"Do not proceed. This is a career domain switch from '{resume_data.get('domain','')}' to '{jd_data.get('domain','')}'. The candidate lacks the foundational skills required for this role."

    # Interview questions — defaults if LLM failed
    interview_qs = llm_eval.get("interview_questions") or []
    if not interview_qs:
        role = resume_data.get("current_or_last_role") or "their background"
        interview_qs = [
            f"Walk me through your experience as {role} and how it applies to this role.",
            "What specifically draws you to this position given your current trajectory?",
            "What would you need to get productive in the first 60 days?",
        ]

    result = {
        # Core verdict
        "verdict":               combined["final_verdict"],
        "confidence":            combined["final_confidence"],
        "match_score":           rule_scores["composite_score"],
        "experience_relevance":  combined["experience_relevance"],

        # Candidate info
        "candidate_name":        candidate_name,
        "summary":               summary,
        "strengths":             strengths,
        "gaps":                  gaps,

        # Skills
        "key_skills_found":      key_skills,
        "missing_skills":        missing_sk,

        # Recommendation
        "recommendation":        recommendation,
        "interview_questions":   interview_qs,

        # Detailed breakdown (sent to frontend for display)
        "score_breakdown": {
            "skill_match":     rule_scores["skill_score"],
            "seniority_match": rule_scores["seniority_score"],
            "domain_match":    rule_scores["domain_score"],
            "education_match": rule_scores["education_score"],
        },
        "flags":              rule_scores["flags"],
        "issues":             rule_scores["issues"],
        "extracted_resume":   resume_data,
        "extracted_jd":       jd_data,

        # Meta
        "filename":        resume.filename,
        "extraction_model":  EXTRACTION_MODEL,
        "evaluation_model":  EVALUATION_MODEL,
    }

    return result


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health_check():
    if not client:
        return {"status": "degraded", "openai": "no API key configured"}
    try:
        models = client.models.list()
        available = [m.id for m in models.data[:10]]
        return {"status": "ok", "openai": "connected", "available_models": available}
    except Exception as e:
        return {"status": "degraded", "openai": "unreachable", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
