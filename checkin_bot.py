# INF601 - Advanced Programming in Python
# Nicholas Pollard
# Scheduled Check-In Bot

"""
Practice Hub client foundation.

Verified against the live OpenAPI schema at
https://practice.fhsucyber.com/openapi.json before writing this file.
"""

import json
import os
import re
import shutil

import requests

DEFAULT_TIMEOUT = 15  # seconds
PAGE_SIZE = 100  # matches the API's documented max "limit"

ARTIFACT_DIR = "artifact"
FILES_DIR = os.path.join(ARTIFACT_DIR, "files")
COLLECTED_JSON_PATH = os.path.join(ARTIFACT_DIR, "collected.json")


class ConfigError(Exception):
    """Raised when required configuration is missing."""


class PracticeHubError(Exception):
    """Raised when the Practice Hub API returns an unexpected error."""


class Config:
    def __init__(self, base_url, token, instructor_id):
        self.base_url = base_url
        self.token = token
        self.instructor_id = instructor_id


def load_config():
    """Load API configuration from environment variables."""
    base_url = os.environ.get("PRACTICE_API_URL")
    token = os.environ.get("PRACTICE_API_TOKEN")
    instructor_id = os.environ.get("INSTRUCTOR_ID", "7")

    if not base_url:
        raise ConfigError("PRACTICE_API_URL environment variable is not set")
    if not token:
        raise ConfigError("PRACTICE_API_TOKEN environment variable is not set")

    try:
        instructor_id = int(instructor_id)
    except ValueError as exc:
        raise ConfigError(
            f"INSTRUCTOR_ID must be an integer, got {instructor_id!r}"
        ) from exc

    return Config(base_url=base_url, token=token, instructor_id=instructor_id)


class PracticeHubClient:
    """Thin wrapper around the Practice Hub REST API."""

    def __init__(self, config):
        self.base_url = config.base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {config.token}"})

    def _request(self, method, path, *, allow_statuses=frozenset(), **kwargs):
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(method, url, timeout=DEFAULT_TIMEOUT, **kwargs)
        except requests.exceptions.RequestException as exc:
            raise PracticeHubError(f"Network error calling {method} {path}: {exc}") from exc

        if response.status_code >= 400 and response.status_code not in allow_statuses:
            raise PracticeHubError(
                f"{method} {path} failed: HTTP {response.status_code} - {response.text[:300]}"
            )
        return response

    def get_me(self):
        """Return the account that owns the configured API token."""
        return self._request("GET", "/api/v1/me").json()

    def list_posts(self, *, limit=100, offset=0, author=None, tag=None, mine=False):
        """Return one page of posts, newest first."""
        params = {"limit": limit, "offset": offset, "mine": mine}
        if author is not None:
            params["author"] = author
        if tag is not None:
            params["tag"] = tag
        return self._request("GET", "/api/v1/posts", params=params).json()

    def get_post(self, post_id):
        """Return the full detail record for a single post."""
        return self._request("GET", f"/api/v1/posts/{post_id}").json()

    def list_comments(self, post_id):
        """Return all comments on a post."""
        return self._request("GET", f"/api/v1/posts/{post_id}/comments").json()

    def create_comment(self, post_id, body):
        """
        Post a comment/reply. A 423 (check-in closed) is allowed through
        rather than raised, so callers can handle it explicitly.
        """
        return self._request(
            "POST",
            f"/api/v1/posts/{post_id}/comments",
            json={"body": body},
            allow_statuses={423},
        )

    def download_attachment(self, attachment_id):
        """Download raw attachment bytes by attachment id."""
        return self._request("GET", f"/api/v1/attachments/{attachment_id}").content


