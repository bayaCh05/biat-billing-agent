"""Unit tests — PCEVectorStore (ChromaDB wrapper) : 3 collections
(pce_catalog, invoice_embeddings, audit_incidents), cycle de vie singleton,
dégradation (indisponible / échec d'embedding), sémantique upsert.

Ce fichier n'existait pas avant : chaque appelant du projet mocke
PCEVectorStore.get() à la frontière (test_ai_agents.py pour AnomalyAgent,
test_audit_agent.py pour AuditAgent) — aucune méthode réelle n'était
exercée directement. Ici, on construit une instance sans passer par
_init_client() (pas de vrai ChromaDB/disque touché) : les 3 collections
sont des MagicMock que chaque test configure, et PCEEmbedder.get() est
monkeypatché — cohérent avec la convention du projet ("mock tous les
dépendances externes").
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.ai_agents.rag.pce_vectorstore import PCEVectorStore
from src.cost_catalog.catalog import CostCatalogEntry
from src.models.enums import ChargeFlux, ChargeNature, ChargeType, Recurrence


def _bare_store(available: bool = True) -> PCEVectorStore:
    """Instance sans _init_client() réel — les 3 collections sont des
    MagicMock configurées par chaque test."""
    store = object.__new__(PCEVectorStore)
    store._client = MagicMock()
    store._pce_col = MagicMock()
    store._inv_col = MagicMock()
    store._incident_col = MagicMock()
    store._available = available
    return store


def _entry(id_: str = "licences_saas", label: str = "Licences SaaS") -> CostCatalogEntry:
    return CostCatalogEntry(
        id=id_, label=label, compte="622", nature=ChargeNature.FIXE,
        type_charge=ChargeType.OPEX, tva_rate=19.0, recurrence=Recurrence.MENSUELLE,
        flux=ChargeFlux.FOURNISSEUR, keywords=["saas", "abonnement"],
    )


def _patch_embedder(embed=None, embed_batch=None):
    fake = MagicMock()
    fake.embed.return_value = embed
    fake.embed_batch.return_value = embed_batch
    return patch("src.ai_agents.rag.embedder.PCEEmbedder.get", return_value=fake)


class TestSingletonAndInitClient:
    def setup_method(self):
        PCEVectorStore._instance = None

    def teardown_method(self):
        PCEVectorStore._instance = None

    def test_get_returns_same_instance(self):
        with patch("chromadb.PersistentClient"):
            a = PCEVectorStore.get()
            b = PCEVectorStore.get()
        assert a is b

    def test_successful_init_creates_three_collections_and_sets_available(self):
        fake_client = MagicMock()
        with patch("chromadb.PersistentClient", return_value=fake_client):
            store = PCEVectorStore()
        assert store.available is True
        assert fake_client.get_or_create_collection.call_count == 3

    def test_chromadb_failure_sets_available_false(self):
        with patch("chromadb.PersistentClient", side_effect=RuntimeError("disk full")):
            store = PCEVectorStore()
        assert store.available is False

    def test_telemetry_explicitly_disabled(self):
        """Data residency (CLAUDE.md) — chromadb's anonymized_telemetry
        defaults to True; must be explicitly opted out, not left to
        incidental non-network-calling behavior of the installed version."""
        with patch("chromadb.PersistentClient") as mock_client:
            PCEVectorStore()
        _, kwargs = mock_client.call_args
        assert kwargs["settings"].anonymized_telemetry is False


class TestInitializePCE:
    def test_unavailable_store_is_noop(self):
        store = _bare_store(available=False)
        store.initialize_pce([_entry()])
        store._pce_col.count.assert_not_called()

    def test_matching_count_skips_reindex_entirely(self):
        store = _bare_store()
        entries = [_entry(), _entry(id_="steg")]
        store._pce_col.count.return_value = len(entries)
        with patch.object(store, "_index_pce") as mock_index:
            store.initialize_pce(entries)
        mock_index.assert_not_called()
        store._pce_col.delete.assert_not_called()

    def test_stale_nonempty_index_deletes_before_reindexing(self):
        store = _bare_store()
        store._pce_col.count.return_value = 5  # existing docs, mismatched count
        with patch.object(store, "_index_pce") as mock_index:
            store.initialize_pce([_entry()])
        store._pce_col.delete.assert_called_once()
        mock_index.assert_called_once()

    def test_empty_collection_skips_delete_but_still_reindexes(self):
        store = _bare_store()
        store._pce_col.count.return_value = 0
        with patch.object(store, "_index_pce") as mock_index:
            store.initialize_pce([_entry(), _entry(id_="steg")])
        store._pce_col.delete.assert_not_called()
        mock_index.assert_called_once()


class TestIndexPCE:
    def test_embeds_and_adds_valid_entries(self):
        store = _bare_store()
        store._pce_col.count.return_value = 0
        entries = [_entry(id_="a", label="A"), _entry(id_="b", label="B")]
        with _patch_embedder(embed_batch=[[0.1, 0.2], [0.3, 0.4]]):
            store.initialize_pce(entries)

        store._pce_col.add.assert_called_once()
        kwargs = store._pce_col.add.call_args.kwargs
        assert kwargs["ids"] == ["a", "b"]
        assert kwargs["embeddings"] == [[0.1, 0.2], [0.3, 0.4]]
        assert kwargs["metadatas"][0]["compte"] == "622"

    def test_skips_entries_with_failed_embedding(self):
        store = _bare_store()
        store._pce_col.count.return_value = 0
        entries = [_entry(id_="a"), _entry(id_="b")]
        with _patch_embedder(embed_batch=[None, [0.3, 0.4]]):
            store.initialize_pce(entries)

        kwargs = store._pce_col.add.call_args.kwargs
        assert kwargs["ids"] == ["b"]

    def test_no_valid_embeddings_skips_add_entirely(self):
        store = _bare_store()
        store._pce_col.count.return_value = 0
        with _patch_embedder(embed_batch=[None]):
            store.initialize_pce([_entry()])
        store._pce_col.add.assert_not_called()


class TestSearchPCE:
    def test_unavailable_returns_empty(self):
        store = _bare_store(available=False)
        assert store.search_pce("licences") == []

    def test_embed_failure_returns_empty(self):
        store = _bare_store()
        with _patch_embedder(embed=None):
            assert store.search_pce("licences") == []

    def test_returns_results_with_similarity_from_distance(self):
        store = _bare_store()
        store._pce_col.count.return_value = 3
        store._pce_col.query.return_value = {
            "metadatas": [[{"id": "licences_saas", "label": "Licences SaaS"}]],
            "distances": [[0.2]],
        }
        with _patch_embedder(embed=[0.1, 0.2]):
            results = store.search_pce("licences")

        assert results == [{"id": "licences_saas", "label": "Licences SaaS", "similarity": 0.8}]

    def test_query_exception_returns_empty(self):
        store = _bare_store()
        store._pce_col.count.return_value = 1
        store._pce_col.query.side_effect = RuntimeError("chromadb crashed")
        with _patch_embedder(embed=[0.1]):
            assert store.search_pce("x") == []


class TestReindexPCE:
    def test_unavailable_is_noop(self):
        store = _bare_store(available=False)
        with patch.object(store, "_index_pce") as mock_index:
            store.reindex_pce([_entry()])
        mock_index.assert_not_called()

    def test_deletes_collection_and_recreates_before_reindexing(self):
        store = _bare_store()
        new_col = MagicMock()
        store._client.get_or_create_collection.return_value = new_col
        with patch.object(store, "_index_pce") as mock_index:
            store.reindex_pce([_entry()])

        store._client.delete_collection.assert_called_once()
        assert store._pce_col is new_col
        mock_index.assert_called_once()

    def test_delete_failure_is_swallowed_and_reindex_still_happens(self):
        store = _bare_store()
        store._client.delete_collection.side_effect = RuntimeError("collection missing")
        with patch.object(store, "_index_pce") as mock_index:
            store.reindex_pce([_entry()])
        mock_index.assert_called_once()


class TestStoreInvoiceEmbedding:
    def test_unavailable_is_noop(self):
        store = _bare_store(available=False)
        store.store_invoice_embedding("inv-1", "text")
        store._inv_col.add.assert_not_called()

    def test_embed_failure_is_noop(self):
        store = _bare_store()
        with _patch_embedder(embed=None):
            store.store_invoice_embedding("inv-1", "text")
        store._inv_col.add.assert_not_called()

    def test_new_invoice_is_added_directly(self):
        store = _bare_store()
        store._inv_col.get.return_value = {"ids": []}
        with _patch_embedder(embed=[0.1, 0.2]):
            store.store_invoice_embedding("inv-1", "text", invoice_number="F001")

        store._inv_col.delete.assert_not_called()
        store._inv_col.add.assert_called_once_with(
            ids=["inv-1"], embeddings=[[0.1, 0.2]], documents=["text"],
            metadatas=[{"invoice_number": "F001"}],
        )

    def test_existing_invoice_is_deleted_before_re_adding(self):
        store = _bare_store()
        store._inv_col.get.return_value = {"ids": ["inv-1"]}
        with _patch_embedder(embed=[0.1]):
            store.store_invoice_embedding("inv-1", "text")

        store._inv_col.delete.assert_called_once_with(ids=["inv-1"])
        store._inv_col.add.assert_called_once()

    def test_missing_invoice_number_defaults_to_empty_string(self):
        store = _bare_store()
        store._inv_col.get.return_value = {"ids": []}
        with _patch_embedder(embed=[0.1]):
            store.store_invoice_embedding("inv-1", "text")
        assert store._inv_col.add.call_args.kwargs["metadatas"] == [{"invoice_number": ""}]

    def test_chromadb_exception_is_caught_not_raised(self):
        store = _bare_store()
        store._inv_col.get.side_effect = RuntimeError("boom")
        with _patch_embedder(embed=[0.1]):
            store.store_invoice_embedding("inv-1", "text")  # must not raise


class TestSearchSimilarInvoices:
    def test_unavailable_returns_empty(self):
        store = _bare_store(available=False)
        assert store.search_similar_invoices("text") == []

    def test_empty_collection_returns_empty(self):
        store = _bare_store()
        store._inv_col.count.return_value = 0
        assert store.search_similar_invoices("text") == []

    def test_embed_failure_returns_empty(self):
        store = _bare_store()
        store._inv_col.count.return_value = 5
        with _patch_embedder(embed=None):
            assert store.search_similar_invoices("text") == []

    def test_excludes_given_id_from_results(self):
        store = _bare_store()
        store._inv_col.count.return_value = 3
        store._inv_col.query.return_value = {
            "ids": [["inv-1", "inv-2"]],
            "metadatas": [[{"invoice_number": "F001"}, {"invoice_number": "F002"}]],
            "distances": [[0.1, 0.2]],
        }
        with _patch_embedder(embed=[0.1]):
            results = store.search_similar_invoices("text", exclude_id="inv-1")

        assert len(results) == 1
        assert results[0]["invoice_id"] == "inv-2"

    def test_query_exception_returns_empty(self):
        store = _bare_store()
        store._inv_col.count.return_value = 3
        store._inv_col.query.side_effect = RuntimeError("boom")
        with _patch_embedder(embed=[0.1]):
            assert store.search_similar_invoices("text") == []


class TestIndexIncident:
    def test_unavailable_is_noop(self):
        store = _bare_store(available=False)
        store.index_incident("risque", "r1", "text", {})
        store._incident_col.add.assert_not_called()

    def test_embed_failure_is_noop(self):
        store = _bare_store()
        with _patch_embedder(embed=None):
            store.index_incident("risque", "r1", "text", {})
        store._incident_col.add.assert_not_called()

    def test_doc_id_combines_source_type_and_id(self):
        store = _bare_store()
        store._incident_col.get.return_value = {"ids": []}
        with _patch_embedder(embed=[0.1]):
            store.index_incident("risque", "r1", "text", {"severity": "ELEVE"})

        kwargs = store._incident_col.add.call_args.kwargs
        assert kwargs["ids"] == ["risque:r1"]
        assert kwargs["metadatas"] == [
            {"source_type": "risque", "source_id": "r1", "severity": "ELEVE"}
        ]

    def test_upserts_existing_incident(self):
        store = _bare_store()
        store._incident_col.get.return_value = {"ids": ["anomaly:f1"]}
        with _patch_embedder(embed=[0.1]):
            store.index_incident("anomaly", "f1", "text", {})
        store._incident_col.delete.assert_called_once_with(ids=["anomaly:f1"])

    def test_chromadb_exception_is_caught_not_raised(self):
        store = _bare_store()
        store._incident_col.get.side_effect = RuntimeError("boom")
        with _patch_embedder(embed=[0.1]):
            store.index_incident("risque", "r1", "text", {})  # must not raise


class TestSearchSimilarIncidents:
    def test_unavailable_returns_empty(self):
        store = _bare_store(available=False)
        assert store.search_similar_incidents("text") == []

    def test_empty_collection_returns_empty(self):
        store = _bare_store()
        store._incident_col.count.return_value = 0
        assert store.search_similar_incidents("text") == []

    def test_embed_failure_returns_empty(self):
        store = _bare_store()
        store._incident_col.count.return_value = 2
        with _patch_embedder(embed=None):
            assert store.search_similar_incidents("text") == []

    def test_filters_out_results_below_min_similarity(self):
        store = _bare_store()
        store._incident_col.count.return_value = 2
        store._incident_col.query.return_value = {
            "documents": [["texte incident proche", "texte incident lointain"]],
            "metadatas": [[
                {"source_type": "risque", "source_id": "r1", "date": "2026-06-01"},
                {"source_type": "anomaly", "source_id": "f1", "date": "2026-05-01"},
            ]],
            "distances": [[0.1, 0.5]],  # similarités : 0.9, 0.5
        }
        with _patch_embedder(embed=[0.1]):
            results = store.search_similar_incidents("text", min_similarity=0.75)

        assert len(results) == 1
        assert results[0]["source_id"] == "r1"
        assert results[0]["similarity"] == 0.9

    def test_excerpt_is_truncated_to_200_chars(self):
        store = _bare_store()
        store._incident_col.count.return_value = 1
        long_text = "a" * 300
        store._incident_col.query.return_value = {
            "documents": [[long_text]],
            "metadatas": [[{"source_type": "risque", "source_id": "r1", "date": "2026-06-01"}]],
            "distances": [[0.1]],
        }
        with _patch_embedder(embed=[0.1]):
            results = store.search_similar_incidents("text")

        assert len(results[0]["excerpt"]) == 200

    def test_query_exception_returns_empty(self):
        store = _bare_store()
        store._incident_col.count.return_value = 1
        store._incident_col.query.side_effect = RuntimeError("boom")
        with _patch_embedder(embed=[0.1]):
            assert store.search_similar_incidents("text") == []
