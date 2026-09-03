from mosaera_connectors.redact import scrub_credentials


def test_scrubs_gitlab_oauth2_token() -> None:
    text = "fatal: unable to access 'https://oauth2:glpat-secret123@gitlab.example/g/r.git/': 403"
    out = scrub_credentials(text)
    assert "glpat-secret123" not in out
    assert "https://***@gitlab.example/g/r.git" in out


def test_scrubs_github_x_access_token() -> None:
    text = "remote: https://x-access-token:ghp_abcdef@github.com/o/r.git denied"
    out = scrub_credentials(text)
    assert "ghp_abcdef" not in out
    assert "https://***@github.com/o/r.git" in out


def test_scrubs_bare_token_userinfo() -> None:
    assert scrub_credentials("http://tok3n@host/x") == "http://***@host/x"


def test_leaves_credential_free_text_untouched() -> None:
    text = "fatal: repository 'https://gitlab.example/g/r.git' not found"
    assert scrub_credentials(text) == text
    assert scrub_credentials("no urls here at all") == "no urls here at all"
