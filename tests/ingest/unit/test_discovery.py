import json
from urllib.parse import parse_qs, urlsplit

import pytest

from hackfront.ingest.sources.github import client as gh
from hackfront.ingest.sources.jira import client as jira
from hackfront.ingest.sources.slack import client as slack


class Fake:
    """Transport serving {path: (status, body, headers)} or a callable(url) -> same; records every URL and header set."""

    def __init__(self, module, routes):
        self.module, self.routes, self.calls = module, routes, []

    def get(self, url, headers, timeout):
        self.calls.append((url, headers))
        route = self.routes(url) if callable(self.routes) else self.routes[urlsplit(url).path]
        status, body, hdrs = (route + ({},))[:3] if len(route) == 2 else route
        return self.module.HTTPResponse(status, hdrs, json.dumps(body).encode())


def github(routes):
    t = Fake(gh, routes)
    return gh.GitHubClient("tok", transport=t), t


def test_github_whoami_and_auth_error_is_sanitized():
    c, t = github({"/user": (200, {"login": "octocat"})})
    assert c.whoami() == "octocat" and t.calls[0][1]["Authorization"] == "Bearer tok"
    assert "tok" not in t.calls[0][0]
    c, _ = github({"/user": (401, {"message": "Bad credentials tok-leak"})})
    with pytest.raises(gh.GitHubAPIError) as e:
        c.whoami()
    assert e.value.status == 401 and "leak" not in str(e.value)


def test_github_list_repos_org_then_user_fallback_and_paging():
    page2 = "https://api.github.com/orgs/acme/repos?per_page=100&page=2"

    def routes(url):
        p = urlsplit(url)
        if p.path == "/orgs/nobody/repos":
            return 404, {}
        if p.path == "/users/nobody/repos":
            return 200, [{"full_name": "nobody/x", "private": False}]
        assert p.path == "/orgs/acme/repos"
        if "page=2" in url:
            return 200, [{"full_name": "acme/b", "private": True}]
        return 200, [{"full_name": "acme/a"}], {"Link": f'<{page2}>; rel="next"'}

    c, t = github(routes)
    assert c.list_repos("acme") == [{"full_name": "acme/a", "private": False}, {"full_name": "acme/b", "private": True}]
    assert parse_qs(urlsplit(t.calls[0][0]).query)["sort"] == ["pushed"]
    assert c.list_repos("nobody") == [{"full_name": "nobody/x", "private": False}]


def test_github_list_repos_token_and_page_bound():
    n = []

    def routes(url):
        n.append(url)
        return 200, [{"full_name": f"o/r{len(n)}"}], {"Link": f'<https://api.github.com/user/repos?page={len(n) + 1}>; rel="next"'}

    c, t = github(routes)
    assert len(c.list_repos(None)) == 5  # bounded
    q = parse_qs(urlsplit(n[0]).query)
    assert urlsplit(n[0]).path == "/user/repos" and q["affiliation"] == ["owner,collaborator,organization_member"]
    other_error, _ = github({"/orgs/acme/repos": (500, {})})
    with pytest.raises(gh.GitHubAPIError):  # only 404 falls back
        other_error.list_repos("acme")


def test_github_url_validation_stays_narrow():
    c, _ = github({})
    for bad in ("https://evil.example/user", "http://api.github.com/user", "https://api.github.com/gists",
                "https://api.github.com/user/emails", "https://api.github.com/orgs/a/b/repos",
                "https://api.github.com/orgs//repos", "https://api.github.com/users/a%2Fb/repos"):
        with pytest.raises(ValueError):
            c._validate_api_url(bad)
    for owner in ("a/b", "a?x", "", "a b"):
        with pytest.raises(ValueError):
            c.list_repos(owner)
    assert c._validate_api_url("https://api.github.com/repos/o/r/commits")


