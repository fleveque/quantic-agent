"""Pull requests on GitHub, opened as a GitHub App (decision 0014).

The agent publishes nothing (design N2): it commits a post's files to a new
branch and opens a pull request, and a person merges it or not. On the
Quantic repository nothing on GitHub's side enforces that, since its plan
can't protect main, and the App's permission to push branches covers main
too. So this client is written so it can't change an existing branch:

- the only write to a ref is creating one (POST .../git/refs), which GitHub
  refuses for a ref that exists, as main always does;
- the branch must be under BRANCH_PREFIX, checked before any request;
- there is no method that updates a ref, deletes one, merges, or writes
  files through the contents API.

Quantic's deploy workflow refuses a push to main by a bot, so a change to
this module that broke the rule still wouldn't deploy.

Authentication is the App's: a JWT signed with its private key, exchanged
for an installation token that lasts an hour and works only on the
repositories the App is installed on, with the permissions it was given.
No person's token is involved (decision 0006's rule, applied to GitHub).
"""

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Any, Self

import httpx
import jwt
from pydantic import BaseModel, ValidationError

from quantic_agent import network

API_URL = "https://api.github.com"
BRANCH_PREFIX = "agent/"


class GitHubError(Exception):
    """Anything that went wrong talking to GitHub."""


class UnavailableError(GitHubError):
    """GitHub wasn't there to answer: safe to try again later."""


class APIError(GitHubError):
    """GitHub answered with an error. status is the HTTP status, message
    GitHub's own."""

    def __init__(self, method: str, path: str, status: int, message: str) -> None:
        super().__init__(f"{method} {path}: {status} {message}")
        self.status = status
        self.message = message


class RefusedError(GitHubError):
    """The client won't do it: a branch outside BRANCH_PREFIX."""


def app_jwt(app_id: str, private_key: str, now: float | None = None) -> str:
    """The App's own credential: a JWT it signs with its private key, which
    GitHub checks against the public half it holds. It is good for one thing,
    getting an installation token. Issued a minute in the past, for clocks
    that differ, and valid for nine more (GitHub allows ten), as GitHub's
    documentation suggests."""
    issued = int(now if now is not None else time.time()) - 60
    claims = {"iat": issued, "exp": issued + 600, "iss": app_id}
    return jwt.encode(claims, private_key, algorithm="RS256")


def check_branch(branch: str) -> None:
    """Refuses a branch name the agent may not write: anything outside
    BRANCH_PREFIX, or a name git would read as something else."""
    name = branch.removeprefix(BRANCH_PREFIX)
    if (
        not branch.startswith(BRANCH_PREFIX)
        or not name
        or ".." in branch
        or branch.endswith(("/", ".lock"))
        or any(c.isspace() or c in "~^:?*[\\" for c in branch)
    ):
        raise RefusedError(f"the agent only writes branches under {BRANCH_PREFIX}: {branch!r}")


@dataclass(frozen=True)
class File:
    """A file to commit: its path in the repository and its text."""

    path: str
    content: str


class _Head(BaseModel):
    ref: str
    sha: str


class PullRequest(BaseModel):
    """A pull request, as far as the agent needs it."""

    number: int
    html_url: str
    state: str  # "open" or "closed"
    merged_at: datetime | None = None
    head: _Head

    @property
    def merged(self) -> bool:
        return self.merged_at is not None


class _Object(BaseModel):
    sha: str


class _Ref(BaseModel):
    ref: str
    object: _Object


class _Commit(BaseModel):
    sha: str
    tree: _Object


class _Installation(BaseModel):
    id: int


class _Token(BaseModel):
    token: str
    expires_at: datetime


# A validation error reading GitHub's reply is a GitHubError too: the reply
# wasn't what the client was written against.
def _validated[T: BaseModel](model: type[T], data: Any) -> T:
    try:
        return model.model_validate(data)
    except ValidationError as err:
        raise GitHubError(f"unexpected reply: {err}") from err


