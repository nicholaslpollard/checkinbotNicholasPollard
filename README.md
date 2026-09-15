# Scheduled Check-In Bot

INF601 Advanced Programming in Python — a scheduled bot that collects an
instructor's posts from the FHSU Practice Hub API and automatically replies
to that instructor's daily check-in posts.

## Purpose

A GitHub Actions workflow runs `checkin_bot.py` on a schedule (and on
demand) against the Practice Hub REST API at `https://practice.fhsucyber.com`.
Each run does two things:

1. **Collects** every post made by the instructor (full body, tags,
   timestamps, and downloaded attachments) into `artifact/`.
2. **Replies once** to any instructor post whose title contains
   "check-in", as long as that check-in's daily reply window is open and
   the bot hasn't already replied.

## How the bot works

`checkin_bot.py` is a single script built around a small `PracticeHubClient`
wrapper over `requests`. The main flow (`main()`) is:

1. Load configuration from environment variables.
2. Call `GET /api/v1/me` to authenticate and learn the bot's own numeric
   user id.
3. Page through `GET /api/v1/posts` for the instructor's posts and run
   check-in processing on them **first** — check-ins are time-sensitive
   (a missed daily window can't be recovered), while collection can simply
   retry on the next scheduled run.
4. For each qualifying, unanswered check-in, `POST` a reply comment.
5. Collect the full instructor dataset: page through every post, fetch
   each one's full detail (so bodies are never truncated previews),
   download every attachment, and write it all to `artifact/`.

### Check-in qualification

A post only qualifies for a reply when **both** are true:

- `author_id` equals the configured instructor id.
- `"check-in"` appears anywhere in the post's title, case-insensitively
  (e.g. "Sept 16 check-in" or "Check-in for Sept 17" both match).

Tags, body content, exact wording, and dates are never consulted. Regular
instructor posts and any student's posts (including a student post that
happens to say "check-in") are never replied to.

## Installation / requirements

- Python 3.14
- Dependencies: `pip install -r requirements.txt` (just `requests`)

## Configuration

The bot reads three environment variables — all required, with no
fallback defaults:

| Variable | GitHub setting | Purpose |
|---|---|---|
| `PRACTICE_API_TOKEN` | Repository **secret** | Bearer token for the Practice Hub API |
| `PRACTICE_API_URL` | Repository **secret** | Base URL, `https://practice.fhsucyber.com` |
| `INSTRUCTOR_ID` | Repository **variable** | Numeric Practice Hub user id to collect/reply to |

No secret values are stored in this repository or printed by the bot —
`checkin_bot.py` never logs the token, and the GitHub Actions workflow only
references secrets through `${{ secrets.* }}`/`${{ vars.* }}` expressions.

## GitHub Actions schedule

`.github/workflows/checkin_bot.yml` runs on:

```
schedule:
  - cron: "0 14,18,22 * * *"
workflow_dispatch:
```

GitHub Actions cron schedules always run in **UTC**, so this fires three
times a day at 14:00, 18:00, and 22:00 UTC — deliberately clear of the
04:00–06:00 UTC window the instructor warned could let a delayed run slip
into the wrong Central-time day. `workflow_dispatch` allows manually
triggering a run from the Actions tab at any time.

The workflow has `permissions: contents: write` and, after a successful
bot run, stages `artifact/`, commits only if something actually changed,
and pushes back to `main`. If `checkin_bot.py` fails (a real API or
collection error), the commit/push step never runs, so a failed run can
never push a partial or incomplete artifact — the next scheduled run
simply retries.

## Artifact output

- `artifact/collected.json` — a JSON array of every instructor post, each
  with `id`, `title`, `body` (full text, not a preview), `tags`,
  `author_id`, `author_name`, `created_at`, `updated_at`, and an
  `attachments` list (the API's own attachment fields plus a `local_path`
  pointing at the downloaded file).
- `artifact/files/` — the actual downloaded attachment bytes, one file per
  attachment, named `{attachment_id}_{sanitized original filename}` so two
  attachments can never collide even if they share a filename.

Each successful run does a full fresh collection: `collected.json` is
overwritten and `artifact/files/` is cleared and rebuilt from the current
live feed, so re-running never duplicates records or accumulates stale
files.

## Duplicate prevention / 423 behavior

Before replying to a qualifying check-in, the bot fetches that post's
existing comments (`GET /api/v1/posts/{id}/comments`) and checks whether
any comment's `author_id` matches the bot's own id (from `GET /api/v1/me`).
If so, it prints `Already replied to check-in <id>; skipping.` and does not
post again — this makes scheduled, manual, and same-day reruns safe.

If the server returns `HTTP 423 Locked` (the check-in's reply window isn't
open), the bot prints that the check-in is currently closed and moves on
to the next post rather than crashing or retrying.

## Testing

```
python3 -m py_compile checkin_bot.py test_checkin_bot.py
python3 -m unittest test_checkin_bot.py -v
```

33 unit tests cover configuration validation, pagination, instructor
filtering, full-detail body retrieval, attachment downloading (including
duplicate-filename handling and failed-download propagation), stale-file
cleanup, deterministic repeated-run output, check-in qualification,
duplicate-reply prevention, 423 handling, and the check-in-before-collection
orchestration order in `main()`. All API calls are mocked; no test ever
contacts the live Practice Hub API.

## Live validation

The workflow was manually run twice against the live Practice Hub feed on
September 15, 2026:

- **First run:** authenticated successfully; the Sept 15 check-in received
  exactly one reply; the historical Sept 7–14 check-ins each returned
  `423 Locked` and were skipped without crashing; 13 instructor posts were
  collected with full bodies, tags, and timestamps; all three attachments
  (`INF601_Syllabus_F2026.pdf`, `pandas_quick_reference.md`,
  `sample_scores.csv`) were downloaded; `artifact/` was committed to `main`
  by the `github-actions[bot]` identity.
- **Second run:** detected the existing Sept 15 reply and printed
  `Already replied to check-in 34; skipping.` without posting a duplicate;
  collected the same 13 posts; printed `No artifact changes to commit.`
  and exited successfully with no new commit.

## AI Usage

Claude Code was used throughout this project to inspect the Practice Hub
API documentation and OpenAPI schema, implement `checkin_bot.py` in
phases, write and run the unit test suite, debug issues, develop and
validate the GitHub Actions workflow, and help prepare this documentation.

ChatGPT was used to interpret the assignment instructions and grading
rubric, plan the phased development approach, review code and workflow
behavior between phases, and review the results of the live GitHub Actions
tests.

I personally configured the GitHub repository's secrets and variable,
reviewed every phase of Claude's implementation before approving it, ran
the live GitHub Actions validation runs described above, and made the
following substantive changes myself:

1. Made `INSTRUCTOR_ID` a required environment variable instead of
   silently defaulting to `7`.
2. Changed `main()` so time-sensitive check-in processing happens before
   full artifact collection, because a missed daily check-in cannot be
   recovered while collection can simply retry on the next run.
3. Chose and finalized the check-in reply text (`CHECKIN_REPLY_TEXT`).
4. Made the workflow's checkout step explicitly target `ref: main`.
5. Made artifact staging explicit with `git add -A artifact/`.
6. Made the workflow's push target explicit with
   `git push origin HEAD:main`.

I remain responsible for understanding and standing behind this
submission.
