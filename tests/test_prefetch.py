import threading
import time

from studydesk.ai.runner import ClaudeResult
from tests.test_study_api import app_env, explain, explained, explained_titles  # noqa: F401  (fixture reuse)


class SlowRunner:
    """Answers like `explained`, after an optional delay, and counts calls."""

    def __init__(self, delay=0.0):
        self.delay = delay
        self.calls = []
        self.lock = threading.Lock()

    def run(self, call):
        with self.lock:
            self.calls.append(call)
        time.sleep(self.delay)
        return ClaudeResult(data=explained(call))


def swap_runner(client, runner):
    client.app_state.runner = runner


def test_next_slide_is_ready_when_the_student_gets_there(app_env):
    client, runner, deck_id = app_env
    explain(client, deck_id, 1)
    client.app_state.jobs.join()
    assert "Topic 2" in explained_titles(runner)
    assert explain(client, deck_id, 2).json()["cached"] is True


def test_prefetch_for_a_slide_left_behind_is_skipped(app_env):
    client, runner, deck_id = app_env
    gate = threading.Event()
    client.app_state.jobs.submit("hold", gate.wait)  # keep the worker busy
    explain(client, deck_id, 1)  # wants 2
    explain(client, deck_id, 3)  # now wants 4; the queued job for 2 is stale
    gate.set()
    client.app_state.jobs.join()
    titles = explained_titles(runner)
    assert "Topic 2" not in titles and "Topic 4" in titles


def test_same_slide_is_never_generated_twice_at_once(app_env):
    client, _, deck_id = app_env
    slow = SlowRunner(delay=0.5)
    swap_runner(client, slow)
    results = []
    threads = [threading.Thread(target=lambda: results.append(explain(client, deck_id, 3).json())) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    client.app_state.jobs.join()
    titles = [c.text.split("Slide title: ")[1].split("\n")[0] for c in slow.calls]
    assert titles.count("Topic 3") == 1
    assert len(results) == 3 and all(r["explanation_md"] == "About Topic 3" for r in results)