class Client:
    """One repository, through the App's installation on it. Opened by
    `async with Client(...) as gh:`.

    Like the model client, it sets no deadline of its own beyond httpx's
    connect and read limits: the caller wraps the work in asyncio.timeout.
    """

    def __init__(
        self, repo: str, app_id: str, private_key: str, *, base_url: str = API_URL
    ) -> None:
        self.repo = repo
        self._app_id = app_id
        self._key = private_key
        self._token: _Token | None = None
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "quantic-agent",
            },
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, kind: type[BaseException] | None, err: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.aclose()

    async def open_pull_request(
        self,
        branch: str,
        files: Sequence[File],
        *,
        message: str,
        title: str,
        body: str,
        base: str = "main",
    ) -> PullRequest:
        """Commits files on a new branch off base, in one commit, and opens a
        pull request from it into base.

        Five requests: base's head, its tree, a new tree with the files on top
        of it, a commit of that tree, the branch pointing at the commit; then
        the pull request. Nothing is visible until the branch exists, so a
        failure before it leaves only unreferenced objects, which GitHub
        collects. The branch must not exist: a second run gets a new one.
        """
        check_branch(branch)
        head = _validated(_Ref, await self._call("GET", f"git/ref/heads/{base}"))
        commit = _validated(_Commit, await self._call("GET", f"git/commits/{head.object.sha}"))
        tree = _validated(
            _Object,
            await self._call(
                "POST",
                "git/trees",
                {
                    "base_tree": commit.tree.sha,
                    "tree": [
                        {"path": f.path, "mode": "100644", "type": "blob", "content": f.content}
                        for f in files
                    ],
                },
            ),
        )
        new = _validated(
            _Commit,
            await self._call(
                "POST",
                "git/commits",
                {"message": message, "tree": tree.sha, "parents": [head.object.sha]},
            ),
        )
        # Creates the ref; GitHub answers 422 if it exists. This is the only
        # ref write in the client.
        await self._call("POST", "git/refs", {"ref": f"refs/heads/{branch}", "sha": new.sha})
        pull = await self._call(
            "POST", "pulls", {"title": title, "head": branch, "base": base, "body": body}
        )
        return _validated(PullRequest, pull)

    async def pull_request(self, number: int) -> PullRequest:
        """A pull request as it stands now."""
        return _validated(PullRequest, await self._call("GET", f"pulls/{number}"))

    async def _installation_token(self) -> str:
        """The installation token, fetched on first use and again a minute
        before it expires."""
        if self._token is None or self._token.expires_at.timestamp() - time.time() < 60:
            bearer = {"Authorization": f"Bearer {app_jwt(self._app_id, self._key)}"}
            found = _validated(
                _Installation,
                await self._request("GET", f"/repos/{self.repo}/installation", headers=bearer),
            )
            self._token = _validated(
                _Token,
                await self._request(
                    "POST", f"/app/installations/{found.id}/access_tokens", headers=bearer
                ),
            )
        return self._token.token

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """A request to a path under the repository, as the installation."""
        token = await self._installation_token()
        return await self._request(
            method,
            f"/repos/{self.repo}/{path}",
            body,
            headers={"Authorization": f"Bearer {token}"},
        )

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        headers: dict[str, str],
    ) -> Any:
        try:
            resp = await self._http.request(method, path, json=body, headers=headers)
        except httpx.HTTPError as err:
            kind = UnavailableError if network.unreachable(err) else GitHubError
            raise kind(f"{method} {path}: {err}") from err
        if resp.status_code >= 300:
            try:
                message = str(resp.json().get("message", resp.text))
            except ValueError:
                message = resp.text
            raise APIError(method, path, resp.status_code, message)
        try:
            return resp.json()
        except ValueError as err:
            raise GitHubError(f"{method} {path}: the reply isn't JSON") from err
