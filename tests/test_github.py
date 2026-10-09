import jwt
import pytest
from conftest import DEAD_URL, FakeGitHub, github_fixture
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from quantic_agent import github
from quantic_agent.github import File


def client(github_api: FakeGitHub, app_key: tuple[str, str]) -> github.Client:
    return github.Client(github_api.repo, "1", app_key[0], base_url=github_api.url)


FILES = [
    File("priv/insights/week-ahead-2026-W42/en.md", '---\nkind: "week_ahead"\n---\n'),
    File("priv/insights/week-ahead-2026-W42/es.md", '---\nkind: "week_ahead"\n---\n'),
]
BRANCH = "agent/week-ahead-2026-W42-run-4"


async def open_one(gh: github.Client, branch: str = BRANCH) -> github.PullRequest:
    return await gh.open_pull_request(
        branch, FILES, message="the commit", title="the title", body="the body"
    )


def test_the_app_signs_a_short_jwt(app_key: tuple[str, str]) -> None:
    token = github.app_jwt("12345", app_key[0], now=1_000_000)

    claims = jwt.decode(token, app_key[1], algorithms=["RS256"], options={"verify_exp": False})
    # A minute in the past for clocks that differ, ten minutes in all: GitHub's limit.
    assert claims == {"iss": "12345", "iat": 999_940, "exp": 1_000_540}


@pytest.mark.parametrize(
    "branch",
    ["agent/week-ahead-2026-W42-run-4", "agent/a", "agent/nested/name"],
)
def test_branches_under_the_prefix_are_allowed(branch: str) -> None:
    github.check_branch(branch)


@pytest.mark.parametrize(
    "branch",
    [
        "main",
        "refs/heads/main",
        "agent/",
        "agent",
        "agent/../main",
        "agent/x y",
        "agent/x:y",
        "agent/x.lock",
        "feature/agent/x",
    ],
)
def test_every_other_branch_is_refused(branch: str) -> None:
    with pytest.raises(github.RefusedError, match="only writes branches under agent/"):
        github.check_branch(branch)


@pytest.mark.anyio
async def test_a_pull_request_is_one_new_branch_and_one_commit(
    github_api: FakeGitHub, app_key: tuple[str, str]
) -> None:
    async with client(github_api, app_key) as gh:
        pr = await open_one(gh)

    assert (pr.number, pr.state, pr.merged, pr.head.ref) == (100, "open", False, BRANCH)
    assert pr.html_url == "https://github.com/fleveque/quantic/pull/100"
    repo = "/repos/fleveque/quantic"
    main = github_fixture("ref.json")["object"]["sha"]
    installation = github_fixture("installation.json")["id"]
    calls = [(method, path) for method, path, _, _ in github_api.requests]
    assert calls == [
        ("GET", f"{repo}/installation"),
        ("POST", f"/app/installations/{installation}/access_tokens"),
        ("GET", f"{repo}/git/ref/heads/main"),
        ("GET", f"{repo}/git/commits/{main}"),
        ("POST", f"{repo}/git/trees"),
        ("POST", f"{repo}/git/commits"),
        ("POST", f"{repo}/git/refs"),
        ("POST", f"{repo}/pulls"),
    ]
    bodies = {path.rsplit("/", 1)[1]: body for _, path, body, _ in github_api.requests}
    assert bodies["trees"]["tree"] == [
        {"path": f.path, "mode": "100644", "type": "blob", "content": f.content} for f in FILES
    ]
    assert bodies["commits"]["parents"] == [main]
    assert bodies["refs"]["ref"] == f"refs/heads/{BRANCH}"
    assert bodies["pulls"] == {
        "title": "the title",
        "head": BRANCH,
        "base": "main",
        "body": "the body",
    }
    # main was read, never written.
    assert github_api.refs["refs/heads/main"] == main


