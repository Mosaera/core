import pytest
from langchain_ollama import ChatOllama, OllamaEmbeddings
from mosaera_core.config import ProviderConfig, Settings
from mosaera_core.models import (
    ModelConfigError,
    _build_model_kwargs,
    _supports_reasoning,
    get_chat_model,
    get_embeddings,
    list_model_sources,
    provider_catalog,
)


def test_reasoning_family_detection() -> None:
    assert _supports_reasoning("gpt-oss:20b")
    assert _supports_reasoning("deepseek-r1:32b")
    assert not _supports_reasoning("qwen3-coder:30b")  # coder variants: no thinking
    assert not _supports_reasoning("llama3:8b")


def test_gateway_binds_role_models_offline() -> None:
    s = Settings()
    for role, expected in (
        ("pm", s.pm_model),
        ("coder", s.coder_model),
        ("reviewer", s.reviewer_model),
    ):
        model = get_chat_model(role, s)  # type: ignore[arg-type]
        assert isinstance(model, ChatOllama)
        assert model.model == expected
        # Lifecycle hardening: bounded context + bounded call time everywhere.
        assert model.num_ctx == s.ollama_num_ctx
        assert model.client_kwargs == {"timeout": s.ollama_timeout}


def _num_ctx(role: str, s: Settings) -> int:
    model = get_chat_model(role, s)  # type: ignore[arg-type]
    assert isinstance(model, ChatOllama)  # narrows for .num_ctx
    return int(model.num_ctx or 0)


def test_coder_num_ctx_override_is_coder_only() -> None:
    # Opt-in: a bigger context for the coder (biggest transcript) leaves the
    # other roles on the global default.
    s = Settings(coder_num_ctx=32768)
    assert _num_ctx("coder", s) == 32768
    assert _num_ctx("pm", s) == s.ollama_num_ctx
    # Default (None) → coder shares the global.
    assert _num_ctx("coder", Settings()) == Settings().ollama_num_ctx


def test_embeddings_carry_client_timeout() -> None:
    s = Settings()
    emb = get_embeddings(s)
    assert isinstance(emb, OllamaEmbeddings)
    assert emb.client_kwargs == {"timeout": s.ollama_timeout}


# --- BYOM (#21): provider dispatch ---------------------------------------


def test_build_kwargs_ollama_keeps_local_knobs() -> None:
    s = Settings()
    provider, model, kwargs = _build_model_kwargs("coder", s)
    assert provider == "ollama"
    assert model == s.coder_model
    assert kwargs["num_ctx"] == s.ollama_num_ctx
    assert "reasoning" in kwargs
    assert kwargs["client_kwargs"] == {"timeout": s.ollama_timeout}


def test_build_kwargs_hosted_omits_ollama_knobs() -> None:
    # A stray num_ctx/reasoning/client_kwargs would make ChatOpenAI raise.
    s = Settings(
        role_providers={"coder": "openai"},
        coder_model="gpt-4o",
        providers={"openai": ProviderConfig(api_key="sk-test", base_url="https://x/v1")},
    )
    provider, model, kwargs = _build_model_kwargs("coder", s)
    assert (provider, model) == ("openai", "gpt-4o")
    assert kwargs["api_key"] == "sk-test"
    assert kwargs["base_url"] == "https://x/v1"
    assert "num_ctx" not in kwargs
    assert "reasoning" not in kwargs
    assert "client_kwargs" not in kwargs
    assert "temperature" in kwargs  # OpenAI-compatible providers accept it


def test_build_kwargs_anthropic_omits_temperature_on_current_tiers() -> None:
    # The current Anthropic tiers (Fable/Mythos 5, Opus 4.7+, Sonnet 5+) reject an explicit
    # `temperature` (HTTP 400 "temperature is deprecated for this model") — so it must NOT be
    # sent. Found live when a Sonnet escalation errored out on a real run.
    s = Settings(
        role_providers={"coder": "anthropic"},
        coder_model="claude-sonnet-5",
        providers={"anthropic": ProviderConfig(api_key="sk-ant-test")},
    )
    provider, model, kwargs = _build_model_kwargs("coder", s)
    assert (provider, model) == ("anthropic", "claude-sonnet-5")
    assert "temperature" not in kwargs  # omitted — this model 400s on it
    assert kwargs["api_key"] == "sk-ant-test"


