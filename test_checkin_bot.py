# INF601 - Advanced Programming in Python
# Nicholas Pollard
# Scheduled Check-In Bot

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from checkin_bot import (
    CHECKIN_REPLY_TEXT,
    Config,
    ConfigError,
    PracticeHubClient,
    PracticeHubError,
    collect_instructor_posts,
    download_attachments,
    fetch_instructor_posts,
    has_already_replied,
    is_qualifying_checkin,
    load_config,
    main,
    process_checkins,
    safe_attachment_filename,
)


class LoadConfigTests(unittest.TestCase):
    def test_missing_url_raises(self):
        env = {
            "PRACTICE_API_TOKEN": "abc",
            "INSTRUCTOR_ID": "7",
        }

        with patch.dict(
            os.environ,
            env,
            clear=True,
        ):
            with self.assertRaises(ConfigError):
                load_config()

    def test_missing_token_raises(self):
        env = {
            "PRACTICE_API_URL": "https://practice.fhsucyber.com",
            "INSTRUCTOR_ID": "7",
        }

        with patch.dict(
            os.environ,
            env,
            clear=True,
        ):
            with self.assertRaises(ConfigError):
                load_config()

    def test_missing_instructor_id_raises(self):
        env = {
            "PRACTICE_API_URL": "https://practice.fhsucyber.com",
            "PRACTICE_API_TOKEN": "abc",
        }

        with patch.dict(
            os.environ,
            env,
            clear=True,
        ):
            with self.assertRaises(ConfigError):
                load_config()

    def test_instructor_id_from_env(self):
        env = {
            "PRACTICE_API_URL": "https://practice.fhsucyber.com",
            "PRACTICE_API_TOKEN": "abc",
            "INSTRUCTOR_ID": "42",
        }

        with patch.dict(
            os.environ,
            env,
            clear=True,
        ):
            config = load_config()

        self.assertEqual(
            config.instructor_id,
            42,
        )


def make_client():
    config = Config(
        base_url="https://practice.fhsucyber.com",
        token="test-token",
        instructor_id=7,
    )

    return PracticeHubClient(config)


class PracticeHubClientTests(unittest.TestCase):
    def test_request_raises_on_http_error(self):
        client = make_client()

        fake_response = MagicMock(
            status_code=500,
            text="server error",
        )

        client.session.request = MagicMock(
            return_value=fake_response
        )

        with self.assertRaises(PracticeHubError):
            client.get_me()

    def test_request_allows_specified_status(self):
        client = make_client()

        fake_response = MagicMock(
            status_code=423,
            text="Locked",
        )

        client.session.request = MagicMock(
            return_value=fake_response
        )

        response = client.create_comment(
            1,
            "hello",
        )

        self.assertEqual(
            response.status_code,
            423,
        )

    def test_list_posts_sends_expected_params(self):
        client = make_client()

        fake_response = MagicMock(
            status_code=200
        )

        fake_response.json.return_value = []

        client.session.request = MagicMock(
            return_value=fake_response
        )

        client.list_posts(
            limit=100,
            offset=50,
            author=7,
            tag="checkin",
        )

        _, kwargs = client.session.request.call_args

        self.assertEqual(
            kwargs["params"],
            {
                "limit": 100,
                "offset": 50,
                "mine": False,
                "author": 7,
                "tag": "checkin",
            },
        )

    def test_authorization_header_uses_bearer_token(self):
        client = make_client()

        self.assertEqual(
            client.session.headers["Authorization"],
            "Bearer test-token",
        )

    def test_network_error_wrapped_as_practice_hub_error(self):
        import requests

        client = make_client()

        client.session.request = MagicMock(
            side_effect=requests.exceptions.ConnectionError(
                "boom"
            )
        )

        with self.assertRaises(PracticeHubError):
            client.get_me()


