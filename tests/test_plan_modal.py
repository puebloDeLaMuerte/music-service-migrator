"""Inspect Push Plan: the live verdict, and clipboard routing for candidate links."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common.push.resolution_cache import set_decision
from tui.views.push_plan_modal import PushPlanModal, _to_clipboard

LINK = "https://open.spotify.com/artist/0WCo84qtCKfbyIf1lqQWB4"


def _plan(*, ambiguous: int) -> dict:
    items = [
        {
            "kind": "artist", "key": f"a{n}", "label": f"Artist {n}", "status": "ambiguous",
            "candidates": [{"ref": f"r{n}", "display": f"Artist {n}", "score": 1.0}],
        }
        for n in range(ambiguous)
    ]
    blocked = f"{ambiguous} item(s) need your decision — open Inspect Push Plan."
    return {
        "provider": "spotify", "kind": "push_add", "items": items,
        "playlists": [], "operations": [{"op": "follow_artists", "ids": ["r0"]}],
        "summary": {
            "operations": 1,
            "can_apply": not ambiguous,
            "blocking_reason": blocked if ambiguous else None,
        },
    }


class VerdictTests(unittest.TestCase):
    """Decisions are made here, so the page must not keep quoting the stored plan."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "meta").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def modal(self, plan: dict) -> PushPlanModal:
        return PushPlanModal(plan, workspace_root=self.root)

    def test_open_decisions_block_and_keep_push_locked(self) -> None:
        m = self.modal(_plan(ambiguous=2))
        self.assertEqual(m._pending(), 2)
        self.assertEqual(m._settled_by_you(), 0)
        text = "\n".join(m._verdict_lines(2, 0))
        self.assertIn("0 conflicts were able to be resolved by decisions you made in the past", text)
        self.assertIn("2 conflicts still need your decision", text)
        self.assertIn("Blocked: 2 item(s)", text)
        self.assertEqual(m._push_label(m._pending()), "Push now")

    def test_settling_every_item_turns_the_verdict_green(self) -> None:
        for n in range(2):
            set_decision("spotify", "artist", f"a{n}", f"r{n}", workspace_root=self.root)
        m = self.modal(_plan(ambiguous=2))
        self.assertEqual(m._pending(), 0)
        self.assertEqual(m._settled_by_you(), 2)
        verdict = "\n".join(m._verdict_lines(0, 2))
        self.assertIn("2 conflicts were able to be resolved by decisions you made in the past", verdict)
        self.assertIn("0 conflicts still need your decision", verdict)
        self.assertIn("Ready to push", verdict)
        self.assertIn("green", verdict)
        self.assertIn("[bold green]", m._push_label(0))

    def test_an_excluded_item_counts_as_settled(self) -> None:
        set_decision("spotify", "artist", "a0", "__exclude__", workspace_root=self.root)
        self.assertEqual(self.modal(_plan(ambiguous=1))._pending(), 0)

    def test_a_plan_without_decisions_keeps_its_own_verdict(self) -> None:
        m = self.modal(_plan(ambiguous=0))
        self.assertIn("Ready to apply", "\n".join(m._verdict_lines(0, 0)))


class FakeApp:
    def __init__(self, works: bool = True) -> None:
        self.works = works
        self.copied: list[str] = []

    def copy_to_clipboard(self, text: str) -> None:
        if not self.works:
            raise RuntimeError("no terminal support")
        self.copied.append(text)


class ClipboardTests(unittest.TestCase):
    def test_a_local_tool_is_used_when_available(self) -> None:
        app = FakeApp()
        with mock.patch("shutil.which", lambda name: "/usr/bin/pbcopy" if name == "pbcopy" else None), \
             mock.patch("subprocess.run") as run:
            self.assertTrue(_to_clipboard(LINK, app))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["pbcopy"])
        self.assertEqual(run.call_args.kwargs["input"], LINK.encode())
        self.assertEqual(app.copied, [])

    def test_falls_back_to_the_terminal_when_no_tool_exists(self) -> None:
        app = FakeApp()
        with mock.patch("shutil.which", lambda name: None):
            self.assertTrue(_to_clipboard(LINK, app))
        self.assertEqual(app.copied, [LINK])

    def test_says_no_when_nothing_works(self) -> None:
        with mock.patch("shutil.which", lambda name: None):
            self.assertFalse(_to_clipboard(LINK, FakeApp(works=False)))


if __name__ == "__main__":
    unittest.main()