def test_build_kwargs_anthropic_keeps_temperature_on_older_models() -> None:
    # Older Anthropic models (Sonnet 4.x, Opus 4.5/4.6, Haiku 4.5, Claude 3.x) still accept
    # `temperature` — so the role's low temperature IS sent, restoring reproducibility (M7). The
    # omission is model-level, not a blanket anthropic rule.
    s = Settings(
        role_providers={"coder": "anthropic"},
        coder_model="claude-sonnet-4-6",
        providers={"anthropic": ProviderConfig(api_key="sk-ant-test")},
    )
    _provider, model, kwargs = _build_model_kwargs("coder", s)
    assert model == "claude-sonnet-4-6"
    assert "temperature" in kwargs  # older model — keeps the low role temperature


def test_anthropic_temperature_predicate_is_deny_by_default() -> None:
    # M7: the accept-list enumerates VETTED versions, not a bare `claude-sonnet-4` prefix — so an
    # unvetted future sonnet-4 (which might 400 on temperature, as sonnet-5 does) omits it.
    from mosaera_core.models import _anthropic_accepts_temperature

    assert _anthropic_accepts_temperature("claude-sonnet-4-6")  # vetted → accepts
    assert _anthropic_accepts_temperature("claude-sonnet-4-0")
    assert _anthropic_accepts_temperature("claude-3-5-sonnet")  # the stable 3.x line
    assert not _anthropic_accepts_temperature("claude-sonnet-5")  # current tier → 400s, omit
    assert not _anthropic_accepts_temperature("claude-opus-4-8")
    assert not _anthropic_accepts_temperature("claude-sonnet-4-9")  # UNVETTED future → deny


def test_hosted_without_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    s = Settings(role_providers={"coder": "openai"}, coder_model="gpt-4o")
    with pytest.raises(ModelConfigError, match="API key"):
        get_chat_model("coder", s)


def test_locked_provider_key_raises_model_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A stored key encrypted under a key we no longer have must surface as a clean, catchable
    # ModelConfigError at the point of USE — not a raw SecretKeyError/500 (M-2).
    from cryptography.fernet import Fernet
    from mosaera_memory import encrypt_secret

    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    ciphertext = encrypt_secret("sk-real-key")
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())  # wrong key → locked
    s = Settings(
        role_providers={"coder": "openai"},
        coder_model="gpt-4o",
        providers={"openai": ProviderConfig(api_key=ciphertext)},
    )
    with pytest.raises(ModelConfigError, match="can't be decrypted"):
        _build_model_kwargs("coder", s)


def test_hosted_with_stored_key_builds_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_openai import ChatOpenAI

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    s = Settings(
        role_providers={"coder": "openai"},
        coder_model="gpt-4o",
        providers={"openai": ProviderConfig(api_key="sk-test")},
    )
    assert isinstance(get_chat_model("coder", s), ChatOpenAI)


def test_hosted_env_key_satisfies_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_openai import ChatOpenAI

    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    s = Settings(role_providers={"coder": "openai"}, coder_model="gpt-4o")
    assert isinstance(get_chat_model("coder", s), ChatOpenAI)


def test_unknown_provider_raises() -> None:
    s = Settings(
        role_providers={"pm": "nope"},
        providers={"nope": ProviderConfig(api_key="x")},
    )
    with pytest.raises(ModelConfigError):
        get_chat_model("pm", s)


def test_list_model_sources_includes_configured_hosted_provider() -> None:
    s = Settings(
        role_providers={"coder": "openai"},
        coder_model="gpt-4o",
        providers={"openai": ProviderConfig(api_key="sk")},
    )
    groups = {g["source"]: g["models"] for g in list_model_sources(s)}
    assert "Openai" in groups
    assert "gpt-4o" in groups["Openai"]  # bound model is always present


