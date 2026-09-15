# INF601 - Advanced Programming in Python
# Nicholas Pollard
# Scheduled Check-In Bot

import os
import unittest
from unittest.mock import MagicMock, patch

from checkin_bot import Config, ConfigError, PracticeHubClient, PracticeHubError, load_config


class LoadConfigTests(unittest.TestCase):
    def test_missing_url_raises(self):
        env = {"PRACTICE_API_TOKEN": "abc"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

    def test_missing_token_raises(self):
        env = {"PRACTICE_API_URL": "https://practice.fhsucyber.com"}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ConfigError):
                load_config()

    def test_valid_config_defaults_instructor_id(self):
        env = {
            "PRACTICE_API_URL": "https://practice.fhsucyber.com",
            "PRACTICE_API_TOKEN": "abc",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.instructor_id, 7)

    def test_instructor_id_from_env(self):
        env = {
            "PRACTICE_API_URL": "https://practice.fhsucyber.com",
            "PRACTICE_API_TOKEN": "abc",
            "INSTRUCTOR_ID": "42",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.instructor_id, 42)


def make_client():
    config = Config(base_url="https://practice.fhsucyber.com", token="test-token", instructor_id=7)
    return PracticeHubClient(config)


class PracticeHubClientTests(unittest.TestCase):
    def test_request_raises_on_http_error(self):
        client = make_client()
        fake_response = MagicMock(status_code=500, text="server error")
        client.session.request = MagicMock(return_value=fake_response)
        with self.assertRaises(PracticeHubError):
            client.get_me()

    def test_request_allows_specified_status(self):
        client = make_client()
        fake_response = MagicMock(status_code=423, text="Locked")
        client.session.request = MagicMock(return_value=fake_response)
        response = client.create_comment(1, "hello")
        self.assertEqual(response.status_code, 423)

    def test_list_posts_sends_expected_params(self):
        client = make_client()
        fake_response = MagicMock(status_code=200)
        fake_response.json.return_value = []
        client.session.request = MagicMock(return_value=fake_response)

        client.list_posts(limit=100, offset=50, author=7, tag="checkin")

        _, kwargs = client.session.request.call_args
        self.assertEqual(
            kwargs["params"],
            {"limit": 100, "offset": 50, "mine": False, "author": 7, "tag": "checkin"},
        )

    def test_authorization_header_uses_bearer_token(self):
        client = make_client()
        self.assertEqual(client.session.headers["Authorization"], "Bearer test-token")

    def test_network_error_wrapped_as_practice_hub_error(self):
        import requests

        client = make_client()
        client.session.request = MagicMock(side_effect=requests.exceptions.ConnectionError("boom"))
        with self.assertRaises(PracticeHubError):
            client.get_me()


if __name__ == "__main__":
    unittest.main()
