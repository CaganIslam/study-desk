import json
import stat
import sys

import pytest

from studydesk.ai.runner import ClaudeCall, ClaudeCLI, ClaudeError, FakeRunner
from studydesk.ai.tutor import EFFORT, Exchange, SlideContext, answer_call, explain_call

# --- runner --------------------------------------------------------------------

FAKE_CLAUDE = """#!{python}
import json, os, sys, time
stdin = sys.stdin.read()
json.loads(stdin)                      # the message must be valid JSON
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
if mode == "sleep":
    time.sleep(5)
elif mode == "garbage":
    print("Error: something broke", file=sys.stderr)
    sys.exit(1)
else:
    print(json.dumps({{"type": "system", "subtype": "init"}}))
    result = {{"type": "result", "is_error": mode != "ok", "duration_ms": 1234, "total_cost_usd": 0.01}}
    if mode == "ok":
        result["structured_output"] = {{"echo_args": sys.argv[1:], "has_image": '"image"' in stdin}}
    elif mode == "login":
        result["result"] = "Invalid API key · Please run /login"
    elif mode == "limit":
        result["result"] = "Claude usage limit reached. Your limit will reset at 5pm."
    elif mode == "nostruct":
        result["is_error"] = False
    print(json.dumps(result))
"""


@pytest.fixture
def fake_claude(tmp_path):
    path = tmp_path / "claude"
    path.write_text(FAKE_CLAUDE.format(python=sys.executable))
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return ClaudeCLI(executable=str(path))


def call(**kwargs):
    defaults = dict(system="sys", text="hello", schema={"type": "object"})
    return ClaudeCall(**{**defaults, **kwargs})


def test_command_is_locked_down():
    cmd = ClaudeCLI().command(call(model="sonnet", effort="low"))
    for flag in ("-p", "--safe-mode", "--no-session-persistence", "--json-schema"):
        assert flag in cmd
    assert cmd[cmd.index("--tools") + 1] == ""
    assert cmd[cmd.index("--input-format") + 1] == "stream-json"
    assert cmd[cmd.index("--model") + 1] == "sonnet" and cmd[cmd.index("--effort") + 1] == "low"
    assert "--model" not in ClaudeCLI().command(call())


def test_success_returns_structured_output(fake_claude, tmp_path):
    image = tmp_path / "slide.png"
    image.write_bytes(b"\x89PNG fake")
    result = fake_claude.run(call(images=(image,)))
    assert result.data["has_image"] is True
    assert result.duration_ms == 1234 and result.cost_usd == 0.01


@pytest.mark.parametrize(
    "mode, code", [("login", "not_logged_in"), ("limit", "limit"), ("garbage", "failed"), ("nostruct", "bad_output")]
)
def test_failures_are_classified(fake_claude, monkeypatch, mode, code):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    with pytest.raises(ClaudeError) as error:
        fake_claude.run(call())
    assert error.value.code == code


def test_timeout(fake_claude, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "sleep")
    with pytest.raises(ClaudeError) as error:
        fake_claude.run(call(timeout=0.5))
    assert error.value.code == "timeout"


def test_missing_executable():
    with pytest.raises(ClaudeError) as error:
        ClaudeCLI(executable="/nonexistent/claude").run(call())
    assert error.value.code == "not_installed"


def test_fake_runner_scripts_results():
    runner = FakeRunner(results=[{"a": 1}, ClaudeError("limit", "x"), lambda c: {"text": c.text}])
    assert runner.run(call()).data == {"a": 1}
    with pytest.raises(ClaudeError):
        runner.run(call())
    assert runner.run(call(text="hi")).data == {"text": "hi"}
    assert len(runner.calls) == 3


# --- tutor prompts --------------------------------------------------------------

CTX = SlideContext(
    course_code="CS 101",
    course_name="Algorithms",
    deck="Lec02.pdf",
    label="24",
    idx=20,
    total=34,
    title="Why does it work",
    text="Some slide text",
    week_topic="Sorting",
    previous_summary="Defined the update rule.",
    known_terms=("vector", "dot product"),
)


def test_explain_call_carries_the_context():
    c = explain_call(CTX, level="normal", language="tr")
    assert "Turkish" in c.system and "{language}" not in c.system
    for piece in ("CS 101 Algorithms", "slide 24 (20 of 34)", "Sorting", "Defined the update rule.", "vector, dot product", "80-150 words"):
        assert piece in c.text
    assert c.effort == EFFORT["normal"]
    assert set(c.schema["required"]) == {"explanation_md", "summary", "terms", "exam_notes"}


def test_levels_and_variants():
    assert explain_call(CTX, level="detailed").effort == "medium"
    simpler = explain_call(CTX, variant="simpler")
    assert "from zero" in simpler.text
    different = explain_call(
        SlideContext(**{**CTX.__dict__, "previous_explanation": "OLD TEXT"}), variant="different"
    )
    assert "OLD TEXT" in different.text
    with pytest.raises(ValueError):
        explain_call(CTX, level="huge")
    with pytest.raises(ValueError):
        explain_call(CTX, variant="poem")


def test_last_slide_is_flagged():
    last = SlideContext(**{**CTX.__dict__, "idx": 34})
    assert "the last slide" in explain_call(last).text


def test_answer_call_includes_the_thread_and_question():
    thread = tuple(Exchange(f"q{i}", f"a{i}") for i in range(7))
    c = answer_call(CTX, "what is a margin?", thread=thread)
    assert "Question: what is a margin?" in c.text
    assert "q6" in c.text and "q1" not in c.text  # only the last five exchanges
    assert set(c.schema["required"]) == {"answer_md", "terms"}


def test_schemas_are_valid_json():
    for c in (explain_call(CTX), answer_call(CTX, "x")):
        json.dumps(c.schema)
        assert c.schema["type"] == "object"
