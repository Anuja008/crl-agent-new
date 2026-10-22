
from functools import lru_cache
from pathlib import Path
import re
import hashlib

import pandas as pd
import chromadb
from sentence_transformers import SentenceTransformer

from src_AI.data_loader import load_all_data
from src_AI.job_search import find_role


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VECTOR_DIR = PROJECT_ROOT / "vector_store"
COLLECTION_NAME = "crl_career_knowledge_v2"
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

def clean(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def normalize(value):
    return " ".join(clean(value).casefold().split())


def split_values(value):
    """Split mapping cells while preserving each competency label."""
    text = clean(value)

    if not text or text.casefold() == "nan":
        return []

    return [
        item.strip()
        for item in re.split(r"[,;\n|]+", text)
        if item.strip()
    ]


def build_documents(data):
    """Build the CRL index from competency and level data, excluding job ads."""
    documents = []

    for index, row in data["crl_descriptions"].iterrows():
        role = clean(row.get("Role"))
        competency = clean(row.get("Competency"))

        if not competency:
            continue

        text = "\n".join([
            "Document type: CRL competency guidance",
            f"Role: {role}",
            f"Competency ID: {clean(row.get('Competency ID'))}",
            f"Competency: {competency}",
            f"CRL: {clean(row.get('CRL'))}",
            f"Level name: {clean(row.get('Level name'))}",
            f"Description: {clean(row.get('Description'))}",
            f"Observable signs: {clean(row.get('Observable signs'))}",
            f"Typical task: {clean(row.get('Typical task'))}",
            f"Rule note: {clean(row.get('Rule note'))}",
        ])

        documents.append({
            "id": f"crl_{index}",
            "text": text,
            "metadata": {
                "source": "crl_description",
                "role": role[:500] or "General",
                "seniority": clean(row.get("Seniority"))[:100],
                "competency": competency[:500],
            },
        })

    for index, row in data["competencies"].iterrows():
        competency = clean(row.get("Competency"))

        if not competency:
            continue

        text = "\n".join([
            "Document type: Competency dictionary",
            f"Competency ID: {clean(row.get('ID'))}",
            f"Competency: {competency}",
            f"Definition: {clean(row.get('Definition'))}",
            f"Includes: {clean(row.get('Includes'))}",
            f"Excludes: {clean(row.get('Excludes (belongs elsewhere)'))}",
            f"Role families: {clean(row.get('Role families'))}",
            f"Typical tools: {clean(row.get('Typical tools'))}",
            f"Example fresher tasks: {clean(row.get('Example fresher tasks'))}",
        ])

        documents.append({
            "id": f"competency_{index}",
            "text": text,
            "metadata": {
                "source": "competency_dictionary",
                "role": "General",
                "competency": competency[:500],
            },
        })

    for index, row in data["crl_scale"].iterrows():
        level = clean(row.get("CRL"))
        if not level:
            continue
        text = "\n".join([
            "Document type: Universal CRL scale",
            f"CRL: {level}",
            f"Level name: {clean(row.get('Level name'))}",
            f"Meaning: {clean(row.get('Universal meaning (locked)'))}",
            f"Independence: {clean(row.get('Independence'))}",
            f"Minimum evidence: {clean(row.get('Minimum evidence'))}",
            f"Typical assessment types: {clean(row.get('Typical assessment types'))}",
        ])
        documents.append({
            "id": f"crl_scale_{index}",
            "text": text,
            "metadata": {
                "source": "crl_scale",
                "role": "General",
                "competency": level,
            },
        })

    return documents


@lru_cache(maxsize=1)
def get_vector_store():
    """Load the embedding model and persistent ChromaDB collection."""
    data = load_all_data()
    documents = build_documents(data)
    fingerprint = hashlib.sha256(
        "\n".join(doc["id"] + doc["text"] for doc in documents).encode("utf-8")
    ).hexdigest()

    VECTOR_DIR.mkdir(parents=True, exist_ok=True)

    model = SentenceTransformer(EMBEDDING_MODEL)
    client = chromadb.PersistentClient(path=str(VECTOR_DIR))

    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    existing_fingerprint = (collection.metadata or {}).get("source_fingerprint")
    existing_count = collection.count()
    if (
        existing_fingerprint != fingerprint
        or existing_count not in (0, len(documents))
    ):
        client.delete_collection(COLLECTION_NAME)
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={
                "hnsw:space": "cosine",
                "source_fingerprint": fingerprint,
            },
        )

    if collection.count() == 0 and documents:
        batch_size = 64

        for start in range(0, len(documents), batch_size):
            batch = documents[start:start + batch_size]

            embeddings = model.encode(
                [doc["text"] for doc in batch],
                normalize_embeddings=True,
                show_progress_bar=False,
            ).tolist()

            collection.add(
                ids=[doc["id"] for doc in batch],
                documents=[doc["text"] for doc in batch],
                metadatas=[doc["metadata"] for doc in batch],
                embeddings=embeddings,
            )

            print(
                f"Indexed {min(start + batch_size, len(documents))}"
                f"/{len(documents)} records",
                flush=True,
            )

    return model, collection