def test_list_model_sources_served_marks_what_is_actually_pulled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#119 O1-O3: a configured-but-not-pulled Ollama model appears in `models` (so it's still
    pickable / shows the role's current binding) but NOT in `served` — the picker's honest
    signal for "not pulled yet", instead of being indistinguishable from a real, ready model."""

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"models": [{"name": "gpt-oss:20b"}]}

    monkeypatch.setattr("httpx.get", lambda *a, **k: _Resp())
    s = Settings(coder_model="qwen3-coder:30b")  # bound, but NOT in the fake served list
    groups = {g["source"]: g for g in list_model_sources(s)}
    ollama = groups["Ollama"]
    assert "gpt-oss:20b" in ollama["served"]
    assert "qwen3-coder:30b" in ollama["models"] and "qwen3-coder:30b" not in ollama["served"]


def test_provider_catalog_shape() -> None:
    cat = {p["id"]: p for p in provider_catalog()}
    assert cat["ollama"]["local"] is True
    assert cat["ollama"]["env_key"] is None
    assert cat["openai"]["local"] is False
    assert cat["openai"]["env_key"] == "OPENAI_API_KEY"


# --- BYOM live model discovery (validate key → list the models it grants) --------


class _FakeResp:
    def __init__(self, status_code: int = 200, data: object = None) -> None:
        self.status_code = status_code
        self._data = data or {}

    def raise_for_status(self) -> None:
        pass

    def json(self) -> object:
        return self._data


def _fake_get(data: object, capture: dict | None = None):
    def _get(url, headers=None, timeout=None):  # type: ignore[no-untyped-def]
        if capture is not None:
            capture["url"], capture["headers"] = url, headers
        return _FakeResp(200, data)

    return _get


def test_fetch_provider_models_openai_filters_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaera_core.models as m

    m._MODEL_CACHE.clear()
    cap: dict = {}
    monkeypatch.setattr(
        m.httpx,
        "get",
        _fake_get(
            {"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4o"}, {"id": "text-embedding-3-small"}]},
            cap,
        ),
    )
    out = m.fetch_provider_models("openai", "sk-test", force=True)
    assert out == ["gpt-4o", "gpt-4o-mini"]  # sorted; the embedding model is filtered out
    assert cap["url"].endswith("/models")
    assert cap["headers"]["Authorization"] == "Bearer sk-test"


def test_fetch_provider_models_anthropic_uses_x_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaera_core.models as m

    m._MODEL_CACHE.clear()
    cap: dict = {}
    monkeypatch.setattr(m.httpx, "get", _fake_get({"data": [{"id": "claude-x"}]}, cap))
    assert m.fetch_provider_models("anthropic", "sk-ant", force=True) == ["claude-x"]
    assert "api.anthropic.com" in cap["url"]
    assert cap["headers"]["x-api-key"] == "sk-ant"


def test_fetch_provider_models_cache_avoids_refetch(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaera_core.models as m

    m._MODEL_CACHE.clear()
    monkeypatch.setattr(m.httpx, "get", _fake_get({"data": [{"id": "gpt-4o"}]}))
    first = m.fetch_provider_models("openai", "sk-c", force=True)

    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("should have served the cache without a network call")

    monkeypatch.setattr(m.httpx, "get", _boom)
    assert m.fetch_provider_models("openai", "sk-c") == first  # cache hit
    assert m.cached_provider_models("openai", "sk-c") == first
    assert m.cached_provider_models("openai", "a-different-key") is None  # key-scoped


def test_fetch_provider_models_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaera_core.models as m
    from mosaera_core.models import ProviderAuthError

    m._MODEL_CACHE.clear()
    monkeypatch.setattr(m.httpx, "get", lambda *a, **k: _FakeResp(status_code=401))
    with pytest.raises(ProviderAuthError):
        m.fetch_provider_models("openai", "bad-key", force=True)


def test_list_model_sources_prefers_cached_live_models(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaera_core.models as m

    m._MODEL_CACHE.clear()
    monkeypatch.setattr(m, "list_models", lambda s: [])  # skip the Ollama network call
    s = Settings(providers={"openai": ProviderConfig(api_key="sk-live")})
    # No cache yet → the curated suggestions are the fallback.
    before = {g["source"]: g["models"] for g in m.list_model_sources(s)}
    assert "gpt-4o" in before.get("Openai", [])
    # A fetch populates the cache → the live list now wins.
    monkeypatch.setattr(m.httpx, "get", _fake_get({"data": [{"id": "gpt-5-live"}]}))
    m.fetch_provider_models("openai", "sk-live", force=True)
    after = {g["source"]: g["models"] for g in m.list_model_sources(s)}
    assert after["Openai"] == ["gpt-5-live"]


# --- Prompt caching: the request side of the 96%-input problem ------------------------------
#
# Two runs measured 2026-08-21: 440,075 input / 13,058 output and 271,490 / 9,745 — with
# `cache_read: 0` on both, because nothing ever ASKED for caching. `cost.py` has read the cache
# fields since 2026-08-20; only the request was missing.


def _anthropic(**over: object) -> Settings:
    return Settings(
        role_providers={"coder": "anthropic"},
        coder_model="claude-haiku-4-5",
        providers={"anthropic": ProviderConfig(api_key="sk-ant-test")},
        **over,  # type: ignore[arg-type]
    )


def test_anthropic_requests_prompt_caching_by_default() -> None:
    _p, _m, kwargs = _build_model_kwargs("coder", _anthropic())
    assert kwargs["model_kwargs"] == {"cache_control": {"type": "ephemeral"}}


def test_the_knob_turns_prompt_caching_off() -> None:
    # The off arm exists so the effect can be A/B'd from one deployment. Absent entirely rather
    # than set-to-false: an unrecognised key in the payload is not a safe way to say "no".
    _p, _m, kwargs = _build_model_kwargs("coder", _anthropic(prompt_cache_enabled=False))
    assert "model_kwargs" not in kwargs


def test_ollama_never_receives_the_cache_kwarg() -> None:
    # `_build_model_kwargs`' own docstring warns that a kwarg a constructor does not accept makes
    # it RAISE. Ollama reports no cache metrics either, so there is nothing to ask for.
    _p, _m, kwargs = _build_model_kwargs("coder", Settings())
    assert "model_kwargs" not in kwargs


def test_openai_never_receives_the_cache_kwarg() -> None:
    # Caching here is an Anthropic request shape, not a generic hosted-provider one.
    s = Settings(
        role_providers={"coder": "openai"},
        coder_model="gpt-5",
        providers={"openai": ProviderConfig(api_key="sk-test")},
    )
    provider, _m, kwargs = _build_model_kwargs("coder", s)
    assert provider == "openai"
    assert "model_kwargs" not in kwargs


def test_the_cached_prefix_is_byte_stable_across_builds() -> None:
    """A cache that stops hitting fails SILENTLY — no error, just a bill.

    Caching pays only while the head of the prompt is byte-identical call to call. That holds
    today by construction (`coder_system` takes three booleans resolved once at team-build time;
    no task text, listing, timestamp or uuid), and nothing stops a future edit from interpolating
    something variable there. This pins the property so such an edit fails HERE rather than
    quietly costing money in production.
    """
    from mosaera_agents.prompts import coder_system

    first = coder_system(allow_delete=False, scratch_enabled=True, tester_owns_tests=True)
    second = coder_system(allow_delete=False, scratch_enabled=True, tester_owns_tests=True)
    assert first == second
    assert first.strip(), "an empty system prompt would 'pass' this test vacuously"
    # No obvious non-determinism smuggled into the cached head.
    for marker in ("2026-", "T0", "run-", "0x"):
        assert marker not in first[:2000], f"{marker!r} looks like variable content in the prefix"


def test_ollama_keeps_the_model_resident_so_its_prefix_cache_survives_a_gate() -> None:
    """Ollama's prefix cache is automatic, but an UNLOAD dumps it — and the default is 5 minutes.

    Guided mode routinely idles longer than that while a human reads a write gate, so without an
    explicit keep_alive the next call recomputes the whole transcript. Invisible in every number we
    record: `prompt_eval_count` reports the request's context size, not what was recomputed.
    """
    _p, _m, kwargs = _build_model_kwargs("coder", Settings())
    assert kwargs["keep_alive"] == "30m"


def test_keep_alive_is_operator_settable() -> None:
    _p, _m, kwargs = _build_model_kwargs("coder", Settings(ollama_keep_alive="-1"))
    assert kwargs["keep_alive"] == "-1"  # -1 = never unload


def test_hosted_providers_never_receive_keep_alive() -> None:
    # A local-residency knob would be a stray kwarg on ChatAnthropic/ChatOpenAI, and the
    # `_build_model_kwargs` docstring is explicit that those raise.
    _p, _m, kwargs = _build_model_kwargs("coder", _anthropic())
    assert "keep_alive" not in kwargs
