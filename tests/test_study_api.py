"""Explanations and marks through the API, with a fake Claude."""

import pytest
from fastapi.testclient import TestClient

from studydesk.ai.runner import ClaudeError, FakeRunner
from studydesk.config import Config
from studydesk.server import create_app
from tests.pdfgen import make_pdf


def explanation(call):
    slide = call.text.split("Slide title: ")[1].split("\n")[0]
    return {
        "explanation_md": f"About {slide}",
        "summary": f"Summary of {slide}",
        "terms": [{"term": "pivot", "meaning": "eksen", "definition_en": "An element.", "example": "x"}],
        "exam_notes": ["remember this"],
    }


@pytest.fixture
def app_env(home, tmp_path):
    data = tmp_path / "data"
    slides = data / "CS101" / "slides"
    slides.mkdir(parents=True)
    pages = [[f"Topic {i}", f"text {i}", f"A {i}"] for i in range(1, 5)]
    (slides / "Lec1.pdf").write_bytes(make_pdf(pages))
    (data / "courses.toml").write_text('[[courses]]\ncode = "CS 101"\nname = "Algorithms"\nfolder = "CS101"\n')
    runner = FakeRunner(results=[explanation] * 20)
    client = TestClient(create_app(Config(home=home, data_root=data), runner=runner))
    deck_id = client.get("/api/courses/CS 101/decks").json()["decks"][0]["id"]
    return client, runner, deck_id


def explain(client, deck_id, idx, **body):
    return client.post(f"/api/decks/{deck_id}/slides/{idx}/explain", json=body)


def test_explanation_shape_and_cache(app_env):
    client, runner, deck_id = app_env
    first = explain(client, deck_id, 1).json()
    assert set(first) == {"idx", "level", "variant", "explanation_md", "summary", "terms", "exam_notes", "cached"}
    assert first["cached"] is False and first["explanation_md"] == "About Topic 1"
    second = explain(client, deck_id, 1).json()
    assert second["cached"] is True and len(runner.calls) == 1
    explain(client, deck_id, 1, refresh=True)
    assert len(runner.calls) == 2


def test_levels_are_cached_separately_and_set_effort(app_env):
    client, runner, deck_id = app_env
    explain(client, deck_id, 1, level="short")
    explain(client, deck_id, 1, level="detailed")
    assert [c.effort for c in runner.calls] == ["low", "medium"]
    assert runner.calls[0].images and runner.calls[0].images[0].suffix == ".png"


def test_previous_slide_summary_is_passed_on(app_env):
    client, runner, deck_id = app_env
    explain(client, deck_id, 1)
    explain(client, deck_id, 2)
    assert "Previous slide: Summary of Topic 1" in runner.calls[1].text


def test_different_variant_sees_the_earlier_explanation(app_env):
    client, runner, deck_id = app_env
    explain(client, deck_id, 2)
    result = explain(client, deck_id, 2, variant="different").json()
    assert result["variant"] == "different"
    assert "About Topic 2" in runner.calls[-1].text


def test_bad_level_and_claude_errors(app_env):
    client, runner, deck_id = app_env
    assert explain(client, deck_id, 1, level="huge").status_code == 400
    runner.results.insert(0, ClaudeError("limit", "usage limit reached"))
    response = explain(client, deck_id, 3)
    assert response.status_code == 503 and response.json()["error"]["code"] == "limit"
    assert explain(client, deck_id, 99).json()["error"]["code"] == "slide_not_found"


def test_known_mark_round_trip(app_env):
    client, _, deck_id = app_env
    assert client.put(f"/api/decks/{deck_id}/slides/2/marks/known").json() == {"idx": 2, "marks": ["known"]}
    slides = client.get(f"/api/decks/{deck_id}/slides").json()["slides"]
    assert slides[1]["marks"] == ["known"] and slides[0]["marks"] == []
    assert client.delete(f"/api/decks/{deck_id}/slides/2/marks/known").json()["marks"] == []
    assert client.put(f"/api/decks/{deck_id}/slides/2/marks/bogus").status_code == 400


def test_flow_open_explain_skip_back(app_env):
    """Flow: open the course, explain slide 1, mark 2 as known and skip, explain 3, go back to 1 (cached)."""
    client, runner, deck_id = app_env
    assert client.get("/api/courses").json()["courses"][0]["code"] == "CS 101"
    explain(client, deck_id, 1)
    client.put(f"/api/decks/{deck_id}/slides/2/marks/known")
    explain(client, deck_id, 3)
    again = explain(client, deck_id, 1).json()
    slides = client.get(f"/api/decks/{deck_id}/slides").json()["slides"]
    assert again["cached"] is True
    assert [s["explained"] for s in slides] == [True, False, True, False]
    assert len(runner.calls) == 2


def test_study_page_assets_are_served(app_env):
    client, *_ = app_env
    for path in ("/", "/js/app.js", "/js/study.js", "/vendor/katex/katex.min.js", "/vendor/marked/marked.esm.js"):
        assert client.get(path).status_code == 200, path


def test_pages_are_revalidated_but_api_is_not_touched(app_env):
    client, *_ = app_env
    assert client.get("/js/study.js").headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/api/health").headers
