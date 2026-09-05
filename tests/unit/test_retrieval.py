"""Chunking, corpus provenance, embeddings, and the memory store."""

from __future__ import annotations

import pytest

from triage.retrieval.chunking import chunk_document
from triage.retrieval.corpus import CorpusError, load_corpus, parse_document
from triage.retrieval.embeddings import HashingEmbedder, build_embedder, cosine
from triage.retrieval.store import MemoryStore

DOC = """---
title: Variables
source_url: https://example.invalid/vars
license: Apache-2.0
tags: [config_error]
---

# Variables

Variable.get raises KeyError when the key is absent.

# Connections

BaseHook.get_connection raises AirflowNotFoundException when the conn_id is absent.
"""


def document(text: str = DOC):
    return parse_document(text, doc_id="corpus/airflow/vars.md", path=None)  # type: ignore[arg-type]


def test_frontmatter_provenance_is_parsed():
    doc = document()

    assert doc.title == "Variables"
    assert doc.source_url == "https://example.invalid/vars"
    assert doc.license == "Apache-2.0"
    assert doc.tags == ("config_error",)
    assert doc.body.startswith("# Variables")


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter at all",
        "---\ntitle: x\n---\nbody",  # missing source_url and license
        "---\n- a\n- b\n---\nbody",  # frontmatter is not a mapping
    ],
)
def test_documents_without_provenance_are_rejected(text):
    with pytest.raises(CorpusError):
        document(text)


def test_chunk_ids_are_stable_and_carry_provenance():
    chunks = chunk_document(document(), chunk_tokens=40, chunk_overlap=8)

    assert [c.chunk_id for c in chunks] == [
        f"corpus/airflow/vars.md#{i:03d}" for i in range(len(chunks))
    ]
    assert all(c.source_url == "https://example.invalid/vars" for c in chunks)
    assert all(c.license == "Apache-2.0" for c in chunks)
    assert "corpus/airflow/vars.md" in chunks[0].header


def test_headings_split_chunks():
    chunks = chunk_document(document(), chunk_tokens=400, chunk_overlap=0)

    assert len(chunks) == 2
    assert "Variable.get" in chunks[0].text
    assert "AirflowNotFoundException" in chunks[1].text


def test_long_sections_window_with_overlap():
    body = "---\ntitle: t\nsource_url: u\nlicense: l\n---\n\n# H\n\n" + " ".join(
        f"word{i}" for i in range(400)
    )
    chunks = chunk_document(document(body), chunk_tokens=100, chunk_overlap=20)

    assert len(chunks) > 1
    first_words = chunks[0].text.split()
    second_words = chunks[1].text.split()
    assert set(first_words) & set(second_words), "overlap should share words"


def test_hashing_embedder_is_deterministic_and_normalized():
    embedder = HashingEmbedder(dim=64)

    a, b = embedder.embed(["KeyError variable missing", "KeyError variable missing"])

    assert a == b
    assert cosine(a, b) == pytest.approx(1.0)
    assert len(a) == 64


def test_hashing_embedder_separates_unrelated_text():
    embedder = HashingEmbedder(dim=512)

    config_text, oom_text = embedder.embed(
        [
            "Variable.get raised KeyError because AIRFLOW_VAR_S3_BUCKET is unset",
            "Task exited with return code Negsignal.SIGKILL after the OOM killer",
        ]
    )

    assert cosine(config_text, oom_text) < 0.3


def test_build_embedder_rejects_unknown_names():
    with pytest.raises(ValueError, match="unknown embedder"):
        build_embedder("word2vec", 128)


def test_memory_store_round_trips_and_ranks(tmp_path):
    store = MemoryStore(tmp_path / "index.json")
    embedder = HashingEmbedder(dim=256)
    chunks = chunk_document(document(), chunk_tokens=400, chunk_overlap=0)

    assert store.rebuild(chunks, embedder) == 2

    results = store.search("AirflowNotFoundException conn_id absent", embedder, k=2)

    assert results[0].chunk.text.count("AirflowNotFoundException") == 1
    assert results[0].score >= results[1].score
    # A fresh handle reads the persisted index.
    assert MemoryStore(tmp_path / "index.json").count() == 2


def test_empty_store_returns_no_results(tmp_path):
    store = MemoryStore(tmp_path / "missing.json")

    assert store.count() == 0
    assert store.search("anything", HashingEmbedder(dim=32)) == []


def test_the_vendored_corpus_all_has_provenance():
    """A corpus document without frontmatter is a corpus bug, not a warning."""
    documents = load_corpus("corpus")

    assert len(documents) >= 8
    assert all(doc.source_url and doc.license for doc in documents)
