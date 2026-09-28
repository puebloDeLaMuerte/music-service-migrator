"""The app reports skipped items itself, so spotipy's raw 403/404 lines are dropped."""

import io
import logging
import unittest

from common.log import get_logger


class SpotipyNoiseTests(unittest.TestCase):
    def setUp(self) -> None:
        get_logger(__name__)  # ensure logging is initialised
        self.buf = io.StringIO()
        self.handler = logging.StreamHandler(self.buf)
        logging.getLogger().addHandler(self.handler)
        self.log = logging.getLogger("spotipy.client")

    def tearDown(self) -> None:
        logging.getLogger().removeHandler(self.handler)

    def _emit(self, message: str) -> str:
        self.log.error(message)
        return self.buf.getvalue()

    def test_handled_statuses_are_dropped(self) -> None:
        url = "https://api.spotify.com/v1/playlists/abc/items"
        for status in (403, 404):
            self.assertEqual(
                self._emit(f"HTTP Error for GET to {url} with Params: {{}} returned {status} due to x"),
                "",
            )

    def test_everything_else_still_shows(self) -> None:
        out = self._emit(
            "HTTP Error for PUT to https://api.spotify.com/v1/me/tracks "
            "with Params: {} returned 500 due to Server Error"
        )
        self.assertIn("500", out)
        self.assertIn("token refresh failed", self._emit("token refresh failed"))


if __name__ == "__main__":
    unittest.main()