class FakeResponse:
    """Minimal stand-in for a requests.Response used by check-in tests."""

    def __init__(
        self,
        status_code,
        payload,
    ):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeClient:
    """Minimal stand-in for PracticeHubClient used by the tests."""

    def __init__(
        self,
        pages,
        post_details,
        attachment_bytes=None,
        comments_by_post=None,
        checkin_status_by_post=None,
    ):
        self._pages = list(pages)
        self._post_details = post_details
        self._attachment_bytes = attachment_bytes or {}
        self._comments_by_post = comments_by_post or {}
        self._checkin_status_by_post = checkin_status_by_post or {}

        self.list_posts_calls = []
        self.create_comment_calls = []

    def list_posts(
        self,
        *,
        limit,
        offset,
        author=None,
        tag=None,
        mine=False,
    ):
        self.list_posts_calls.append(
            {
                "limit": limit,
                "offset": offset,
                "author": author,
            }
        )

        index = offset // limit

        if index >= len(self._pages):
            return []

        return self._pages[index]

    def get_post(
        self,
        post_id,
    ):
        return self._post_details[post_id]

    def download_attachment(
        self,
        attachment_id,
    ):
        return self._attachment_bytes[attachment_id]

    def list_comments(
        self,
        post_id,
    ):
        return self._comments_by_post.get(
            post_id,
            [],
        )

    def create_comment(
        self,
        post_id,
        body,
    ):
        self.create_comment_calls.append(
            (
                post_id,
                body,
            )
        )

        status = self._checkin_status_by_post.get(
            post_id,
            201,
        )

        if status == 423:
            return FakeResponse(
                423,
                {
                    "detail": "Locked",
                },
            )

        return FakeResponse(
            201,
            {
                "id": 900 + post_id,
                "post_id": post_id,
                "body": body,
            },
        )


def make_post(
    post_id,
    author_id,
    title="Untitled",
    body="",
    attachments=None,
):
    return {
        "id": post_id,
        "title": title,
        "body": body,
        "tags": ["tag-a"],
        "author_id": author_id,
        "author_name": (
            "Instructor"
            if author_id == 7
            else "Student"
        ),
        "created_at": "2026-09-15T00:00:00Z",
        "updated_at": "2026-09-15T00:00:00Z",
        "attachments": attachments or [],
    }


class FetchInstructorPostsTests(unittest.TestCase):
    def test_pages_until_short_page_and_filters_by_author(self):
        page1 = [
            make_post(1, 7),
            make_post(2, 99),
        ]

        page2 = [
            make_post(3, 7),
        ]

        client = FakeClient(
            pages=[
                page1,
                page2,
            ],
            post_details={},
        )

        posts = fetch_instructor_posts(
            client,
            instructor_id=7,
            page_size=2,
        )

        self.assertEqual(
            [p["id"] for p in posts],
            [1, 3],
        )

        self.assertEqual(
            [
                c["offset"]
                for c in client.list_posts_calls
            ],
            [0, 2],
        )

    def test_empty_first_page_returns_empty_list(self):
        client = FakeClient(
            pages=[[]],
            post_details={},
        )

        posts = fetch_instructor_posts(
            client,
            instructor_id=7,
            page_size=2,
        )

        self.assertEqual(
            posts,
            [],
        )


class SafeAttachmentFilenameTests(unittest.TestCase):
    def test_duplicate_original_filenames_do_not_collide(self):
        name_a = safe_attachment_filename(
            1,
            "notes.pdf",
        )

        name_b = safe_attachment_filename(
            2,
            "notes.pdf",
        )

        self.assertNotEqual(
            name_a,
            name_b,
        )

        self.assertTrue(
            name_a.startswith("1_")
        )

        self.assertTrue(
            name_b.startswith("2_")
        )

    def test_sanitizes_unsafe_characters(self):
        name = safe_attachment_filename(
            5,
            "../../etc/passwd",
        )

        self.assertNotIn(
            "/",
            name,
        )

        self.assertNotIn(
            "..",
            name.replace("__", ""),
        )


