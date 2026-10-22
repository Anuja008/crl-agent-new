from pathlib import Path

from streamlit.testing.v1 import AppTest

import src_AI.chat_service as chat_service


APP_PATH = Path(__file__).resolve().parents[1] / "AI chatbot" / "app.py"


def test_new_chat_isolated_and_switching_restores_role(monkeypatch):
    monkeypatch.setattr(chat_service, "GROQ_API_KEY", None)
    app = AppTest.from_file(str(APP_PATH), default_timeout=60).run()

    app.chat_input[0].set_value("Java Developer").run()
    java_chat_id = app.session_state["active_chat_id"]
    java_chat = app.session_state["chats"][java_chat_id]
    assert java_chat["role"] == "Java Developer"
    assert all(
        competency_id in java_chat["messages"][-1]["content"]
        for competency_id in ("R01", "R02", "R03", "R20")
    )

    app.sidebar.button(key="new_chat").click().run()
    python_chat_id = app.session_state["active_chat_id"]
    assert python_chat_id != java_chat_id
    assert app.session_state["chats"][python_chat_id]["messages"] == []

    app.chat_input[0].set_value("Python Developer").run()
    python_chat = app.session_state["chats"][python_chat_id]
    assert python_chat["role"] == "Python Developer"
    assert all(
        competency_id in python_chat["messages"][-1]["content"]
        for competency_id in ("R01", "R02", "R03")
    )

    app.sidebar.button(key=f"chat_{java_chat_id}").click().run()
    assert app.session_state["active_chat_id"] == java_chat_id
    assert app.session_state["chats"][java_chat_id] == java_chat
    assert app.session_state["chats"][python_chat_id]["role"] == "Python Developer"
    assert not app.exception
