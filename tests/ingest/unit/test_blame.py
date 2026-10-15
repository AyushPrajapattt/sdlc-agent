from hackfront.ingest.blame import blame
from hackfront.ingest.demo import data as d

NEW = "@@ -0,0 +1,3 @@\n+a\n+b\n+c"


def texts(result):
    return [(x["text"], x["blame"]) for x in result["lines"]]


def test_new_file_attributes_every_line():
    r = blame([("c1", NEW)])
    assert r == {"lines": [{"text": t, "blame": "c1"} for t in "abc"], "complete": True}


def test_replace_insert_delete_and_offsets_across_hunks():
    base = "@@ -0,0 +1,8 @@\n" + "\n".join(f"+l{i}" for i in range(1, 9))
    # c2: replace l2, then (offset +1 after) insert after l5, delete l8 -- three hunks, -U0 style
    c2 = ("@@ -2 +2 @@\n-l2\n+L2\n"
          "@@ -5,0 +6 @@\n+new\n"
          "@@ -8 +10,0 @@\n-l8")
    r = blame([("c1", base), ("c2", c2)])
    assert r["complete"]
    assert texts(r) == [("l1", "c1"), ("L2", "c2"), ("l3", "c1"), ("l4", "c1"), ("l5", "c1"),
                        ("new", "c2"), ("l6", "c1"), ("l7", "c1")]


def test_context_lines_keep_old_blame_and_no_newline_marker_ignored():
    c2 = "@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n\\ No newline at end of file"
    r = blame([("c1", NEW), ("c2", c2)])
    assert texts(r) == [("a", "c1"), ("B", "c2"), ("c", "c1")]


def test_blank_context_line_with_stripped_space():
    r = blame([("c1", "@@ -0,0 +1,2 @@\n+a\n+"), ("c2", "@@ -1,2 +1,3 @@\n a\n\n+z")])
    assert texts(r) == [("a", "c1"), ("", "c1"), ("z", "c2")]


def test_content_that_looks_like_a_hunk_header_is_data():
    r = blame([("c1", "@@ -0,0 +1,2 @@\n+@@ -1 +1 @@\n+x")])
    assert r["complete"] and r["lines"][0]["text"] == "@@ -1 +1 @@"


def test_mismatch_is_incomplete_and_invents_nothing():
    r = blame([("c1", NEW), ("c2", "@@ -1,2 +1,2 @@\n a\n-WRONG\n+B")])
    assert r["complete"] is False and r["lines"] == []
    assert "does not apply" in r["note"] and "c2" in r["note"]


def test_context_mismatch_and_out_of_range():
    assert not blame([("c1", NEW), ("c2", "@@ -1 +1 @@\n-zzz\n+q")])["complete"]
    assert not blame([("c1", NEW), ("c2", "@@ -9 +9 @@\n-a\n+q")])["complete"]


def test_missing_patch():
    r = blame([("c1", NEW), ("c2", None)])
    assert r["complete"] is False and r["lines"] == [] and "no patch" in r["note"]


def test_history_must_start_with_creation():
    r = blame([("c1", "@@ -1 +1 @@\n-a\n+b")])
    assert r["complete"] is False and r["lines"] == [] and "creating" in r["note"]


def test_truncated_or_garbage_patch():
    assert not blame([("c1", "@@ -0,0 +1,3 @@\n+a")])["complete"]
    assert not blame([("c1", "not a patch")])["complete"]


def test_deletion_gives_no_lines_and_a_note():
    r = blame([("c1", NEW), ("c2", "@@ -1,3 +0,0 @@\n-a\n-b\n-c")])
    assert r["lines"] == [] and r["complete"] is False and "deleted" in r["note"]


def test_recreated_after_deletion():
    r = blame([("c1", NEW), ("c2", "@@ -1,3 +0,0 @@\n-a\n-b\n-c"), ("c3", "@@ -0,0 +1 @@\n+z")])
    assert r["complete"] and texts(r) == [("z", "c3")]


def test_no_patches():
    assert blame([])["complete"] is False


# ---- the demo history reproduces every final file exactly, with the expected blame
def replay(path):
    commits = sorted(d.COMMITS, key=lambda c: c["commit"]["author"]["date"])
    return blame([(c["sha"], f["patch"]) for c in commits for f in c["files"] if f["filename"] == path])


def test_demo_replay_reproduces_final_files():
    assert set(d.FINAL_FILES) == {f["filename"] for c in d.COMMITS for f in c["files"]}
    for path, text in d.FINAL_FILES.items():
        r = replay(path)
        assert r["complete"], (path, r)
        assert [x["text"] for x in r["lines"]] == text.splitlines(), path


def blamed(path, line):
    r = replay(path)
    return next(x["blame"] for x in r["lines"] if x["text"] == line)


def test_demo_key_lines():
    gw = "src/payments/gateway_client.py"
    assert blamed(gw, "MAX_RETRIES = 3") == d.C_RETRY["sha"]
    assert blamed(gw, '        headers = {"Idempotency-Key": attempt.idempotency_key}') == d.C_IDEM["sha"]
    assert blamed(gw, "class GatewayClient:") == d.C_BASE_PAY["sha"]
    assert blamed("src/payments/models.py", "    idempotency_key: str") == d.C_IDEM["sha"]
    assert blamed("src/payments/models.py", "class PaymentAttempt:") == d.C_BASE_PAY["sha"]
    sc = "src/auth/session_cache.py"
    assert blamed(sc, "SESSION_TTL_SECONDS = 900") == d.C_TTL["sha"]
    assert blamed(sc, "from .refresh import refresh_on_activity") == d.C_REFRESH["sha"]
    assert blamed(sc, "        return refresh_on_activity(entry)") == d.C_REFRESH["sha"]
    assert blamed(sc, "class SessionCache:") == d.C_BASE_AUTH["sha"]
    assert blamed("src/auth/refresh.py", "def refresh_on_activity(entry):") == d.C_REFRESH["sha"]
    assert blamed("requirements.txt", "requests==2.32.4") == d.C_BUMP["sha"]
    assert blamed("src/payments/README.md", "See gateway_client.py for the retry policy.") == d.C_INIT["sha"]


def test_demo_story_commits_follow_base_commits():
    by_sha = {c["sha"]: c for c in d.COMMITS}
    for c in d.COMMITS:
        for p in c["parents"]:
            assert by_sha[p["sha"]]["commit"]["author"]["date"] < c["commit"]["author"]["date"]
    assert d.C_BUMP["parents"][0]["sha"] == d.C_BASE_PAY["sha"]
    assert d.C_RETRY["files"][0]["patch"].count("@@ -") >= 1