@pytest.mark.anyio
async def test_the_jwt_is_only_for_the_token_and_the_token_for_the_repository(
    github_api: FakeGitHub, app_key: tuple[str, str]
) -> None:
    async with client(github_api, app_key) as gh:
        await open_one(gh)
        await gh.pull_request(100)

    token = f"Bearer {github_api.token}"
    app = [auth for _, path, _, auth in github_api.requests if not path.startswith("/repos/")]
    repo = [auth for _, path, _, auth in github_api.requests if path.startswith("/repos/")]
    assert len(app) == 1
    assert app[0] != token
    assert repo[1:] == [token] * (len(repo) - 1)  # the first is the installation lookup
    assert github_api.tokens_issued == 1  # fetched once, used for every call


@pytest.mark.anyio
async def test_a_token_about_to_expire_is_replaced(
    github_api: FakeGitHub, app_key: tuple[str, str]
) -> None:
    github_api.token_lifetime = 30  # less than the minute's margin
    async with client(github_api, app_key) as gh:
        github_api.pulls[7] = "open"
        await gh.pull_request(7)
        await gh.pull_request(7)
    assert github_api.tokens_issued == 2


@pytest.mark.anyio
async def test_an_existing_branch_is_never_overwritten(
    github_api: FakeGitHub, app_key: tuple[str, str]
) -> None:
    github_api.refs[f"refs/heads/{BRANCH}"] = "an earlier run's commit"

    async with client(github_api, app_key) as gh:
        with pytest.raises(github.APIError, match="422 Reference already exists") as caught:
            await open_one(gh)

    assert caught.value.status == 422
    assert github_api.refs[f"refs/heads/{BRANCH}"] == "an earlier run's commit"
    assert github_api.pulls == {}


@pytest.mark.anyio
async def test_a_refused_branch_sends_nothing(
    github_api: FakeGitHub, app_key: tuple[str, str]
) -> None:
    async with client(github_api, app_key) as gh:
        with pytest.raises(github.RefusedError):
            await open_one(gh, branch="main")
    assert github_api.requests == []


@pytest.mark.anyio
async def test_the_client_writes_no_ref_but_a_new_one(
    github_api: FakeGitHub, app_key: tuple[str, str]
) -> None:
    async with client(github_api, app_key) as gh:
        await open_one(gh)
        await gh.pull_request(100)

    writes = [(m, p) for m, p, _, _ in github_api.requests if m != "GET"]
    assert all(m == "POST" for m, _ in writes)  # no PATCH, PUT or DELETE, ever
    ref_writes = [b for _, p, b, _ in github_api.requests if p.endswith("/git/refs")]
    assert [b["ref"] for b in ref_writes] == [f"refs/heads/{BRANCH}"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("state", "open_", "merged"),
    [("merged", "closed", True), ("closed", "closed", False), ("open", "open", False)],
)
async def test_a_pull_requests_state_is_read_back(
    github_api: FakeGitHub, app_key: tuple[str, str], state: str, open_: str, merged: bool
) -> None:
    github_api.pulls[12] = state
    async with client(github_api, app_key) as gh:
        pr = await gh.pull_request(12)
    assert (pr.state, pr.merged) == (open_, merged)


@pytest.mark.anyio
async def test_a_wrong_key_is_refused_by_github(
    github_api: FakeGitHub, app_key: tuple[str, str]
) -> None:
    other = github.Client(github_api.repo, "1", OTHER_KEY, base_url=github_api.url)
    async with other as gh:
        with pytest.raises(github.APIError, match="401 A JSON web token could not be decoded"):
            await gh.pull_request(1)


@pytest.mark.anyio
async def test_github_not_answering_is_unavailable(app_key: tuple[str, str]) -> None:
    async with github.Client("fleveque/quantic", "1", app_key[0], base_url=DEAD_URL) as gh:
        with pytest.raises(github.UnavailableError):
            await gh.pull_request(1)


# A second key, which GitHub doesn't know: an App's key from somewhere else.
def _other_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


OTHER_KEY = _other_key()