def retrieve_context(role, question, top_k=5):
    """Semantic retrieval for supplementary explanatory evidence."""
    model, collection = get_vector_store()

    query = f"Role: {role}\nQuestion: {question}"
    embedding = model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
    ).tolist()

    count = collection.count()

    if count == 0:
        return ""

    results = collection.query(
        query_embeddings=embedding,
        n_results=min(top_k, count),
        include=["documents", "metadatas", "distances"],
    )

    records = []

    for document, metadata in zip(
        results["documents"][0],
        results["metadatas"][0],
    ):
        source = metadata.get("source", "")
        record_role = metadata.get("role", "")

        # Do not mix in CRL descriptions for other roles.
        if source == "crl_description":
            if normalize(record_role) != normalize(role):
                continue
            if normalize(metadata.get("seniority", "")) != "fresher":
                continue

        # Job postings are not required for exact CRL mapping.
        if source == "job_posting":
            continue

        records.append(document)

    return "\n\n---\n\n".join(records)


def retrieve_role_context(role, question=""):
    """
    Resolve the exact role mapping and produce verified context.

    Primary and secondary role competencies are included in one list.
    Structured CSV data is authoritative for mappings and CRL levels.
    """

    mapping = find_role(role)

    if mapping is None:
        return build_unmapped_role_context(role)

    if mapping.get("ambiguous"):
        matches = mapping.get("matches", [])
        return {
            "found": False,
            "role": None,
            "context": (
                "The role query is ambiguous. Ask the user to select "
                "one exact role from: " + ", ".join(matches)
            ),
        }

    data = load_all_data()

    mapped_role = clean(mapping.get("Fresher role"))
    dictionary = data["competencies"].copy()
    descriptions = data["crl_descriptions"].copy()

    dictionary["_id_key"] = dictionary["ID"].map(normalize)
    dictionary["_name_key"] = dictionary["Competency"].map(normalize)

    descriptions["_role_key"] = descriptions["Role"].map(normalize)
    descriptions["_id_key"] = descriptions["Competency ID"].map(normalize)
    descriptions["_name_key"] = descriptions["Competency"].map(normalize)
    descriptions["_family_key"] = descriptions["Role family"].map(normalize)
    descriptions["_seniority_key"] = descriptions["Seniority"].map(normalize)

    categories = [
        ("Primary role competencies", "Primary"),
        ("Secondary role competencies", "Secondary"),
    ]

    sections = [
        f"ROLE: {mapped_role}",
        "Only competencies from the primary and secondary role-mapping fields are included, together in one list.",
    ]

    for column in ("Role objective", "Typical tools"):
        value = clean(mapping.get(column))
        if value and value.casefold() != "nan":
            sections.append(f"{column}: {value}")

    resolved = []
    unresolved = []

    sections.append("\nALL MAPPED ROLE SKILLS")

    for column, category in categories:
        values = split_values(mapping.get(column, ""))

        if not values:
            continue

        for value in values:
            key = normalize(value)

            # Support a label such as "Project Coordination (R20)".
            id_match = re.search(r"\(([A-Za-z]+\d+)\)", value)
            possible_id = normalize(id_match.group(1)) if id_match else key

            by_id = dictionary[dictionary["_id_key"] == possible_id]
            by_name = dictionary[dictionary["_name_key"] == key]

            if by_id.empty and by_name.empty:
                unresolved.append((category, value))
                sections.append(
                    f"\nUnresolved competency mapping: {value}. "
                    "No exact competency ID or name match was found."
                )
                continue

            row = by_id.iloc[0] if not by_id.empty else by_name.iloc[0]

            competency_id = clean(row.get("ID"))
            competency_name = clean(row.get("Competency"))

            resolved.append({
                "category": category,
                "id": competency_id,
                "name": competency_name,
            })

            sections.append(
                f"\nPriority: {category} (from role mapping)\n"
                f"Competency: {competency_name} ({competency_id})"
            )

            for field in (
                "Definition",
                "Includes",
                "Example fresher tasks",
            ):
                value_text = clean(row.get(field))
                if value_text and value_text.casefold() != "nan":
                    sections.append(f"{field}: {value_text}")

    # Include each competency's complete role-specific CRL 1-5 progression.
    sections.append("\nROLE-SPECIFIC CRL MAPPINGS")

    role_records = descriptions[
        (descriptions["_role_key"] == normalize(mapped_role))
        & (descriptions["_family_key"] == normalize(mapping.get("Role family")))
        & (descriptions["_seniority_key"] == "fresher")
    ]

    if not role_records.empty:
        for competency in resolved:
            matched = role_records[
                (
                    role_records["_id_key"] == normalize(competency["id"])
                )
                |
                (
                    role_records["_name_key"] == normalize(competency["name"])
                )
            ]

            if matched.empty:
                sections.append(
                    f"\nGenerate a proposed CRL 1-5 progression for "
                    f"{competency['name']} ({competency['id']}) using the "
                    "universal scale, competency definition, role objective, "
                    "and Google research supplied separately."
                )
                continue

            sections.append(
                f"\nCRL records for {competency['name']} "
                f"({competency['id']}):"
            )

            present_levels = set()
            for _, row in matched.iterrows():
                level = clean(row.get("CRL"))
                match_level = re.search(r"\d+", level)
                if match_level:
                    present_levels.add(int(match_level.group()))
                sections.append(
                    "\n".join([
                        f"{level or 'CRL not provided'} — {clean(row.get('Level name')) or 'Level name not provided'}",
                        f"What this looks like: {clean(row.get('Description')) or 'Not provided'}",
                    ])
                )
            missing_levels = sorted(set(range(1, 6)) - present_levels)
            if missing_levels:
                sections.append(
                    f"Generate proposed descriptions for missing CRL levels "
                    f"{', '.join(map(str, missing_levels))} for "
                    f"{competency['name']} ({competency['id']}) using the "
                    "universal scale, role objective, competency definition, "
                    "and Google research supplied separately."
                )

    else:
        sections.append(
            "Generate a proposed role-specific CRL progression for each mapped "
            "competency using the universal scale, competency definitions, "
            "role objective, and Google research supplied separately. Do not "
            "reuse another role's CRL descriptions as exact role evidence."
        )

    # The same universal scale applies when a role-specific competency level
    # is absent; it anchors generated progressions in the project's CRL framework.
    sections.append("\nUNIVERSAL CRL SCALE")
    for _, row in data["crl_scale"].iterrows():
        level = clean(row.get("CRL"))
        if level:
            sections.append("\n".join([
                f"{level} — {clean(row.get('Level name'))}",
                f"Meaning: {clean(row.get('Universal meaning (locked)'))}",
                f"Independence: {clean(row.get('Independence'))}",
                f"Minimum evidence: {clean(row.get('Minimum evidence'))}",
            ]))

    return {
        "found": True,
        "role": mapped_role,
        "exact_mapping": True,
        "competencies": resolved,
        "unresolved": unresolved,
        "context": "\n\n".join(sections),
    }


