from studydesk.ai.runner import FakeRunner
from tests.test_study_api import app_env  # noqa: F401  (fixture reuse)


def answer(text="Kısa cevap.", terms=()):
    return {"kind": "answer", "answer_md": text, "terms": list(terms), "action": {"type": "none"}}


def use(client, *results):
    runner = FakeRunner(results=list(results))
    client.app_state.runner = runner
    return runner


def command(client, text, **context):
    return client.post("/api/command", json={"text": text, **context})


def test_local_commands_never_reach_claude(app_env):
    client, _, deck_id = app_env
    runner = use(client)
    body = command(client, "sıradaki", deck_id=deck_id, idx=1).json()
    assert body == {"kind": "action", "action": {"type": "next"}, "source": "local"}
    opened = command(client, "101 lec 1 aç").json()["action"]
    assert opened == {"type": "open", "course": "CS 101", "deck_id": deck_id, "idx": 1}
    assert runner.calls == []


def test_question_is_answered_and_kept_with_the_slide(app_env):
    client, _, deck_id = app_env
    runner = use(client, answer("Birinci cevap."), answer("İkinci cevap."))
    first = command(client, "pivot nedir", deck_id=deck_id, idx=2).json()
    assert first["kind"] == "answer" and first["idx"] == 2
    assert set(first["answer"]) == {"question", "answer_md", "terms", "id"}
    command(client, "peki neden", deck_id=deck_id, idx=2)
    assert runner.calls[0].images, "the slide image goes with the question"
    assert "Earlier question: pivot nedir" in runner.calls[1].text
    listed = client.get(f"/api/decks/{deck_id}/slides/2/questions").json()["questions"]
    assert [q["question"] for q in listed] == ["pivot nedir", "peki neden"]
    slides = client.get(f"/api/decks/{deck_id}/slides").json()["slides"]
    assert slides[1]["questions"] == 2


def test_position_prefix_moves_to_that_slide_first(app_env):
    client, _, deck_id = app_env
    runner = use(client, answer())
    body = command(client, "3. slayttayız hoca pivot dedi ne o", deck_id=deck_id, idx=1).json()
    assert body["idx"] == 3 and body["action"] == {"type": "goto_slide", "label": "3"}
    assert "Slide title: Topic 3" in runner.calls[0].text
    assert "Message: hoca pivot dedi ne o" in runner.calls[0].text


def test_claude_can_turn_a_message_into_an_action(app_env):
    client, _, deck_id = app_env
    use(client, {"kind": "action", "answer_md": "", "terms": [], "action": {"type": "open", "course": "CS 101", "lecture": "1"}})
    body = command(client, "tekrardan algoritmalara dönelim", deck_id=deck_id, idx=2).json()
    assert body == {"kind": "action", "action": {"type": "open", "course": "CS 101", "deck_id": deck_id, "idx": 1}, "source": "claude"}


def test_unknown_course_from_claude_becomes_none(app_env):
    client, *_ = app_env
    use(client, {"kind": "action", "answer_md": "", "terms": [], "action": {"type": "open", "course": "NOPE 1"}})
    assert command(client, "uydurma dersi aç bakalım şimdi").json()["action"] == {"type": "none"}


def test_question_without_a_slide_is_answered_but_not_stored(app_env):
    client, _, deck_id = app_env
    runner = use(client, answer())
    body = command(client, "bugün ne çalışsam").json()
    assert body["kind"] == "answer" and "id" not in body["answer"]
    assert runner.calls[0].images == () and "No slide is open." in runner.calls[0].text


def test_empty_message(app_env):
    client, *_ = app_env
    assert command(client, "   ").status_code == 400
