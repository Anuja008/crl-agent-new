import pandas as pd

import src_AI.chat_service as chat_service
from src_AI.data_loader import load_all_data
from src_AI.job_search import find_role
from src_AI.rag_retriever import retrieve_role_context


def test_java_and_python_mapping_ids_and_crls(monkeypatch):
    data = load_all_data()
    expected = {
        "Java Developer": {
            "Primary": ["R01", "R02", "R03"],
            "Secondary": ["R20"],
        },
        "Python Developer": {
            "Primary": ["R01", "R02"],
            "Secondary": ["R03"],
        },
    }
    monkeypatch.setattr(
        chat_service,
        "explain_competency",
        lambda name, definition, includes=None: definition,
    )

    for role, categories in expected.items():
        result = retrieve_role_context(role, data=data)
        assert result["found"] is True
        for category, competency_ids in categories.items():
            entries = result["categories"][category]
            assert [entry["competency_id"] for entry in entries] == competency_ids
            for entry in entries:
                assert entry["name"]
                assert entry["definition"]
                assert len(entry["crl_records"]) == 5
                assert all(record["CRL"] for record in entry["crl_records"])
                assert all(record["Level name"] for record in entry["crl_records"])
                assert all(record["scale"] for record in entry["crl_records"])
                assert all(record["Description"] for record in entry["crl_records"])
                assert all(
                    record["Observable signs"] for record in entry["crl_records"]
                )
                assert all(record["Typical task"] for record in entry["crl_records"])

        answer = chat_service.render_role_mapping(result)
        assert "Core Competencies" not in answer
        assert "## Skills and Competencies Required" in answer
        assert "## CRL Mapping and Definitions" in answer
        for competency_id in categories["Primary"] + categories["Secondary"]:
            assert f"({competency_id})" in answer
        for entry in result["competencies"]:
            assert f"- **Definition:** {entry['definition']}" in answer
            assert entry["crl_records"][0]["Description"] in answer
            assert (
                f"- **What the CRL Level Means:** "
                f"{entry['crl_records'][0]['Description']}"
            ) in answer
        for level in range(1, 6):
            assert f"CRL {level}" in answer
        assert "**Observable Evidence:**" in answer
        assert "**CRL Scale Minimum Evidence:**" in answer
        assert "**What the CRL Level Means:**" in answer
        assert "**Typical Task:**" in answer


def test_role_alias_is_validated_against_dataset():
    role = find_role("java dev")
    assert role["Fresher role"] == "Java Developer"


def test_role_lookup_does_not_guess_from_partial_titles():
    assert find_role("Developer") is None


def test_unresolved_mapping_is_reported_without_guessing(monkeypatch):
    data = load_all_data()
    data["role_mapping"] = data["role_mapping"].copy()
    row_index = data["role_mapping"].index[
        data["role_mapping"]["Fresher role"] == "Java Developer"
    ][0]
    data["role_mapping"].loc[
        row_index, "Primary role competencies"
    ] = "R999"
    data["role_mapping"].loc[
        row_index, "Secondary role competencies"
    ] = ""

    result = retrieve_role_context("Java Developer", data=data)
    assert result["unresolved"] == [{"category": "Primary", "value": "R999"}]
    monkeypatch.setattr(
        chat_service,
        "explain_competency",
        lambda name, definition, includes=None: definition,
    )
    answer = chat_service.render_role_mapping(result)
    assert "Unresolved competency ID: R999" in answer
    assert "Competency: R999" not in answer
    assert "name and definition are not inferred" in answer


def test_missing_crl_fields_are_explicit_in_follow_up_context():
    data = load_all_data()
    data["crl_descriptions"] = data["crl_descriptions"].copy()
    crl_row = data["crl_descriptions"].index[
        (data["crl_descriptions"]["Role"] == "Java Developer")
        & (data["crl_descriptions"]["Competency ID"] == "R01")
        & (data["crl_descriptions"]["CRL"] == "CRL 1")
    ][0]
    data["crl_descriptions"].loc[
        crl_row, ["Description", "Observable signs"]
    ] = ""
    data["crl_scale"] = data["crl_scale"].copy()
    scale_row = data["crl_scale"].index[
        data["crl_scale"]["CRL"] == "CRL 1"
    ][0]
    data["crl_scale"].loc[scale_row, "Universal meaning (locked)"] = ""

    result = retrieve_role_context("Java Developer", data=data)

    assert (
        "Role-specific CRL description: The role-specific CRL dataset "
        "does not provide this field."
    ) in result["context"]
    assert (
        "Observable signs: The role-specific CRL dataset does not provide "
        "this field."
    ) in result["context"]
    assert (
        "CRL scale — Universal meaning (locked): The CRL scale does not "
        "provide this field for this level."
    ) in result["context"]


def test_initial_role_answer_uses_complete_dataset_mapping(monkeypatch):
    monkeypatch.setattr(
        chat_service,
        "generate_answer",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Initial mappings must not be left to free-form output.")
        ),
    )

    answer = chat_service.answer_question(
        "Java Developer",
        "Tell me about Java Developer.",
        initial_role=True,
    )

    assert "## Skills and Competencies Required" in answer
    assert "## CRL Mapping and Definitions" in answer
    assert "R20" in answer
    assert "Core Competencies" not in answer


def test_follow_up_uses_active_role_context_and_history(monkeypatch):
    captured = {}

    def fake_generate_answer(role, question, context, history):
        captured.update(
            role=role,
            question=question,
            context=context,
            history=history,
        )
        return "A grounded follow-up."

    monkeypatch.setattr(chat_service, "generate_answer", fake_generate_answer)
    answer = chat_service.answer_question(
        "Python Developer",
        "Explain R01 more simply.",
        history=[{"role": "user", "content": "Python Developer"}],
    )

    assert answer == "A grounded follow-up."
    assert captured["role"] == "Python Developer"
    assert captured["question"] == "Explain R01 more simply."
    assert "R01 Programming" in captured["context"]
    assert "CRL scale — Universal meaning (locked):" in captured["context"]
    assert "Observable signs:" in captured["context"]
    assert "Typical task:" in captured["context"]
    assert captured["history"][0]["content"] == "Python Developer"
