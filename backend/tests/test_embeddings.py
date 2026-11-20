import math
import types

import pytest

from app.services import embedding_service as emb


class FakeClient:
    def __init__(self, dim=768, fail=None, short=False):
        self.dim, self.fail, self.short, self.calls = dim, fail, short, []
        self.models = self

    def embed_content(self, model, contents, config):
        self.calls.append(len(contents))
        if self.fail:
            raise self.fail
        n = len(contents) - 1 if self.short else len(contents)
        return types.SimpleNamespace(embeddings=[types.SimpleNamespace(values=[3.0, 4.0] + [0.0] * (self.dim - 2)) for _ in range(n)])


@pytest.fixture(autouse=True)
def no_sdk(monkeypatch):
    monkeypatch.setattr(emb, "_build_config", lambda *a, **k: None)  # avoid needing the SDK in unit tests


def run(texts, client, **kw):
    return emb.embed_texts(texts, client=client, model="gemini-embedding-001", dimension=768, **kw)


def test_returns_768_normalised_vectors():
    vec = run(["hello"], FakeClient())[0]
    assert len(vec) == 768 and math.isclose(math.sqrt(sum(v * v for v in vec)), 1.0)
    assert len(emb.embed_text("hello", client=FakeClient(), model="m", dimension=768)) == 768


def test_batches_requests():
    client = FakeClient()
    assert len(run([f"t{i}" for i in range(120)], client)) == 120
    assert client.calls == [50, 50, 20]


def test_rejects_wrong_dimension_count_and_empty_text():
    with pytest.raises(emb.EmbeddingError):
        run(["a"], FakeClient(dim=3072))
    with pytest.raises(emb.EmbeddingError):
        run(["a", "b"], FakeClient(short=True))
    with pytest.raises(emb.EmbeddingError):
        run(["ok", "   "], FakeClient())
    assert run([], FakeClient()) == []


def test_api_failure_is_wrapped_and_not_leaked():
    err = RuntimeError("request with key=SECRET123 failed")
    with pytest.raises(emb.EmbeddingError) as e:
        run(["a"], FakeClient(fail=err))
    assert "SECRET123" not in str(e.value)


def test_retries_transient_errors(monkeypatch):
    monkeypatch.setattr(emb.time, "sleep", lambda s: None)
    err = RuntimeError("busy")
    err.code = 429
    client = FakeClient(fail=err)
    with pytest.raises(emb.EmbeddingError):
        run(["a"], client)
    assert len(client.calls) == emb.MAX_ATTEMPTS
