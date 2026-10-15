from hackfront.agent.verify import NOT_ESTABLISHED, to_legacy, verify

EV = {"i1": {"id": "i1", "url": "https://x/1", "text": "Fixes PAY-412.\nRetry   cap stays at 3 for the budget."},
      "i2": {"id": "i2", "url": "https://x/2", "text": "Dana: keep 3."}}


def claim(text, status="supported", cites=(), note=""):
    return {"text": text, "status": status, "note": note, "cites": list(cites)}


def run(claims, summary="ok", gaps=(), sufficient=True, gap=""):
    return verify({"summary": summary, "claims": claims, "gaps": list(gaps)}, EV, sufficient, gap)


def test_verbatim_quote_is_whitespace_and_case_insensitive():
    out = run([claim("a", cites=[{"id": "i1", "quote": "RETRY cap stays\nat 3"}, {"id": "i2"}])])
    assert out["claims"][0]["cites"] == [{"node": "i1", "quote": "RETRY cap stays\nat 3"}, {"node": "i2"}]
    assert out["claims"][0]["status"] == "supported" and out["dropped"] == 0 and out["confidence"] == "high"


def test_fabricated_id_and_non_verbatim_quote_are_dropped_and_confidence_low():
    out = run([claim("a", cites=[{"id": "nope", "quote": "x"}, {"id": "i2", "quote": "Dana says keep 3"},
                                 {"id": "i1", "quote": "Fixes PAY-412"}])])
    c = out["claims"][0]
    assert c["cites"] == [{"node": "i1", "quote": "Fixes PAY-412"}] and c["status"] == "supported"
    assert out["dropped"] == 2 and out["confidence"] == "low" and any("2 citation" in g for g in out["gaps"])


def test_supported_without_verified_cite_is_downgraded_with_note():
    out = run([claim("a", cites=[{"id": "nope"}]), claim("b", note="my reasoning")])
    a, b = out["claims"]
    assert a["status"] == "inferred" and a["cites"] == [] and "no citation could be verified" in a["note"]
    assert b["status"] == "inferred" and b["note"].startswith("my reasoning ")  # supported with no cites at all
    assert out["confidence"] == "low" and not any(c["status"] == "supported" for c in out["claims"])


def test_unknown_keeps_no_cites_and_inferred_gets_a_note():
    out = run([claim("a", cites=[{"id": "i1"}]), claim("u", "unknown", [{"id": "i1"}], "missing ADR"),
               claim("i", "inferred", [{"id": "i2"}])])
    assert out["claims"][1]["cites"] == [] and out["claims"][1]["note"] == "missing ADR"
    assert out["claims"][2]["note"] and out["claims"][2]["cites"] == [{"node": "i2"}]
    assert out["dropped"] == 0 and out["confidence"] == "medium"


def test_urls_not_in_evidence_are_stripped_from_all_free_text():
    out = run([claim("see [https://evil/1] and https://x/1 now", cites=[{"id": "i1"}], note="https://evil/2")],
              summary="a [https://x/2] b [https://evil/9] c https://evil/8.", gaps=["read https://evil/3"])
    assert "evil" not in str(out) and "https://x/1" in out["claims"][0]["text"] and "[https://x/2]" in out["summary"]
    assert out["confidence"] == "low"


def test_confidence_rules():
    sup = claim("s", cites=[{"id": "i1"}])
    assert run([sup])["confidence"] == "high"
    assert run([sup], gaps=["no ADR"])["confidence"] == "medium"
    assert run([sup, claim("u", "unknown")])["confidence"] == "medium"
    assert run([sup], sufficient=False, gap="g")["confidence"] == "low"
    assert run([claim("u", "unknown")])["confidence"] == "low"
    assert run([])["claims"][0]["status"] == "unknown"  # never an empty claim list


def test_not_established_and_legacy_shape():
    assert NOT_ESTABLISHED["confidence"] == "low" and NOT_ESTABLISHED["summary"].startswith("Not established")
    assert [c["status"] for c in NOT_ESTABLISHED["claims"]] == ["unknown"] and NOT_ESTABLISHED["claims"][0]["cites"] == []
    out = run([claim("s", cites=[{"id": "i1"}]), claim("i", "inferred", [{"id": "i2"}], "why"), claim("u", "unknown", note="n")])
    legacy = to_legacy(out, EV)
    assert legacy["citations"] == ["https://x/1", "https://x/2"] and legacy["confidence"] == "medium"
    assert "(inferred)" in legacy["answer"] and "u n" in legacy["uncertainty"]
