
import sys
import re
import uuid
from datetime import datetime

from pathlib import Path

import streamlit as st

# Make the project root importable when Streamlit runs this file.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src_AI.data_loader import load_all_data
from src_AI.job_search import find_role
from src_AI.chat_service import answer_question
from src_AI.resume_coach import analyze_resume, extract_resume, role_rubric


# ---------------------------------------------------------
# Page configuration
# ---------------------------------------------------------

st.set_page_config(
    page_title="CRL Career Guidance",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------
# Styling
# ---------------------------------------------------------

st.markdown(
    """
    <style>
    .stApp {
        background: #212121;
        color: #ECECEC;
    }

    
/* Keep chat content within the available viewport */
[data-testid="stAppViewContainer"] .main .block-container {
    max-width: 100%;
    width: 100%;
    padding-left: clamp(1rem, 4vw, 4rem);
    padding-right: clamp(1rem, 4vw, 4rem);
    padding-bottom: 7rem;
    box-sizing: border-box;
}

/* Prevent long text and headings from overflowing */
[data-testid="stChatMessage"],
[data-testid="stMarkdownContainer"] {
    min-width: 0;
    max-width: 100%;
    overflow-wrap: anywhere;
    word-break: normal;
}

/* Keep code and long lines scrollable rather than cutting off */
[data-testid="stMarkdownContainer"] pre {
    max-width: 100%;
    overflow-x: auto;
}

/* Keep the chat input within the viewport */
[data-testid="stChatInput"] {
    max-width: 100%;
    box-sizing: border-box;
}


    [data-testid="stSidebar"] {
        background: #171717;
        border-right: 1px solid #333333;
    }

    [data-testid="stSidebar"] [data-testid="stButton"] button {
        width: 100%;
        text-align: left;
        border-radius: 9px;
        border: 1px solid transparent;
        background: transparent;
        color: #E5E5E5;
        min-height: 42px;
    }

    [data-testid="stSidebar"] [data-testid="stButton"] button:hover {
        background: #292929;
        border-color: #444444;
    }

    [data-testid="stSidebar"] [data-testid="stButton"] button[kind="primary"] {
        background: #303030;
        border-color: #454545;
    }

    [data-testid="stChatMessage"] {
        border-radius: 12px;
    }

    [data-testid="stChatInput"] {
        background: #2A2A2A;
    }

    [data-testid="stChatInput"] textarea {
        color: #FFFFFF;
    }

    .main-title {
        font-size: 1.8rem;
        font-weight: 650;
        margin-bottom: 0.25rem;
    }

    .sub-title {
        color: #A7A7A7;
        font-size: 0.95rem;
        margin-bottom: 1.5rem;
    }

    .role-label {
        display: inline-block;
        background: #303030;
        color: #D8D8D8;
        padding: 5px 10px;
        border-radius: 8px;
        font-size: 0.85rem;
        margin-bottom: 14px;
    }

    div[data-testid="stChatInput"] {
        border-color: #454545;
    }

    #MainMenu, footer {
        visibility: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------
# Load data
# ---------------------------------------------------------

@st.cache_data(show_spinner=False)
def get_role_names():
    data = load_all_data()
    mapping = data["role_mapping"]

    if "Fresher role" not in mapping.columns:
        raise ValueError(
            "The role_mapping dataset does not contain the "
            "'Fresher role' column."
        )

    names = (
        mapping["Fresher role"]
        .dropna()
        .astype(str)
        .str.strip()
    )

    return sorted(
        {name for name in names if name},
        key=str.casefold,
    )


@st.cache_data(show_spinner=False)
def get_crl_descriptions():
    return load_all_data()["crl_descriptions"]


def normalize(value):
    return " ".join(str(value or "").casefold().split())


def detect_role(message, role_names):
    """
    Detect a role mentioned naturally in the user's message.
    Prefer the longest role name to avoid shorter partial matches.
    """
    text = normalize(message)
    if not text:
        return None

    # Prefer exact matching first.
    for name in role_names:
        if normalize(name) == text:
            return name

    matches = [
        name for name in role_names
        if normalize(name) in text
    ]

    if not matches:
        # Try the existing role matcher as a fallback.
        try:
            result = find_role(message)

            if isinstance(result, dict) and not result.get("ambiguous"):
                candidate = result.get("Fresher role")
                if candidate:
                    return str(candidate).strip()
        except Exception:
            pass

        return extract_unlisted_role(message)

    # Avoid choosing a shorter role when a more specific role is present.
    longest_length = max(len(normalize(name)) for name in matches)
    longest_matches = [
        name for name in matches
        if len(normalize(name)) == longest_length
    ]

    # If multiple equally long role names match, do not guess.
    unique_matches = sorted(set(longest_matches), key=str.casefold)

    if len(unique_matches) == 1:
        return unique_matches[0]

    return None


def extract_unlisted_role(message):
    """Extract a reasonable free-form role title from a skills question."""
    text = str(message or "").strip().rstrip("?.! ")
    if not text:
        return None

    patterns = [
        r"(?:what\s+)?(?:skills?|competencies|requirements|crl(?:\s+levels?)?)(?:\s+and\s+(?:skills?|competencies|crl(?:\s+levels?)?))*\s+(?:(?:are|is|do|does|would|will)\s+)?(?:(?:required|needed|necessary)\s+)?(?:for|of)\s+(?:the\s+)?(?:role\s+of\s+)?(.+)$",
        r"(?:for|as)\s+(?:the\s+)?(?:role\s+of\s+)?(.+)$",
        r"(?:what|which|explain|describe|tell\s+me\s+about|show\s+me|list|give\s+me)\s+(.+)$",
    ]

    candidate = text
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            break

    candidate = re.sub(
        r"^(?:(?:me\s+)?about\s+|me\s+)",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"^(?:a|an|the)\s+", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"^(?:(?:are|is)\s+)?(?:the\s+)?(?:skills?|competencies|requirements?)\s+(?:does|do)\s+(?:a|an|the)\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+(?:need|needs|require|requires|should\s+know)$", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"\s+(?:in|at)\s+(?:a\s+|an\s+|the\s+)?(?:it|tech|technology|software|product)\s+companies?$",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.sub(r"\s+at\s+[\w&.-]+(?:\s+[\w&.-]+)*$", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(
        r"\s+(?:skills?|competencies|requirements?|with\s+crl(?:\s+mapping)?|and\s+crl(?:\s+mapping)?)$",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).strip(" ,:-")

    if not candidate or len(candidate) > 100:
        return None

    # Reject conversational prompts that do not contain a plausible title.
    words = candidate.split()
    if words and normalize(words[0]) in {
        "can", "could", "would", "will", "do", "does", "did", "is",
        "are", "was", "were", "am", "have", "has", "had", "should",
        "tell", "show", "explain", "define", "clarify", "understand",
        "who", "where", "when", "why",
    }:
        return None
    if len(words) > 10 or normalize(candidate) in {
        "it", "technology", "tech", "software", "a role", "any role",
        "skill gap", "a skill gap", "my resume", "this app", "the chatbot",
    }:
        return None
    if len(words) == 1 and normalize(candidate) in {
        "what", "which", "how", "please", "tell", "show", "list", "explain",
    }:
        return None

    return candidate


def format_assessment(assessment, rubric):
    """Render the same score summary and skill details for every assessment."""
    by_id = {item.get("competency_id"): item for item in assessment.get("competencies", [])}
    gaps = {item.get("competency_id"): item for item in assessment.get("gaps", [])}
    overall = assessment.get("overall_crl")
    overall_label = f"CRL {overall}" if overall is not None else "Not enough evidence"
    lines = [
        f"## Resume CRL assessment - {assessment.get('role')} ({assessment.get('seniority')})",
        f"**Estimated overall CRL:** {overall_label}",
        f"**Skills with direct evidence:** {assessment.get('scored_competencies', 0)} of {len(rubric)} mapped skills",
        assessment.get("summary", "") or "Resume evidence compared with each mapped role skill.",
        "",
        "### Mapped skills and CRL evidence",
    ]
    for skill in rubric:
        skill_id = skill.get("competency_id", "")
        item = by_id.get(skill_id, {})
        current = item.get("estimated_crl")
        target = item.get("target_crl", 3)
        current_text = f"CRL {current}" if current is not None else "Not evidenced in resume"
        target_text = f"CRL {target}" if target is not None else "Target not set"
        lines.extend([
            "",
            f"### {skill_id} - {skill.get('competency', 'Skill')}",
            f"**CRL:** {current_text} -> {target_text}",
        ])
        definition = skill.get("definition", "")
        if definition:
            lines.append(f"**Definition:** {definition}")
        if skill.get("includes"):
            lines.append(f"**Includes:** {skill['includes']}")
        evidence = item.get("evidence_quote")
        lines.append(f"**Verbatim resume evidence:** {evidence or 'No matching resume passage found.'}")
        reason = item.get("reason")
        if reason:
            lines.append(f"**Assessment:** {reason}")
        gap = gaps.get(skill_id)
        actions = gap.get("recommended_actions", []) if gap else []
        if gap and gap.get("gap"):
            lines.append(f"**Gap:** {gap['gap']}")
        if actions:
            lines.append("**Next steps:**")
            lines.extend(f"- {action}" for action in actions)
    strengths = assessment.get("strengths", [])
    if strengths:
        lines.extend(["", "### Strengths"])
        for item in strengths:
            lines.append(
                f"- **{item.get('competency_id', '')} — {item.get('competency', 'Skill')}** "
                f"(CRL {item.get('estimated_crl')}): {item.get('reason', '')}"
            )
    if gaps:
        lines.extend(["", "### Skill gaps and next steps"])
        for skill in rubric:
            item = gaps.get(skill.get("competency_id"))
            if not item:
                continue
            current = item.get("estimated_crl")
            target = item.get("target_crl")
            current_label = f"CRL {current}" if current is not None else "Not evidenced"
            lines.extend([
                "",
                f"**{skill.get('competency_id')} — {skill.get('competency', 'Skill')}:** "
                f"{current_label} → CRL {target}",
            ])
            if item.get("gap"):
                lines.append(item["gap"])
            actions = item.get("recommended_actions", [])
            if isinstance(actions, str):
                actions = [actions]
            lines.extend(f"- {action}" for action in actions)
    lines.extend(["", "*Scores reflect evidence found in this resume. Missing evidence does not mean the skill is absent.*"])
    return "\n".join(lines)


def render_assessment_card(assessment, rubric):
    """Show the resume assessment in the same score-card layout each time."""
    st.markdown(
        f"### Resume CRL assessment - {assessment.get('role')} "
        f"({assessment.get('seniority')})"
    )
    score = assessment.get("overall_crl")
    score_col, evidence_col = st.columns(2)
    score_col.metric("Estimated CRL", f"CRL {score}" if score is not None else "Not enough evidence")
    evidence_col.metric(
        "Skills with evidence",
        f"{assessment.get('scored_competencies', 0)} / {len(rubric)}",
    )
    if assessment.get("summary"):
        st.write(assessment["summary"])

    results = {item.get("competency_id"): item for item in assessment.get("competencies", [])}
    rows = []
    for skill in rubric:
        item = results.get(skill.get("competency_id"), {})
        level = item.get("estimated_crl")
        target = item.get("target_crl")
        rows.append({
            "CRL ID": skill.get("competency_id", ""),
            "Skill": skill.get("competency", ""),
            "Estimated CRL": f"CRL {level}" if level is not None else "Not evidenced",
            "Target CRL": f"CRL {target}" if target is not None else "CRL 3",
            "Status": item.get("status", "Not enough evidence"),
        })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.markdown("**Resume evidence matched to each skill**")
    for skill in rubric:
        item = results.get(skill.get("competency_id"), {})
        st.markdown(
            f"**{skill.get('competency_id', '')} - {skill.get('competency', 'Skill')}**"
        )
        quote = item.get("evidence_quote")
        if quote:
            st.markdown(f"> {quote}")
            if item.get("reason"):
                st.caption(f"Why it matches: {item['reason']}")
        else:
            st.caption("No matching evidence passage was found in the resume for this skill.")

    strengths = assessment.get("strengths", [])
    if strengths:
        st.markdown("**Strengths**")
        for item in strengths:
            score = item.get("estimated_crl")
            score_text = f" (CRL {score})" if score is not None else ""
            st.markdown(
                f"- **{item.get('competency_id', '')} - {item.get('competency', 'Skill')}{score_text}:** "
                f"{item.get('reason', '')}"
            )

    gaps = {item.get("competency_id"): item for item in assessment.get("gaps", [])}
    ordered_gaps = [gaps[skill.get("competency_id")] for skill in rubric if skill.get("competency_id") in gaps]
    if ordered_gaps:
        st.markdown("**Skill gaps and next steps**")
        for item in ordered_gaps:
            st.markdown(f"**{item.get('competency_id', '')} - {item.get('competency', 'Skill')}**")
            current = item.get("estimated_crl")
            target = item.get("target_crl") or 3
            current_text = f"CRL {current}" if current is not None else "Not evidenced"
            st.caption(f"{current_text} -> CRL {target}. {item.get('gap', '')}")
            actions = item.get("recommended_actions", [])
            if isinstance(actions, str):
                actions = [actions]
            for action in actions:
                st.markdown(f"- {action}")
    st.caption(
        "Scores reflect evidence found in this resume. Missing evidence does not mean the skill is absent."
    )


# ---------------------------------------------------------
# Conversation state
# ---------------------------------------------------------

def make_chat():
    now = datetime.now()

    return {
        "id": str(uuid.uuid4()),
        "title": "New chat",
        "role": None,
        "created_at": now,
        "messages": [],
    }


if "chats" not in st.session_state:
    first_chat = make_chat()
    st.session_state.chats = {first_chat["id"]: first_chat}
    st.session_state.active_chat_id = first_chat["id"]

if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = next(
        iter(st.session_state.chats)
    )

# Recover safely if the selected conversation no longer exists.
if st.session_state.active_chat_id not in st.session_state.chats:
    st.session_state.active_chat_id = next(
        iter(st.session_state.chats)
    )


def create_new_chat():
    chat = make_chat()
    st.session_state.chats[chat["id"]] = chat
    st.session_state.active_chat_id = chat["id"]


# ---------------------------------------------------------
# Sidebar
# ---------------------------------------------------------

with st.sidebar:
    st.markdown("## 🎯 CRL Career Guidance")
    st.caption("Career roles, competencies and CRL levels")

    if st.button(
        "+ New Chat",
        key="new_chat_button",
        type="primary",
        use_container_width=True,
    ):
        create_new_chat()
        st.rerun()

    st.divider()
    st.markdown("### Your conversations")

    ordered_chats = sorted(
        st.session_state.chats.values(),
        key=lambda item: item["created_at"],
        reverse=True,
    )

    for chat_item in ordered_chats:
        chat_id = chat_item["id"]
        label = chat_item["title"]

        if len(label) > 30:
            label = label[:27] + "..."

        is_active = chat_id == st.session_state.active_chat_id

        if st.button(
            ("●  " if is_active else "   ") + label,
            key=f"select_chat_{chat_id}",
            type="primary" if is_active else "secondary",
            use_container_width=True,
        ):
            st.session_state.active_chat_id = chat_id
            st.rerun()

    st.divider()

    # Resume scoring is available here on every chat, without scrolling the
    # main conversation back to its assessment panel.
    with st.expander("Resume CRL assessment", expanded=False):
        resume_data = load_all_data()
        sidebar_crl = resume_data["crl_descriptions"]
        sidebar_roles = sorted(
            {v for v in resume_data["role_mapping"]["Fresher role"].dropna().astype(str).str.strip() if v},
            key=str.casefold,
        )
        current_chat = st.session_state.chats[st.session_state.active_chat_id]
        widget_scope = current_chat["id"]
        saved_assessment = st.session_state.get("resume_assessment") or {}
        role_default = current_chat.get("role") or saved_assessment.get("role")
        role_index = sidebar_roles.index(role_default) if role_default in sidebar_roles else 0
        sidebar_role = st.selectbox(
            "Target role for your resume", sidebar_roles, index=role_index,
            key=f"sidebar_resume_role_{widget_scope}"
        )
        sidebar_seniorities = sorted(
            sidebar_crl.loc[
                sidebar_crl["Role"].fillna("").astype(str).str.strip() == sidebar_role,
                "Seniority",
            ].dropna().astype(str).str.strip().unique(),
            key=str.casefold,
        )
        if not sidebar_seniorities:
            sidebar_seniorities = ["Fresher"]
        sidebar_seniority = st.selectbox(
            "Seniority", sidebar_seniorities,
            key=f"sidebar_resume_seniority_{widget_scope}"
        )
        sidebar_file = st.file_uploader(
            "Upload a resume (PDF or TXT)", type=["pdf", "txt"],
            key=f"sidebar_resume_file_{widget_scope}"
        )
        st.caption("The uploaded resume text is sent to the configured Groq API for assessment.")
        if st.button(
            "Assess resume against CRL", type="primary",
            disabled=sidebar_file is None, key=f"sidebar_assess_resume_{widget_scope}",
            use_container_width=True,
        ):
            try:
                resume_text = extract_resume(sidebar_file)
                rubric = role_rubric(
                    sidebar_crl, sidebar_role, sidebar_seniority,
                    role_mapping=resume_data["role_mapping"],
                    competencies=resume_data["competencies"],
                )
                with st.spinner("Scoring mapped role skills..."):
                    scored = analyze_resume(
                        resume_text, sidebar_role, sidebar_seniority, rubric
                    )
                st.session_state["resume_assessment"] = scored
                current_chat["role"] = sidebar_role
                current_chat["messages"].append({
                    "role": "user",
                    "content": f"Score my resume for {sidebar_role} ({sidebar_seniority}).",
                })
                current_chat["messages"].append({
                    "role": "assistant",
                    "content": format_assessment(scored, rubric),
                    "type": "resume_assessment",
                    "assessment": scored,
                    "rubric": rubric,
                })
                st.rerun()
            except Exception as error:
                st.error(f"Resume assessment failed: {error}")

    st.divider()

    if st.button(
        "Clear current chat",
        key="clear_current_chat",
        use_container_width=True,
    ):
        current = st.session_state.chats[
            st.session_state.active_chat_id
        ]
        current["messages"] = []
        current["role"] = None
        current["title"] = "New chat"
        st.rerun()

    st.caption("Conversations are stored in this Streamlit session.")


# ---------------------------------------------------------
# Main chat area
# ---------------------------------------------------------

chat = st.session_state.chats[st.session_state.active_chat_id]
assessment = st.session_state.get("resume_assessment")

st.markdown(
    '<div class="main-title">CRL Career Guidance Assistant</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-title">'
    'See role skills in one list, clear definitions, and an aligned CRL progression.'
    '</div>',
    unsafe_allow_html=True,
)

if chat["role"]:
    st.markdown(
        f'<div class="role-label">Selected role: '
        f'{chat["role"]}</div>',
        unsafe_allow_html=True,
    )
else:
    st.info(
        "Ask for a role in the dataset or a custom role, for example: "
        "**What skills and CRL levels are required for a Data Analyst?** "
        "For custom roles, the assistant proposes a CRL progression from the available competency definitions."
    )


# Resume scoring controls and results live in the sidebar and chat transcript.

# Display existing messages for the selected chat.
for message in chat["messages"]:
    with st.chat_message(message["role"]):
        if message.get("type") == "resume_assessment":
            render_assessment_card(message["assessment"], message["rubric"])
        else:
            st.markdown(message["content"])


# ---------------------------------------------------------
# User input and response
# ---------------------------------------------------------

user_input = st.chat_input(
    "Ask about a role or ask a follow-up question..."
)

if user_input:
    user_message = user_input.strip()

    if user_message:
        # Detect and remember the role when one is mentioned.
        detected_role = detect_role(
            user_message,
            get_role_names(),
        )

        if detected_role:
            chat["role"] = detected_role

        # Update the conversation title from the first message.
        if not chat["messages"]:
            chat["title"] = (
                user_message[:30] + "..."
                if len(user_message) > 30
                else user_message
            )

        # Store the user message before rendering the answer.
        chat["messages"].append({
            "role": "user",
            "content": user_message,
        })

        with st.chat_message("user"):
            st.markdown(user_message)

        with st.chat_message("assistant"):
            if not chat["role"]:
                answer = (
                    "I couldn't identify a role from that message. "
                    "Please name a job title, such as **Data Analyst**, "
                    "**Java Developer**, or **Site Reliability Engineer**. "
                    "For other titles, I can build a proposed skill and CRL map."
                )
                st.markdown(answer)
            else:
                with st.spinner("Checking CRL data and preparing an answer..."):
                    try:
                        # Exclude the latest user message from history,
                        # because it is passed separately as the question.
                        history = chat["messages"][:-1]

                        answer = answer_question(
                            role=chat["role"],
                            question=user_message,
                            history=history,
                            resume_assessment=(
                                assessment
                                if assessment
                                and normalize(assessment.get("role")) == normalize(chat["role"])
                                else None
                            ),
                        )

                        if not isinstance(answer, str):
                            answer = str(answer)

                        if not answer.strip():
                            answer = (
                                "I couldn't generate an answer this time. "
                                "Please try again."
                            )

                    except Exception as error:
                        print(
                            "Chat service error:",
                            type(error).__name__,
                            str(error),
                        )
                        answer = (
                            "I encountered an error while processing "
                            "your question. Please check the terminal "
                            "for details and try again."
                        )

                st.markdown(answer)

        chat["messages"].append({
            "role": "assistant",
            "content": answer,
        })

        st.rerun()
