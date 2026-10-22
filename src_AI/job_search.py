
import re

from src_AI.data_loader import load_all_data


def normalize(value):
    """Normalize role text for comparison."""
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value).strip().casefold(),
    )


def find_role(role_query):
    """
    Find a role in role_mapping.csv.

    Returns:
        A mapping dictionary for a unique role.
        None if no role matches.
        An ambiguity dictionary if multiple roles match.
    """
    query = normalize(role_query)

    if not query:
        return None

    data = load_all_data()
    mapping = data["role_mapping"].copy()

    role_column = "Fresher role"

    if role_column not in mapping.columns:
        raise ValueError(
            f"Missing required column: {role_column}"
        )

    mapping["_role_key"] = (
        mapping[role_column].fillna("").map(normalize)
    )

    # Exact matching takes priority.
    exact = mapping[mapping["_role_key"] == query]

    if len(exact) == 1:
        return exact.iloc[0].drop(
            labels=["_role_key"]
        ).to_dict()

    if len(exact) > 1:
        return {
            "ambiguous": True,
            "matches": sorted(
                exact[role_column].dropna().astype(str).unique().tolist()
            ),
        }

    # Partial matching is permitted only when the result is unique.
    partial = mapping[
        mapping["_role_key"].apply(
            lambda name: bool(name)
            and (query in name or name in query)
        )
    ]

    unique_roles = (
        partial[role_column]
        .dropna()
        .astype(str)
        .drop_duplicates()
        .tolist()
    )

    if len(unique_roles) == 1:
        matched = partial[
            partial[role_column].astype(str) == unique_roles[0]
        ]

        if len(matched) == 1:
            return matched.iloc[0].drop(
                labels=["_role_key"]
            ).to_dict()

        return {
            "ambiguous": True,
            "matches": unique_roles,
        }

    if len(unique_roles) > 1:
        return {
            "ambiguous": True,
            "matches": sorted(unique_roles),
        }

    return None