def test_jira_myself_projects_paging_and_errors():
    def routes(url):
        p = urlsplit(url)
        if p.path == "/rest/api/3/myself":
            return 200, {"displayName": "Ann", "emailAddress": "ann@x.io", "accountId": "secret"}
        start = int(parse_qs(p.query)["startAt"][0])
        rows = [{"key": "PAY", "name": "Payments"}, {"key": "SEC"}]
        return 200, {"values": rows[start:start + 1], "isLast": start + 1 >= len(rows)}

    t = Fake(jira, routes)
    c = jira.JiraClient("https://a.atlassian.net", "tok", email="a@b.c", transport=t)
    assert c.myself() == {"displayName": "Ann", "emailAddress": "ann@x.io"}
    assert c.projects() == [{"key": "PAY", "name": "Payments"}, {"key": "SEC", "name": "SEC"}]
    assert t.calls[0][1]["Authorization"].startswith("Basic ") and "tok" not in t.calls[0][0]
    bad = jira.JiraClient("https://a.atlassian.net", "tok", transport=Fake(jira, lambda u: (403, {"errorMessages": ["tok"]})))
    with pytest.raises(jira.JiraAPIError) as e:
        bad.myself()
    assert e.value.status == 403 and "tok" not in str(e.value)
    odd = jira.JiraClient("https://a.atlassian.net", "tok", transport=Fake(jira, lambda u: (200, [])))
    with pytest.raises(jira.JiraAPIError):
        odd.projects()


def test_jira_projects_page_bound():
    c = jira.JiraClient("https://a.atlassian.net", "t", transport=Fake(
        jira, lambda u: (200, {"values": [{"key": "AA", "name": "A"}], "isLast": False})))
    assert len(c.projects()) == 5


def test_slack_auth_channels_users():
    def routes(url):
        p = urlsplit(url)
        q = parse_qs(p.query)
        if p.path == "/api/auth.test":
            return 200, {"ok": True, "user": "bot", "team": "Acme", "url": "x"}
        if p.path == "/api/conversations.list":
            assert q["types"] == ["public_channel,private_channel"] and q["exclude_archived"] == ["true"]
            if "cursor" in q:
                return 200, {"ok": True, "channels": [{"id": "C2", "name": "ops", "is_private": True}]}
            return 200, {"ok": True, "channels": [{"id": "C1", "name": "dev", "is_member": True}],
                         "response_metadata": {"next_cursor": "abc"}}
        assert p.path == "/api/users.list"
        return 200, {"ok": True, "members": [
            {"id": "U1", "name": "ann", "real_name": "Ann A", "profile": {"display_name": "annie"}},
            {"id": "U2", "name": "bob", "real_name": "Bob B", "profile": {"display_name": ""}},
            {"id": "U3", "name": "cy", "profile": {}},
            {"id": "U4", "name": "gone", "deleted": True},
            {"id": "B1", "name": "robot", "is_bot": True}]}

    t = Fake(slack, routes)
    c = slack.SlackClient("xoxb-tok", transport=t)
    assert c.auth_test() == {"user": "bot", "team": "Acme"}
    assert c.channels() == [{"id": "C1", "name": "dev", "is_private": False, "is_member": True},
                            {"id": "C2", "name": "ops", "is_private": True, "is_member": False}]
    assert c.users() == {"U1": "annie", "U2": "Bob B", "U3": "cy", "B1": "robot"}
    assert all("xoxb-tok" not in url for url, _ in t.calls) and t.calls[0][1]["Authorization"] == "Bearer xoxb-tok"


def test_slack_errors_sanitized_and_paging_bounded():
    c = slack.SlackClient("t", transport=Fake(slack, lambda u: (200, {"ok": False, "error": "invalid_auth"})))
    with pytest.raises(slack.SlackAPIError, match="invalid_auth"):
        c.auth_test()
    c = slack.SlackClient("t", transport=Fake(slack, lambda u: (200, {"ok": False, "error": "bad token xoxb-1"})))
    with pytest.raises(slack.SlackAPIError) as e:
        c.channels()
    assert "xoxb" not in str(e.value)
    loop = slack.SlackClient("t", transport=Fake(slack, lambda u: (200, {
        "ok": True, "channels": [{"id": "C"}], "response_metadata": {"next_cursor": "x"}})))
    assert len(loop.channels()) == 5
    with pytest.raises(slack.SlackAPIError):
        slack.SlackClient("t", transport=Fake(slack, lambda u: (200, {"ok": True, "members": "no"}))).users()
