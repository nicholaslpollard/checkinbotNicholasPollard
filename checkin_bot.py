# INF601 - Advanced Programming in Python
# Nicholas Pollard
# Scheduled Check-In Bot

"""
Practice Hub client foundation.

Verified against the live OpenAPI schema at
https://practice.fhsucyber.com/openapi.json before writing this file.
"""

import os

import requests

DEFAULT_TIMEOUT = 15  # seconds


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

    def download_attachment_from_url(self, download_url):
        """Download raw attachment bytes using the download_url from AttachmentPublic."""
        if download_url.startswith("http"):
            url = download_url
        else:
            url = f"{self.base_url}{download_url}"
        response = self.session.get(url, timeout=DEFAULT_TIMEOUT)
        if response.status_code >= 400:
            raise PracticeHubError(
                f"GET {download_url} failed: HTTP {response.status_code} - {response.text[:300]}"
            )
        return response.content


def main():
    config = load_config()
    client = PracticeHubClient(config)

    me = client.get_me()
    print(f"Authenticated as: {me['name']} (id={me['id']})")

    posts = client.list_posts(limit=5)
    print(f"Fetched {len(posts)} post(s) from the first page of /api/v1/posts.")


if __name__ == "__main__":
    main()