def fetch_instructor_posts(client, instructor_id, page_size=PAGE_SIZE):
    """
    Page through /api/v1/posts until every page has been retrieved, returning
    only posts authored by instructor_id.

    The server already supports an "author" filter, but the result is also
    filtered client-side as a safety net against unfiltered/incorrect rows.
    """
    posts = []
    offset = 0
    while True:
        page = client.list_posts(limit=page_size, offset=offset, author=instructor_id)
        if not page:
            break
        posts.extend(post for post in page if post.get("author_id") == instructor_id)
        if len(page) < page_size:
            break
        offset += page_size
    return posts


def safe_attachment_filename(attachment_id, original_filename):
    """
    Build a filesystem-safe, collision-proof filename for an attachment.

    Attachment ids are unique per the API schema, so prefixing with the id
    guarantees no two attachments ever collide on disk, even when they share
    an original filename, while keeping the name deterministic across runs.
    """
    base = os.path.basename(original_filename or "") or "attachment"
    sanitized = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return f"{attachment_id}_{sanitized}"


def download_attachments(client, attachments, files_dir):
    """
    Download every attachment's bytes into files_dir. Returns the attachment
    metadata with an added "local_path" field pointing at the saved file.

    Every instructor attachment must download successfully. A failure here
    is allowed to propagate as PracticeHubError so the whole collection run
    fails loudly instead of silently producing an incomplete artifact.
    """
    os.makedirs(files_dir, exist_ok=True)
    saved = []
    for attachment in attachments:
        filename = safe_attachment_filename(attachment["id"], attachment["filename"])
        local_path = os.path.join(files_dir, filename)
        content = client.download_attachment(attachment["id"])

        with open(local_path, "wb") as f:
            f.write(content)

        saved.append({
            "id": attachment["id"],
            "post_id": attachment["post_id"],
            "filename": attachment["filename"],
            "content_type": attachment["content_type"],
            "size": attachment["size"],
            "download_url": attachment["download_url"],
            "created_at": attachment["created_at"],
            "local_path": local_path,
        })
    return saved


def build_post_record(client, detail, files_dir):
    """Build one collected.json post record from a full post detail payload."""
    return {
        "id": detail["id"],
        "title": detail["title"],
        "body": detail["body"],
        "tags": detail.get("tags", []),
        "author_id": detail["author_id"],
        "author_name": detail["author_name"],
        "created_at": detail["created_at"],
        "updated_at": detail["updated_at"],
        "attachments": download_attachments(client, detail.get("attachments") or [], files_dir),
    }


def collect_instructor_posts(client, instructor_id, artifact_dir=ARTIFACT_DIR):
    """
    Collect every instructor post (full detail, tags, timestamps, downloaded
    attachments) and write it to <artifact_dir>/collected.json.

    Each run fetches the complete current instructor dataset and overwrites
    collected.json with it, so re-running safely refreshes the artifact
    instead of duplicating or losing records. files_dir is cleared and
    recreated before downloading, so a successful run leaves it containing
    exactly the current attachment set with no stale leftover files. If any
    attachment fails to download, the exception propagates and this run
    exits without writing collected.json.
    """
    files_dir = os.path.join(artifact_dir, "files")
    os.makedirs(artifact_dir, exist_ok=True)
    if os.path.isdir(files_dir):
        shutil.rmtree(files_dir)
    os.makedirs(files_dir, exist_ok=True)

    summaries = fetch_instructor_posts(client, instructor_id)
    posts = [
        build_post_record(client, client.get_post(summary["id"]), files_dir)
        for summary in summaries
    ]

    collected_path = os.path.join(artifact_dir, "collected.json")
    with open(collected_path, "w", encoding="utf-8") as f:
        json.dump(posts, f, indent=2)
        f.write("\n")

    return posts


def main():
    config = load_config()
    client = PracticeHubClient(config)

    me = client.get_me()
    print(f"Authenticated as: {me['name']} (id={me['id']})")

    posts = collect_instructor_posts(client, config.instructor_id)
    print(f"Collected {len(posts)} instructor post(s) into {COLLECTED_JSON_PATH}")


if __name__ == "__main__":
    main()
