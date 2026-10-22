
from src_AI.rag_retriever import retrieve_context, retrieve_role_context
from src_AI.llm_client import GROQ_API_KEY, generate_answer


def answer_question(role, question, history=None, resume_assessment=None):
    """Coordinate role matching, evidence retrieval, and answer generation."""

    role = (role or "").strip()
    question = (question or "").strip()

    if not role:
        return "Please enter a job role first."

    if not question:
        return "Please enter a question."

    try:
        result = retrieve_role_context(
            role=role,
            question=question,
        )

        if not result.get("found"):
            return result.get(
                "context",
                "The role could not be resolved in the CRL dataset.",
            )

        context = result.get("context", "")

        if not context.strip():
            return (
                "No relevant CRL evidence was retrieved for this role. "
                "I cannot provide a reliable mapping without source data."
            )

        if result.get("exact_mapping"):
            try:
                retrieved = retrieve_context(role, question, top_k=5)
                if retrieved:
                    context += "\n\nSUPPLEMENTARY CHROMA RETRIEVAL\n" + retrieved
            except Exception as error:
                # The complete structured role context remains available if
                # the optional semantic index cannot be opened.
                print(
                    f"Chroma retrieval error: {type(error).__name__}: {error}",
                    flush=True,
                )

        if not GROQ_API_KEY:
            return context

        return generate_answer(
            role=result["role"],
            question=question,
            context=context,
            history=history or [],
            resume_assessment=resume_assessment,
        )

    except Exception as error:
        print(
            f"Career chatbot error: {type(error).__name__}: {error}",
            flush=True,
        )

        return (
            "I couldn't retrieve the role's CRL evidence. "
            "Check the terminal for the detailed error."
        )
