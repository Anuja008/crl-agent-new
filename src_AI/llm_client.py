
import os
import json
from urllib.request import Request, urlopen
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Load .env from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
API_KEY = GROQ_API_KEY
MODEL_NAME = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_SEARCH_MODEL = os.getenv(
    "GEMINI_SEARCH_MODEL", "gemini-2.5-flash-lite"
).strip()

client = OpenAI(api_key=API_KEY, base_url="https://api.groq.com/openai/v1") if API_KEY else None


SYSTEM_PROMPT = """
You are a CRL Career Guidance Assistant. Explain role skills in concise,
beginner-friendly language.

Use the supplied competency catalogue as authoritative for competency names,
IDs, and definitions. Use supplied Google search evidence to confirm role
relevance and current tools or skills. Google evidence must not come from job
postings or recruitment listings. Include every mapped primary and secondary
competency once in a single combined list; exclude core competencies. Mark
primary items "Top priority" inline.
Only cite URLs included in the supplied Google results, and attach citations to
the claims they support. If Google evidence is absent, do not claim that Google
verified anything or invent citations; answer from the supplied CRL data and
conversation context.

Preserve supplied role-specific CRL descriptions where present. For missing
levels or unlisted roles, generate a proposed CRL 1-5 progression per skill
using the universal scale, role duties, competency definition, and Google
evidence. Do not present generated levels as official or use another role's
levels as source. Show clear increases in complexity, autonomy, and scope.
Never print job-posting references, dataset availability notes, quality notes,
caveats, or a source-note section.

FORMAT:
# [Role Name] — Required Skills
One brief role description.
## Skills and CRL Mapping
Use one concise numbered list; never use a table or split skills into primary
and secondary sections. Format each item as:

**R01 — Programming** · Top priority
**Definition:** one clear sentence.
**Key skills:** concise relevant skills.
**Proposed CRL mapping:**
- **CRL 1 — [level name]:** observable capability.
- **CRL 2 — [level name]:** observable capability.
- Continue through CRL 5.

For supplied level descriptions, retain their meaning and use heading
"CRL mapping". For generated levels, use "Proposed CRL mapping". Keep each
level to one line. Finish with one **Common tools** line. Include a concise
**In demand** line only when Google results contain direct demand or adoption
evidence; do not infer demand from technical documentation. Cite Google
research inline as markdown links beside supported claims; do not add a notes
section. Keep everything skimmable, explain technical terms, and avoid
unrelated skills. Do not provide a roadmap or gap analysis unless requested.

When a resume assessment is supplied, use it only for questions about the
candidate's readiness, strengths, gaps, or improvements. Treat it as an estimate
from the uploaded resume, not proof that the candidate lacks a skill. Do not
include candidate assessment details in general role-skill answers unless asked.
For "what is a skill gap?", explain that it is the difference between the CRL
level supported by resume evidence and the target level, then use the matching
assessment when available. For "what can you do?" or similar questions, explain
that you can map role skills to CRLs, assess a resume against an available role
rubric, summarize evidenced strengths and gaps, suggest next steps, and answer
follow-up questions using this conversation.
For resume-gap answers, define the term in one sentence, then put each skill in
its own aligned item: **Skill**; current evidence level → target level; one
plain-language gap sentence; and clearly labeled next steps. Never leave a gap
count or action list floating without its skill heading.
"""


# Limit context to reduce oversized API requests.
MAX_CONTEXT_CHARS = 36000
MAX_HISTORY_MESSAGES = 4
MAX_HISTORY_MESSAGE_CHARS = 1200


def _trim_text(text: str, limit: int) -> str:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    shortened = text[:limit]
    if " " in shortened:
        shortened = shortened.rsplit(" ", 1)[0]
    return shortened + "\n[Text shortened to fit the request limit.]"