def build_unmapped_role_context(role):
    """Provide the role, competency catalogue, and CRL scale for a proposed map."""
    data = load_all_data()
    dictionary = data["competencies"]
    sections = [
        f"REQUESTED ROLE: {clean(role)}",
        "Use the competency catalogue below to select relevant skills, then generate a proposed role-specific CRL 1-5 progression for each selected skill. Exclude core competencies. Ground every level in the universal scale, role duties, competency definition, and Google research supplied separately.",
        "\nUNIVERSAL CRL SCALE",
    ]

    for _, row in data["crl_scale"].iterrows():
        level = clean(row.get("CRL"))
        if not level:
            continue
        scale_parts = [
            f"{level} — {clean(row.get('Level name'))}",
            f"Meaning: {clean(row.get('Universal meaning (locked)'))}",
            f"Independence: {clean(row.get('Independence'))}",
            f"Minimum evidence: {clean(row.get('Minimum evidence'))}",
        ]
        sections.append("\n".join(part for part in scale_parts if not part.endswith(": ")))

    sections.append(
        "\nCOMPLETE COMPETENCY CATALOGUE",
    )

    for _, row in dictionary.iterrows():
        competency_id = clean(row.get("ID"))
        name = clean(row.get("Competency"))
        if not competency_id or not name:
            continue
        sections.append(
            "\n".join([
                f"{competency_id} — {name} ({clean(row.get('Type')) or 'Type not provided'})",
                f"Definition: {clean(row.get('Definition'))}",
                f"Skills included: {clean(row.get('Includes'))}",
                f"Typical tools: {clean(row.get('Typical tools'))}",
                f"Example entry-level task: {clean(row.get('Example fresher tasks'))}",
            ])
        )

    return {
        "found": True,
        "role": clean(role),
        "exact_mapping": False,
        "competencies": [],
        "unresolved": [],
        "context": "\n\n".join(sections),
    }
