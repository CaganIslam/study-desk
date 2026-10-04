from studydesk.ai.runner import FakeRunner
from studydesk.study.terms import normalise
from tests.test_study_api import app_env, explain  # noqa: F401  (fixture reuse)


def test_normalise():
    assert normalise("PLA (Perceptron Learning Algorithm)") == "pla"
    assert normalise("Valuations") == normalise("valuation")
    assert normalise("class") == "class"
    assert normalise("Düzenlileştirme") == "duzenlilestirme"


def terms_api(client, **params):
    return client.get("/api/terms", params=params).json()["terms"]


def test_terms_from_explanations_are_captured_once(app_env):
    client, _, deck_id = app_env
    explain(client, deck_id, 1)
    client.app_state.jobs.join()  # slide 2 prefetched: the same "pivot" term again
    found = terms_api(client)
    assert [(t["term"], t["status"], t["courses"]) for t in found] == [("pivot", "new", ["CS 101"])]
    card = client.get(f"/api/terms/{found[0]['id']}").json()
    assert set(card) == {"id", "term", "meaning", "definition_en", "example", "status", "courses", "seen"}
    assert {(s["idx"], s["source"]) for s in card["seen"]} == {(1, "explanation"), (2, "explanation")}


def test_asking_makes_a_term_hard_and_knowing_a_slide_makes_it_known(app_env):
    client, _, deck_id = app_env
    client.app_state.runner = FakeRunner(
        results=[
            {"kind": "answer", "answer_md": "x", "action": {"type": "none"},
             "terms": [{"term": "Heap", "meaning": "yığın", "definition_en": "A tree.", "example": "e"}]},
        ]
    )  # fmt: skip
    client.post("/api/command", json={"text": "heap nedir", "deck_id": deck_id, "idx": 3})
    assert terms_api(client, status="hard")[0]["term"] == "Heap"

    from tests.test_study_api import explained

    client.app_state.runner = FakeRunner(results=[explained] * 10)
    explain(client, deck_id, 4)
    client.put(f"/api/decks/{deck_id}/slides/4/marks/known")
    assert [t["term"] for t in terms_api(client, status="known")] == ["pivot"]
    assert [t["term"] for t in terms_api(client, status="hard")] == ["Heap"]  # hard stays hard


def test_known_terms_are_sent_with_the_next_explanation(app_env):
    client, runner, deck_id = app_env
    explain(client, deck_id, 1)
    client.app_state.jobs.join()
    client.put(f"/api/decks/{deck_id}/slides/1/marks/known")
    explain(client, deck_id, 4)
    client.app_state.jobs.join()
    call = next(c for c in runner.calls if "Slide title: Topic 4" in c.text)
    assert "The student already knows these" in call.text and "pivot" in call.text


def test_lookup_status_change_and_errors(app_env):
    client, _, deck_id = app_env
    explain(client, deck_id, 1)
    card = client.get("/api/terms/lookup", params={"term": "Pivot"}).json()
    assert card["term"] == "pivot"
    updated = client.patch(f"/api/terms/{card['id']}", json={"status": "hard"}).json()
    assert updated["status"] == "hard"
    assert client.patch(f"/api/terms/{card['id']}", json={"status": "famous"}).status_code == 400
    assert client.get("/api/terms/9999").json()["error"]["code"] == "term_not_found"
    assert client.get("/api/terms/lookup", params={"term": "nothing"}).status_code == 404
    assert terms_api(client, q="piv")[0]["term"] == "pivot" and terms_api(client, course="OTHER") == []


def test_terms_page_assets(app_env):
    client, *_ = app_env
    assert client.get("/js/terms.js").status_code == 200


def test_backfill_captures_older_explanations_once(app_env):
    client, _, deck_id = app_env
    explain(client, deck_id, 1)
    db = client.app_state.db
    with db.connect() as conn:
        conn.execute("DELETE FROM terms")
    from studydesk.study import terms

    assert terms.backfill(db) >= 1 and terms_api(client)[0]["term"] == "pivot"
    assert terms.backfill(db) == 0
