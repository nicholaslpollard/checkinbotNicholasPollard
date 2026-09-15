# INF601 - Advanced Programming in Python
# Nicholas Pollard
# Scheduled Check-In Bot

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from checkin_bot import (
    Config,
    ConfigError,
    PracticeHubClient,
    PracticeHubError,
    collect_instructor_posts,
    download_attachments,
    fetch_instructor_posts,
    load_config,
    safe_attachment_filename,
)


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


class FakeClient:
    """Minimal stand-in for PracticeHubClient used by the collection tests."""

    def __init__(self, pages, post_details, attachment_bytes=None):
        self._pages = list(pages)  # list of pages; each page is a list of post summaries
        self._post_details = post_details  # {post_id: full detail dict}
        self._attachment_bytes = attachment_bytes or {}  # {attachment_id: bytes}
        self.list_posts_calls = []

    def list_posts(self, *, limit, offset, author=None, tag=None, mine=False):
        self.list_posts_calls.append({"limit": limit, "offset": offset, "author": author})
        index = offset // limit
        if index >= len(self._pages):
            return []
        return self._pages[index]

    def get_post(self, post_id):
        return self._post_details[post_id]

    def download_attachment(self, attachment_id):
        return self._attachment_bytes[attachment_id]


def make_post(post_id, author_id, title="Untitled", body="", attachments=None):
    return {
        "id": post_id,
        "title": title,
        "body": body,
        "tags": ["tag-a"],
        "author_id": author_id,
        "author_name": "Instructor" if author_id == 7 else "Student",
        "created_at": "2026-09-15T00:00:00Z",
        "updated_at": "2026-09-15T00:00:00Z",
        "attachments": attachments or [],
    }


class FetchInstructorPostsTests(unittest.TestCase):
    def test_pages_until_short_page_and_filters_by_author(self):
        page1 = [make_post(1, 7), make_post(2, 99)]  # full page, mixed authors
        page2 = [make_post(3, 7)]  # short page -> last page
        client = FakeClient(pages=[page1, page2], post_details={})

        posts = fetch_instructor_posts(client, instructor_id=7, page_size=2)

        self.assertEqual([p["id"] for p in posts], [1, 3])
        self.assertEqual(
            [(c["offset"]) for c in client.list_posts_calls],
            [0, 2],
        )

    def test_empty_first_page_returns_empty_list(self):
        client = FakeClient(pages=[[]], post_details={})
        posts = fetch_instructor_posts(client, instructor_id=7, page_size=2)
        self.assertEqual(posts, [])


class SafeAttachmentFilenameTests(unittest.TestCase):
    def test_duplicate_original_filenames_do_not_collide(self):
        name_a = safe_attachment_filename(1, "notes.pdf")
        name_b = safe_attachment_filename(2, "notes.pdf")
        self.assertNotEqual(name_a, name_b)
        self.assertTrue(name_a.startswith("1_"))
        self.assertTrue(name_b.startswith("2_"))

    def test_sanitizes_unsafe_characters(self):
        name = safe_attachment_filename(5, "../../etc/passwd")
        self.assertNotIn("/", name)
        self.assertNotIn("..", name.replace("__", ""))


class DownloadAttachmentsTests(unittest.TestCase):
    def test_writes_files_and_records_local_path(self):
        attachments = [
            {"id": 10, "post_id": 1, "filename": "a.pdf", "content_type": "application/pdf",
             "size": 3, "download_url": "/api/v1/attachments/10", "created_at": "2026-09-15T00:00:00Z"},
        ]
        client = FakeClient(pages=[], post_details={}, attachment_bytes={10: b"abc"})

        with tempfile.TemporaryDirectory() as tmp:
            files_dir = os.path.join(tmp, "files")
            saved = download_attachments(client, attachments, files_dir)

            self.assertEqual(len(saved), 1)
            local_path = saved[0]["local_path"]
            self.assertTrue(os.path.exists(local_path))
            with open(local_path, "rb") as f:
                self.assertEqual(f.read(), b"abc")

    def test_duplicate_filenames_produce_separate_files(self):
        attachments = [
            {"id": 1, "post_id": 1, "filename": "notes.pdf", "content_type": "application/pdf",
             "size": 3, "download_url": "u1", "created_at": "t"},
            {"id": 2, "post_id": 1, "filename": "notes.pdf", "content_type": "application/pdf",
             "size": 3, "download_url": "u2", "created_at": "t"},
        ]
        client = FakeClient(pages=[], post_details={}, attachment_bytes={1: b"first", 2: b"second"})

        with tempfile.TemporaryDirectory() as tmp:
            files_dir = os.path.join(tmp, "files")
            saved = download_attachments(client, attachments, files_dir)

            self.assertEqual(len(saved), 2)
            self.assertNotEqual(saved[0]["local_path"], saved[1]["local_path"])
            with open(saved[0]["local_path"], "rb") as f:
                self.assertEqual(f.read(), b"first")
            with open(saved[1]["local_path"], "rb") as f:
                self.assertEqual(f.read(), b"second")

    def test_failed_download_is_skipped_not_fatal(self):
        attachments = [
            {"id": 1, "post_id": 1, "filename": "ok.pdf", "content_type": "application/pdf",
             "size": 3, "download_url": "u1", "created_at": "t"},
        ]
        class RaisingClient(FakeClient):
            def download_attachment(self, attachment_id):
                raise PracticeHubError("boom")

        raising_client = RaisingClient(pages=[], post_details={})
        with tempfile.TemporaryDirectory() as tmp:
            files_dir = os.path.join(tmp, "files")
            saved = download_attachments(raising_client, attachments, files_dir)
        self.assertEqual(saved, [])


class CollectInstructorPostsTests(unittest.TestCase):
    def test_creates_directories_and_writes_full_body_from_detail(self):
        summary = make_post(1, 7, title="Sept 16 check-in", body="preview only")
        detail = make_post(1, 7, title="Sept 16 check-in", body="FULL BODY TEXT")
        client = FakeClient(pages=[[summary]], post_details={1: detail})

        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = os.path.join(tmp, "artifact")
            posts = collect_instructor_posts(client, instructor_id=7, artifact_dir=artifact_dir)

            self.assertTrue(os.path.isdir(os.path.join(artifact_dir, "files")))
            collected_path = os.path.join(artifact_dir, "collected.json")
            self.assertTrue(os.path.exists(collected_path))

            with open(collected_path, encoding="utf-8") as f:
                on_disk = json.load(f)

            self.assertEqual(on_disk, posts)
            self.assertEqual(posts[0]["body"], "FULL BODY TEXT")

    def test_repeated_runs_are_deterministic_and_do_not_duplicate(self):
        summary = make_post(1, 7)
        detail = make_post(1, 7, body="stable body")
        client = FakeClient(pages=[[summary]], post_details={1: detail})

        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = os.path.join(tmp, "artifact")
            collect_instructor_posts(client, instructor_id=7, artifact_dir=artifact_dir)
            with open(os.path.join(artifact_dir, "collected.json"), encoding="utf-8") as f:
                first_run = f.read()

            client.list_posts_calls.clear()
            collect_instructor_posts(client, instructor_id=7, artifact_dir=artifact_dir)
            with open(os.path.join(artifact_dir, "collected.json"), encoding="utf-8") as f:
                second_run = f.read()

            self.assertEqual(first_run, second_run)
            data = json.loads(second_run)
            self.assertEqual(len(data), 1)


if __name__ == "__main__":
    unittest.main()