class DownloadAttachmentsTests(unittest.TestCase):
    def test_writes_files_and_records_local_path(self):
        attachments = [
            {
                "id": 10,
                "post_id": 1,
                "filename": "a.pdf",
                "content_type": "application/pdf",
                "size": 3,
                "download_url": "/api/v1/attachments/10",
                "created_at": "2026-09-15T00:00:00Z",
            },
        ]

        client = FakeClient(
            pages=[],
            post_details={},
            attachment_bytes={
                10: b"abc",
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            files_dir = os.path.join(
                tmp,
                "files",
            )

            saved = download_attachments(
                client,
                attachments,
                files_dir,
            )

            self.assertEqual(
                len(saved),
                1,
            )

            local_path = saved[0]["local_path"]

            self.assertTrue(
                os.path.exists(local_path)
            )

            with open(
                local_path,
                "rb",
            ) as f:
                self.assertEqual(
                    f.read(),
                    b"abc",
                )

    def test_duplicate_filenames_produce_separate_files(self):
        attachments = [
            {
                "id": 1,
                "post_id": 1,
                "filename": "notes.pdf",
                "content_type": "application/pdf",
                "size": 3,
                "download_url": "u1",
                "created_at": "t",
            },
            {
                "id": 2,
                "post_id": 1,
                "filename": "notes.pdf",
                "content_type": "application/pdf",
                "size": 3,
                "download_url": "u2",
                "created_at": "t",
            },
        ]

        client = FakeClient(
            pages=[],
            post_details={},
            attachment_bytes={
                1: b"first",
                2: b"second",
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            files_dir = os.path.join(
                tmp,
                "files",
            )

            saved = download_attachments(
                client,
                attachments,
                files_dir,
            )

            self.assertEqual(
                len(saved),
                2,
            )

            self.assertNotEqual(
                saved[0]["local_path"],
                saved[1]["local_path"],
            )

            with open(
                saved[0]["local_path"],
                "rb",
            ) as f:
                self.assertEqual(
                    f.read(),
                    b"first",
                )

            with open(
                saved[1]["local_path"],
                "rb",
            ) as f:
                self.assertEqual(
                    f.read(),
                    b"second",
                )

    def test_failed_download_raises_instead_of_skipping(self):
        attachments = [
            {
                "id": 1,
                "post_id": 1,
                "filename": "ok.pdf",
                "content_type": "application/pdf",
                "size": 3,
                "download_url": "u1",
                "created_at": "t",
            },
        ]

        class RaisingClient(FakeClient):
            def download_attachment(
                self,
                attachment_id,
            ):
                raise PracticeHubError(
                    "boom"
                )

        raising_client = RaisingClient(
            pages=[],
            post_details={},
        )

        with tempfile.TemporaryDirectory() as tmp:
            files_dir = os.path.join(
                tmp,
                "files",
            )

            with self.assertRaises(
                PracticeHubError
            ):
                download_attachments(
                    raising_client,
                    attachments,
                    files_dir,
                )


class CollectInstructorPostsTests(unittest.TestCase):
    def test_creates_directories_and_writes_full_body_from_detail(self):
        summary = make_post(
            1,
            7,
            title="Sept 16 check-in",
            body="preview only",
        )

        detail = make_post(
            1,
            7,
            title="Sept 16 check-in",
            body="FULL BODY TEXT",
        )

        client = FakeClient(
            pages=[
                [summary],
            ],
            post_details={
                1: detail,
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = os.path.join(
                tmp,
                "artifact",
            )

            posts = collect_instructor_posts(
                client,
                instructor_id=7,
                artifact_dir=artifact_dir,
            )

            self.assertTrue(
                os.path.isdir(
                    os.path.join(
                        artifact_dir,
                        "files",
                    )
                )
            )

            collected_path = os.path.join(
                artifact_dir,
                "collected.json",
            )

            self.assertTrue(
                os.path.exists(collected_path)
            )

            with open(
                collected_path,
                encoding="utf-8",
            ) as f:
                on_disk = json.load(f)

            self.assertEqual(
                on_disk,
                posts,
            )

            self.assertEqual(
                posts[0]["body"],
                "FULL BODY TEXT",
            )

    def test_repeated_runs_are_deterministic_and_do_not_duplicate(self):
        summary = make_post(
            1,
            7,
        )

        detail = make_post(
            1,
            7,
            body="stable body",
        )

        client = FakeClient(
            pages=[
                [summary],
            ],
            post_details={
                1: detail,
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = os.path.join(
                tmp,
                "artifact",
            )

            collect_instructor_posts(
                client,
                instructor_id=7,
                artifact_dir=artifact_dir,
            )

            with open(
                os.path.join(
                    artifact_dir,
                    "collected.json",
                ),
                encoding="utf-8",
            ) as f:
                first_run = f.read()

            client.list_posts_calls.clear()

            collect_instructor_posts(
                client,
                instructor_id=7,
                artifact_dir=artifact_dir,
            )

            with open(
                os.path.join(
                    artifact_dir,
                    "collected.json",
                ),
                encoding="utf-8",
            ) as f:
                second_run = f.read()

            self.assertEqual(
                first_run,
                second_run,
            )

            data = json.loads(
                second_run
            )

            self.assertEqual(
                len(data),
                1,
            )

    def test_successful_refresh_removes_stale_files(self):
        summary = make_post(
            1,
            7,
        )

        current_attachment = {
            "id": 2,
            "post_id": 1,
            "filename": "current.pdf",
            "content_type": "application/pdf",
            "size": 3,
            "download_url": "u2",
            "created_at": "t",
        }

        detail = make_post(
            1,
            7,
            attachments=[
                current_attachment,
            ],
        )

        client = FakeClient(
            pages=[
                [summary],
            ],
            post_details={
                1: detail,
            },
            attachment_bytes={
                2: b"new",
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = os.path.join(
                tmp,
                "artifact",
            )

            files_dir = os.path.join(
                artifact_dir,
                "files",
            )

            os.makedirs(
                files_dir
            )

            stale_path = os.path.join(
                files_dir,
                "1_old-removed-attachment.pdf",
            )

            with open(
                stale_path,
                "wb",
            ) as f:
                f.write(
                    b"stale"
                )

            collect_instructor_posts(
                client,
                instructor_id=7,
                artifact_dir=artifact_dir,
            )

            self.assertFalse(
                os.path.exists(
                    stale_path
                )
            )

            self.assertEqual(
                os.listdir(files_dir),
                ["2_current.pdf"],
            )

    def test_attachment_failure_propagates_and_does_not_produce_success(self):
        summary = make_post(
            1,
            7,
        )

        failing_attachment = {
            "id": 9,
            "post_id": 1,
            "filename": "broken.pdf",
            "content_type": "application/pdf",
            "size": 3,
            "download_url": "u9",
            "created_at": "t",
        }

        detail = make_post(
            1,
            7,
            attachments=[
                failing_attachment,
            ],
        )

        class RaisingClient(FakeClient):
            def download_attachment(
                self,
                attachment_id,
            ):
                raise PracticeHubError(
                    "boom"
                )

        client = RaisingClient(
            pages=[
                [summary],
            ],
            post_details={
                1: detail,
            },
        )

        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = os.path.join(
                tmp,
                "artifact",
            )

            with self.assertRaises(
                PracticeHubError
            ):
                collect_instructor_posts(
                    client,
                    instructor_id=7,
                    artifact_dir=artifact_dir,
                )

            self.assertFalse(
                os.path.exists(
                    os.path.join(
                        artifact_dir,
                        "collected.json",
                    )
                )
            )


class IsQualifyingCheckinTests(unittest.TestCase):
    def test_title_containing_checkin_qualifies_case_insensitively(self):
        post = make_post(
            1,
            7,
            title="Sept 16 CHECK-IN",
        )

        self.assertTrue(
            is_qualifying_checkin(
                post,
                instructor_id=7,
            )
        )

    def test_checkin_with_surrounding_text_qualifies(self):
        post = make_post(
            1,
            7,
            title="Check-in for Sept 17",
        )

        self.assertTrue(
            is_qualifying_checkin(
                post,
                instructor_id=7,
            )
        )

    def test_regular_instructor_post_does_not_qualify(self):
        post = make_post(
            1,
            7,
            title="Weekly announcement",
        )

        self.assertFalse(
            is_qualifying_checkin(
                post,
                instructor_id=7,
            )
        )

    def test_other_authors_checkin_does_not_qualify(self):
        post = make_post(
            1,
            99,
            title="Student check-in",
        )

        self.assertFalse(
            is_qualifying_checkin(
                post,
                instructor_id=7,
            )
        )


class HasAlreadyRepliedTests(unittest.TestCase):
    def test_my_comment_is_detected_by_author_id(self):
        comments = [
            {
                "id": 1,
                "author_id": 42,
            },
            {
                "id": 2,
                "author_id": 5,
            },
        ]

        self.assertTrue(
            has_already_replied(
                comments,
                my_user_id=5,
            )
        )

    def test_other_users_comments_do_not_count(self):
        comments = [
            {
                "id": 1,
                "author_id": 42,
            },
        ]

        self.assertFalse(
            has_already_replied(
                comments,
                my_user_id=5,
            )
        )


class ProcessCheckinsTests(unittest.TestCase):
    def test_unanswered_checkin_gets_exactly_one_reply(self):
        post = make_post(
            1,
            7,
            title="Sept 16 check-in",
        )

        client = FakeClient(
            pages=[],
            post_details={},
            comments_by_post={
                1: [],
            },
        )

        process_checkins(
            client,
            [post],
            instructor_id=7,
            my_user_id=5,
        )

        self.assertEqual(
            client.create_comment_calls,
            [
                (
                    1,
                    CHECKIN_REPLY_TEXT,
                ),
            ],
        )

    def test_already_replied_checkin_is_skipped(self):
        post = make_post(
            1,
            7,
            title="Sept 16 check-in",
        )

        client = FakeClient(
            pages=[],
            post_details={},
            comments_by_post={
                1: [
                    {
                        "id": 10,
                        "author_id": 5,
                        "body": "already answered",
                    },
                ],
            },
        )

        process_checkins(
            client,
            [post],
            instructor_id=7,
            my_user_id=5,
        )

        self.assertEqual(
            client.create_comment_calls,
            [],
        )

    def test_other_users_comment_does_not_block_my_reply(self):
        post = make_post(
            1,
            7,
            title="Sept 16 check-in",
        )

        client = FakeClient(
            pages=[],
            post_details={},
            comments_by_post={
                1: [
                    {
                        "id": 10,
                        "author_id": 999,
                        "body": "a student comment",
                    },
                ],
            },
        )

        process_checkins(
            client,
            [post],
            instructor_id=7,
            my_user_id=5,
        )

        self.assertEqual(
            client.create_comment_calls,
            [
                (
                    1,
                    CHECKIN_REPLY_TEXT,
                ),
            ],
        )

    def test_non_checkin_and_other_author_posts_are_ignored(self):
        posts = [
            make_post(
                1,
                7,
                title="Regular instructor update",
            ),
            make_post(
                2,
                99,
                title="Student check-in",
            ),
        ]

        client = FakeClient(
            pages=[],
            post_details={},
            comments_by_post={
                1: [],
                2: [],
            },
        )

        process_checkins(
            client,
            posts,
            instructor_id=7,
            my_user_id=5,
        )

        self.assertEqual(
            client.create_comment_calls,
            [],
        )

    def test_423_is_reported_and_does_not_stop_remaining_posts(self):
        posts = [
            make_post(
                1,
                7,
                title="Sept 7 check-in",
            ),
            make_post(
                2,
                7,
                title="Sept 16 check-in",
            ),
        ]

        client = FakeClient(
            pages=[],
            post_details={},
            comments_by_post={
                1: [],
                2: [],
            },
            checkin_status_by_post={
                1: 423,
            },
        )

        process_checkins(
            client,
            posts,
            instructor_id=7,
            my_user_id=5,
        )

        self.assertEqual(
            client.create_comment_calls,
            [
                (
                    1,
                    CHECKIN_REPLY_TEXT,
                ),
                (
                    2,
                    CHECKIN_REPLY_TEXT,
                ),
            ],
        )

    def test_multiple_checkins_processed_in_one_run(self):
        posts = [
            make_post(
                1,
                7,
                title="Sept 16 check-in",
            ),
            make_post(
                2,
                7,
                title="Sept 17 check-in",
            ),
        ]

        client = FakeClient(
            pages=[],
            post_details={},
            comments_by_post={
                1: [],
                2: [],
            },
        )

        process_checkins(
            client,
            posts,
            instructor_id=7,
            my_user_id=5,
        )

        self.assertEqual(
            len(client.create_comment_calls),
            2,
        )


class MainOrchestrationTests(unittest.TestCase):
    def test_checkins_run_before_collection_and_survive_collection_failure(self):
        """
        Check-ins are time-sensitive and cannot be recovered after their
        window closes, so main() must process them before the (retryable)
        full artifact collection step - and a later collection failure must
        not prevent the check-in attempt from having already happened.
        """
        call_order = []
        fake_config = Config(base_url="https://practice.fhsucyber.com", token="t", instructor_id=7)

        def fake_fetch(client, instructor_id):
            call_order.append("fetch_instructor_posts")
            return []

        def fake_process(client, posts, instructor_id, my_user_id):
            call_order.append("process_checkins")

        def fake_collect(client, instructor_id):
            call_order.append("collect_instructor_posts")
            raise PracticeHubError("attachment download failed")

        with patch("checkin_bot.load_config", return_value=fake_config), \
                patch("checkin_bot.PracticeHubClient") as mock_client_cls, \
                patch("checkin_bot.fetch_instructor_posts", side_effect=fake_fetch), \
                patch("checkin_bot.process_checkins", side_effect=fake_process), \
                patch("checkin_bot.collect_instructor_posts", side_effect=fake_collect):
            mock_client_cls.return_value.get_me.return_value = {"id": 5, "name": "Nick"}

            with self.assertRaises(PracticeHubError):
                main()

        self.assertEqual(
            call_order,
            ["fetch_instructor_posts", "process_checkins", "collect_instructor_posts"],
        )


if __name__ == "__main__":
    unittest.main()