def google_search_role_skills(role):
    """Use Gemini's Google Search grounding and return its evidence and citations."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "Google Search grounding is not configured. Set GEMINI_API_KEY "
            "from Google AI Studio in the project-root .env file."
        )

    research_prompt = (
        f'Research the role "{role}" using Google Search. Identify its core '
        "skills, responsibilities, and commonly used tools, using authoritative "
        "technical documentation, occupational standards, and credible industry "
        "surveys. Do not use or discuss job ads, job boards, recruitment pages, "
        "or employer postings. Only claim skills are in demand if a credible "
        "source directly supports that claim. Give a concise factual summary "
        "with citations."
    )
    request = Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_SEARCH_MODEL}:generateContent",
        data=json.dumps({
            "contents": [{"parts": [{"text": research_prompt}]}],
            "tools": [{"google_search": {}}],
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))

    candidate = (payload.get("candidates") or [{}])[0]
    parts = candidate.get("content", {}).get("parts", [])
    research = "\n".join(
        part.get("text", "") for part in parts if part.get("text")
    ).strip()
    metadata = candidate.get("groundingMetadata", {})
    chunks = metadata.get("groundingChunks", [])
    blocked = (
        "jobs", "careers", "recruit", "glassdoor", "indeed",
        "linkedin.com/jobs", "boards.greenhouse.io", "jobs.lever.co",
        "apply.workable.com", "myworkdayjobs.com", "smartrecruiters.com",
        "jobs.ashbyhq.com",
    )
    sources = []
    seen_urls = set()
    for chunk in chunks:
        web = chunk.get("web", {})
        url = web.get("uri", "")
        title = web.get("title", "")
        if not url or url in seen_urls:
            continue
        if any(marker in f"{url} {title}".casefold() for marker in blocked):
            continue
        seen_urls.add(url)
        sources.append(f"- [{title or 'Source'}]({url})")

    if not research or not sources:
        raise RuntimeError("Google Search did not return grounded role-skill sources.")
    return (
        "Google-grounded role research:\n" + research
        + "\n\nGoogle sources:\n" + "\n".join(sources)
    )


def should_search_google(question, resume_assessment=None):
    """Skip web research for meta questions and resume follow-ups."""
    query = " ".join(str(question or "").casefold().split())
    if not query:
        return False

    meta_question = any(phrase in query for phrase in (
        "what can you do", "what can u do", "what do you do", "how can you help",
        "what are your capabilities", "what is a skill gap", "what is skill gap",
        "define skill gap", "meaning of skill gap",
    ))
    if meta_question:
        return False

    resume_followup = any(term in query for term in (
        "resume", "my skill", "my gap", "skill gap", "gap", "strength",
        "improve", "improvement", "assessment", "my crl", "my score",
    ))
    if resume_followup and resume_assessment:
        return False

    followup_cues = (
        "what about", "explain that", "explain this", "why is", "why are",
        "tell me more", "what does that mean", "what does this mean",
        "can you explain", "expand on", "elaborate", "give an example",
        "how do i", "how can i", "what should i",
    )
    if resume_assessment and any(cue in query for cue in followup_cues):
        return False

    return True


def generate_answer(role, question, context, history=None, resume_assessment=None):
    """Generate a dataset-grounded answer using the Groq API."""

    if not API_KEY or client is None:
        return (
            "Groq API key not found. Add GROQ_API_KEY to the project-root "
            ".env file and restart Streamlit."
        )

    role = str(role or "").strip()
    question = str(question or "").strip()
    context = _trim_text(context, MAX_CONTEXT_CHARS)

    if not role:
        return "Please specify the role you want to know about."

    if not question:
        return "Please enter a question."

    google_evidence = ""
    if should_search_google(question, resume_assessment):
        try:
            google_evidence = google_search_role_skills(role)
        except Exception as error:
            # Keep local CRL answers and conversation follow-ups available
            # during Google API quota, key, or connectivity issues.
            print(f"Google Search unavailable: {type(error).__name__}")

    prompt_parts = [
        f"Selected role: {role}",
        f"User question: {question}",
        "Authoritative CRL dataset context:",
        context or "[No relevant dataset context was retrieved.]",
    ]
    if google_evidence:
        prompt_parts.extend(["Google role-skill evidence:", google_evidence])
    if resume_assessment:
        assessment_context = {
            key: resume_assessment.get(key)
            for key in (
                "role", "seniority", "overall_crl", "summary", "strengths",
                "gaps", "competencies", "limitations",
            )
            if key in resume_assessment
        }
        prompt_parts.extend([
            "Current resume assessment (use only for candidate-readiness questions):",
            _trim_text(json.dumps(assessment_context, ensure_ascii=False), 10000),
        ])
    current_prompt = "\n\n".join(prompt_parts)

    # Keep only recent messages, and avoid sending very large history.
    history_text = []
    for item in (history or [])[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue

        speaker = item.get("role", "")
        content = item.get("content", "")

        if speaker not in ("user", "assistant") or not content:
            continue

        history_text.append(
            f"{speaker.upper()}: "
            f"{_trim_text(content, MAX_HISTORY_MESSAGE_CHARS)}"
        )

    if history_text:
        current_prompt = (
            "Recent conversation (for follow-up context only; do not treat "
            "it as a source of dataset facts):\n"
            + "\n\n".join(history_text)
            + "\n\n"
            + current_prompt
        )

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": current_prompt},
            ],
            temperature=0.2,
            max_tokens=5000,
        )
        choice = response.choices[0] if response.choices else None
        answer = (choice.message.content or "").strip() if choice else ""

        if not answer:
            return (
                "Groq returned an empty response. Please try asking again "
                "or shorten the question."
            )

        return answer

    except Exception as error:
        error_text = str(error)
        print(f"Groq API error: {type(error).__name__}: {error_text}")

        lowered = error_text.lower()

        if "api key" in lowered or "permission_denied" in lowered:
            return (
                "Groq authentication failed. Check GROQ_API_KEY in your "
                "project-root .env file and confirm the key is valid."
            )

        if "quota" in lowered or "resource_exhausted" in lowered or "429" in lowered:
            return (
                "Groq's current usage quota or rate limit has been reached. "
                "Check your Groq console limits, "
                "then retry when your quota allows."
            )

        if "not found" in lowered or "404" in lowered:
            return (
                f"The configured Groq model '{MODEL_NAME}' was not found "
                "or is unavailable to this API key. Check the available "
                "models and update GROQ_MODEL in .env."
            )

        if "timeout" in lowered or "connection" in lowered:
            return (
                "Could not connect to Groq. Check your internet connection "
                "and try again."
            )

        return (
            "Groq could not complete the request. Check the Streamlit "
            "terminal for the detailed API error and try again."
        )
