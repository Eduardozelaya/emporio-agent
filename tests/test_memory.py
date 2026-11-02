"""E5: persistence and the history window.

The window tests are the ones that matter. A window that starts on an orphan `tool` message
makes the provider reject the whole request, and the customer sees a fallback for a bug that
is entirely ours.
"""

from __future__ import annotations

import pytest

from emporio import memory
from emporio.config import Settings
from emporio.memory import trim_to_valid_window


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        llm_api_key=None,
        llm_base_url=None,
        llm_model="test",
        llm_temperature=0.0,
        llm_timeout_s=1,
        max_tool_steps=3,
        history_window=6,
        emporio_today=None,
        data_dir=tmp_path / "data",
    )


def user(text: str) -> dict:
    return {"role": "user", "content": text}


def assistant(text: str) -> dict:
    return {"role": "assistant", "content": text}


def asks_tool(call_id: str, name: str = "get_product") -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}
        ],
    }


def tool_result(call_id: str, name: str = "get_product") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "name": name, "content": "{}"}


# ------------------------------------------------------------------------- persistence


def test_round_trip_preserves_the_wire_format(settings) -> None:
    turn = [
        user("Quanto custa o GD20?"),
        asks_tool("c1"),
        tool_result("c1"),
        assistant("R$ 2.199,00"),
    ]
    memory.append("s1", turn, settings)

    loaded = memory.load_window("s1", settings=settings)
    assert [m["role"] for m in loaded] == ["user", "assistant", "tool", "assistant"]
    assert loaded[1]["tool_calls"][0]["function"]["name"] == "get_product"
    assert loaded[2]["tool_call_id"] == "c1"
    assert loaded[3]["content"] == "R$ 2.199,00"


def test_sessions_are_independent(settings) -> None:
    memory.append("a", [user("oi")], settings)
    memory.append("b", [user("olá"), assistant("opa")], settings)
    assert len(memory.load_window("a", settings=settings)) == 1
    assert len(memory.load_window("b", settings=settings)) == 2


def test_history_survives_a_restart(settings) -> None:
    """DECISIONS D7: a session resumed with --session must still know the conversation."""
    memory.append("s1", [user("Quanto custa o Yamaha C40?"), assistant("R$ 599,90.")], settings)
    # A fresh connection is opened by load_window; nothing is cached in process.
    assert memory.load_window("s1", settings=settings)[0]["content"].startswith("Quanto custa")


def test_appends_keep_their_order(settings) -> None:
    for i in range(5):
        memory.append("s1", [user(f"m{i}")], settings)
    assert [m["content"] for m in memory.load_window("s1", 10, settings)] == [
        "m0", "m1", "m2", "m3", "m4"
    ]


def test_empty_append_is_a_no_op(settings) -> None:
    memory.append("s1", [], settings)
    assert memory.load_window("s1", settings=settings) == []


def test_message_count_and_session_listing(settings) -> None:
    memory.append("s1", [user("a"), assistant("b")], settings)
    memory.append("s2", [user("c")], settings)
    assert memory.message_count("s1", settings) == 2
    assert {row["session_id"] for row in memory.list_sessions(settings)} == {"s1", "s2"}


def test_new_session_ids_are_unique() -> None:
    assert len({memory.new_session_id() for _ in range(100)}) == 100


# ------------------------------------------------------------------- AC5: the window


def test_window_returns_only_the_most_recent(settings) -> None:
    memory.append("s1", [user(f"m{i}") for i in range(10)], settings)
    window = memory.load_window("s1", 4, settings)
    assert [m["content"] for m in window] == ["m6", "m7", "m8", "m9"]


def test_window_never_starts_on_an_orphan_tool_message() -> None:
    """The API rejects a `tool` message whose requesting assistant message is missing."""
    cut = [tool_result("c1"), assistant("R$ 2.199,00"), user("e em 12x?")]
    assert trim_to_valid_window(cut)[0]["role"] == "assistant"
    assert all(m.get("role") != "tool" for m in trim_to_valid_window(cut)[:1])


def test_window_never_ends_on_an_unanswered_tool_request() -> None:
    cut = [user("oi"), assistant("olá"), asks_tool("c1")]
    assert trim_to_valid_window(cut) == [user("oi"), assistant("olá")]


def test_a_whole_tool_group_is_kept_together() -> None:
    intact = [asks_tool("c1"), tool_result("c1"), assistant("pronto")]
    assert trim_to_valid_window(intact) == intact


def test_several_orphan_results_are_all_dropped() -> None:
    cut = [tool_result("c1"), tool_result("c2"), assistant("pronto")]
    assert trim_to_valid_window(cut) == [assistant("pronto")]


def test_a_window_that_is_entirely_a_broken_group_becomes_empty() -> None:
    assert trim_to_valid_window([tool_result("c1")]) == []
    assert trim_to_valid_window([asks_tool("c1")]) == []


def test_real_window_cut_mid_group_is_repaired(settings) -> None:
    """The case that actually happens: the limit lands between a request and its result."""
    memory.append(
        "s1",
        [
            user("Quanto custa o GD20?"),
            asks_tool("c1"),
            tool_result("c1"),
            assistant("R$ 2.199,00"),
            user("e no pix?"),
            asks_tool("c2", "quote_price"),
            tool_result("c2", "quote_price"),
            assistant("R$ 2.089,05"),
        ],
        settings,
    )
    # A window of 6 would start on the `tool` result of the first group.
    window = memory.load_window("s1", 6, settings)
    assert window[0]["role"] != "tool"
    assert [m["role"] for m in window] == ["assistant", "user", "assistant", "tool", "assistant"]


def test_window_of_zero_is_empty(settings) -> None:
    memory.append("s1", [user("oi")], settings)
    assert memory.load_window("s1", 0, settings) == []


def test_window_defaults_to_the_configured_size(settings) -> None:
    memory.append("s1", [user(f"m{i}") for i in range(20)], settings)
    assert len(memory.load_window("s1", settings=settings)) == settings.history_window
