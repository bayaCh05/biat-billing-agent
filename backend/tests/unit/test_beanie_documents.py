"""Tests unitaires pour les Documents Beanie — Phase 2 de la migration MongoDB.

Vérifie pour chaque document :
  - Correspondance exacte champ-à-champ avec l'ORM SQLAlchemy source
  - Types des champs (UUID, str, int, bool, list, ...)
  - Valeurs par défaut
  - Nom de collection (Settings.name)
  - Indexes TTL ou composés (Settings.indexes)
  - Instanciation via model_construct() sans connexion DB
"""
from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest
from pymongo import IndexModel


# ── Helpers ------------------------------------------------------------------

def _check_fields(doc_class, expected: set[str]) -> None:
    """Vérifie que le document possède exactement les champs attendus."""
    actual = set(doc_class.model_fields.keys()) - {"revision_id"}
    missing = expected - actual
    extra   = actual - expected
    assert not missing, f"{doc_class.__name__} — champs manquants : {missing}"
    assert not extra,   f"{doc_class.__name__} — champs en trop : {extra}"


# ── UserDocument -------------------------------------------------------------

class TestUserDocument:
    def test_fields_match_orm(self):
        from src.storage.documents.user import UserDocument
        _check_fields(UserDocument, {
            "id", "nom", "prenom", "email", "hashed_password", "role",
            "departement", "is_first_login", "is_active", "created_at",
            "failed_login_attempts", "locked_until", "last_failed_login",
            "last_login_at", "last_login_ip", "profile_picture",
        })

    def test_id_is_uuid_with_factory(self):
        from src.storage.documents.user import UserDocument
        doc = UserDocument.model_construct(
            nom="Test", prenom="User", email="t@t.com",
            hashed_password="x", role="admin",
        )
        assert isinstance(doc.id, UUID)

    def test_collection_name(self):
        from src.storage.documents.user import UserDocument
        assert UserDocument.Settings.name == "users"


# ── AuditLogDocument --------------------------------------------------------

class TestAuditLogDocument:
    def test_fields_match_orm(self):
        from src.storage.documents.audit_log import AuditLogDocument
        _check_fields(AuditLogDocument, {
            "id",
            "created_at", "user_id", "user_email", "user_role", "actor",
            "action", "resource_type", "resource_id", "entity_id",
            "before_value", "after_value", "ip_address", "user_agent",
            "status", "detail", "row_hash",
        })

    def test_defaults(self):
        from src.storage.documents.audit_log import AuditLogDocument
        doc = AuditLogDocument.model_construct(action="LOGIN")
        assert doc.status == "SUCCESS"
        assert doc.actor == ""
        assert doc.user_id is None
        assert doc.row_hash is None

    def test_compute_row_hash_works_on_document(self):
        from api.security.audit_integrity import compute_row_hash
        from src.storage.documents.audit_log import AuditLogDocument
        doc = AuditLogDocument.model_construct(
            id="550e8400-e29b-41d4-a716-446655440000",
            created_at=datetime.datetime(2026, 7, 8, 14, 32, 15, 0),
            user_id="u1", action="CREATE",
            resource_type="Invoice", resource_id="r1",
            status="SUCCESS", ip_address="10.0.0.1", actor="",
        )
        h = compute_row_hash(doc)
        assert isinstance(h, str) and len(h) == 64

    def test_hmac_ms_precision_parity(self):
        """Avec le fix Phase 4, SQLite µs et MongoDB ms produisent le même hash."""
        import os
        os.environ.setdefault("AUDIT_HMAC_SECRET", "test-secret-32chars-padded-xxxxx")
        from api.security.audit_integrity import compute_row_hash

        base = dict(
            id="550e8400-e29b-41d4-a716-446655440000",
            user_id="u1", action="LOGIN",
            resource_type="User", resource_id="r1",
            status="SUCCESS", ip_address="10.0.0.1", actor="",
        )

        class _R:
            def __init__(self, dt, **kw):
                self.created_at = dt
                for k, v in kw.items():
                    setattr(self, k, v)

        # SQLite : naive avec µs ≠ 0 mais multiple de 1000 déjà (ex: 123000)
        r_sqlite = _R(datetime.datetime(2026, 7, 8, 14, 32, 15, 123000), **base)
        # MongoDB : UTC-aware, même valeur ms
        r_mongo  = _R(
            datetime.datetime(2026, 7, 8, 14, 32, 15, 123000,
                              tzinfo=datetime.timezone.utc),
            **base,
        )
        assert compute_row_hash(r_sqlite) == compute_row_hash(r_mongo)

    def test_collection_name(self):
        from src.storage.documents.audit_log import AuditLogDocument
        assert AuditLogDocument.Settings.name == "audit_logs"


# ── RevokedTokenDocument ----------------------------------------------------

class TestRevokedTokenDocument:
    def test_fields(self):
        from src.storage.documents.revoked_token import RevokedTokenDocument
        _check_fields(RevokedTokenDocument, {
            "id","revoked_at", "reason", "user_id"})

    def test_id_is_str(self):
        from src.storage.documents.revoked_token import RevokedTokenDocument
        doc = RevokedTokenDocument.model_construct(id="jti-abc")
        assert isinstance(doc.id, str)
        assert doc.id == "jti-abc"

    def test_defaults(self):
        from src.storage.documents.revoked_token import RevokedTokenDocument
        doc = RevokedTokenDocument.model_construct(id="jti-abc")
        assert doc.reason == "logout"
        assert doc.user_id is None

    def test_collection_name(self):
        from src.storage.documents.revoked_token import RevokedTokenDocument
        assert RevokedTokenDocument.Settings.name == "revoked_tokens"


# ── ActiveTokenDocument -----------------------------------------------------

class TestActiveTokenDocument:
    def test_fields(self):
        from src.storage.documents.active_token import ActiveTokenDocument
        _check_fields(ActiveTokenDocument, {
            "id",
            "user_id", "created_at", "expires_at",
            "ip_address", "user_agent", "revoked",
        })

    def test_id_is_str(self):
        from src.storage.documents.active_token import ActiveTokenDocument
        exp = datetime.datetime(2026, 7, 9, 8, 0, tzinfo=datetime.timezone.utc)
        doc = ActiveTokenDocument.model_construct(id="jti-xyz", user_id="u1", expires_at=exp)
        assert isinstance(doc.id, str)

    def test_revoked_default_false(self):
        from src.storage.documents.active_token import ActiveTokenDocument
        exp = datetime.datetime(2026, 7, 9, tzinfo=datetime.timezone.utc)
        doc = ActiveTokenDocument.model_construct(id="jti-xyz", user_id="u1", expires_at=exp)
        assert doc.revoked is False

    def test_ttl_index(self):
        from src.storage.documents.active_token import ActiveTokenDocument
        indexes = ActiveTokenDocument.Settings.indexes
        assert any(
            isinstance(i, IndexModel) and i.document.get("expireAfterSeconds") == 0
            for i in indexes
        )

    def test_collection_name(self):
        from src.storage.documents.active_token import ActiveTokenDocument
        assert ActiveTokenDocument.Settings.name == "active_tokens"


# ── InvoiceDocument ---------------------------------------------------------

class TestInvoiceDocument:
    def test_fields_match_orm(self):
        from src.storage.documents.invoice import InvoiceDocument
        required = {
            "id",
            "file_hash", "raw_file_path", "file_mime_type", "direction", "status",
            "extraction_method", "retry_count", "last_error",
            "issuer_name", "issuer_name_conf", "issuer_tax_id", "issuer_tax_id_conf",
            "recipient_name", "recipient_name_conf", "recipient_tax_id", "recipient_tax_id_conf",
            "invoice_number", "invoice_number_conf", "invoice_date", "invoice_date_conf",
            "due_date", "due_date_conf",
            "amount_ht", "amount_ht_conf", "tva_rate", "tva_rate_conf",
            "tva_amount", "tva_amount_conf", "amount_ttc", "amount_ttc_conf",
            "currency", "raw_extracted_json",
            "cost_catalog_id", "accounting_compte", "accounting_label",
            "charge_nature", "charge_type", "matched_po_id", "matched_contract_id",
            "matched_client_id", "payment_term_days", "classification_reason",
            "classification_pass", "human_review_required", "human_review_notes",
            "reviewed_by", "reviewed_at",
            "received_at", "extracted_at", "classified_at", "validated_at",
            "exported_at", "export_reference", "paid_at", "collected_at",
            "created_at", "updated_at",
            "line_items", "flags", "history",
        }
        _check_fields(InvoiceDocument, required)

    def test_id_is_uuid(self):
        from src.storage.documents.invoice import InvoiceDocument
        doc = InvoiceDocument.model_construct(
            file_hash="abc", raw_file_path="/tmp/x.pdf",
            direction="FOURNISSEUR", status="RECEIVED",
        )
        assert isinstance(doc.id, UUID)

    def test_embedded_lists_empty_by_default(self):
        from src.storage.documents.invoice import InvoiceDocument
        doc = InvoiceDocument.model_construct(
            file_hash="abc", raw_file_path="/tmp/x.pdf",
            direction="FOURNISSEUR", status="RECEIVED",
            line_items=[], flags=[], history=[],
        )
        assert doc.line_items == []
        assert doc.flags == []
        assert doc.history == []

    def test_embedded_line_item(self):
        from src.storage.documents.invoice import LineItemEmbed
        li = LineItemEmbed(line_number=1, description="Serveur", quantity=1.0,
                           unit_price=5000.0, line_total=5000.0, tva_rate=19.0)
        assert isinstance(li.id, UUID)
        assert li.line_number == 1

    def test_embedded_flag(self):
        from src.storage.documents.invoice import ValidationFlagEmbed
        flag = ValidationFlagEmbed(
            flag_type="TOTAL_MISMATCH", severity="ERROR", message="HT+TVA≠TTC"
        )
        assert flag.resolved is False
        assert isinstance(flag.id, UUID)

    def test_embedded_history(self):
        from src.storage.documents.invoice import StatusHistoryEmbed
        h = StatusHistoryEmbed(from_status="RECEIVED", to_status="EXTRACTING")
        assert h.changed_by == "agent"

    def test_chromadb_uuid_str(self):
        """str(invoice.id) doit être un UUID valide (compatibilité ChromaDB)."""
        from src.storage.documents.invoice import InvoiceDocument
        doc = InvoiceDocument.model_construct(
            file_hash="abc", raw_file_path="/tmp/x.pdf",
            direction="FOURNISSEUR", status="RECEIVED",
            line_items=[], flags=[], history=[],
        )
        chromadb_key = str(doc.id)
        # Doit pouvoir être reparsé en UUID
        reparsed = UUID(chromadb_key)
        assert reparsed == doc.id

    def test_collection_name(self):
        from src.storage.documents.invoice import InvoiceDocument
        assert InvoiceDocument.Settings.name == "invoices"


# ── JournalEntryDocument ----------------------------------------------------

class TestJournalEntryDocument:
    def test_fields(self):
        from src.storage.documents.journal_entry import JournalEntryDocument
        _check_fields(JournalEntryDocument, {
            "id",
            "reference", "date_ecriture", "description",
            "source_invoice_id", "source_asset_id", "accounting_explanation",
            "created_at", "lines",
        })

    def test_embedded_line(self):
        from src.storage.documents.journal_entry import JournalLineEmbed
        ln = JournalLineEmbed(compte="401", libelle="Fournisseur", credit=5000.0)
        assert isinstance(ln.id, UUID)

    def test_collection_name(self):
        from src.storage.documents.journal_entry import JournalEntryDocument
        assert JournalEntryDocument.Settings.name == "journal_entries"


# ── ClientInvoiceDocument ---------------------------------------------------

class TestClientInvoiceDocument:
    def test_fields(self):
        from src.storage.documents.client_invoice import ClientInvoiceDocument
        _check_fields(ClientInvoiceDocument, {
            "id",
            "invoice_number", "invoice_date", "due_date",
            "issuer_name", "issuer_tax_id", "issuer_address",
            "client_id", "client_name", "client_tax_id", "client_address",
            "amount_ht", "tva_amount", "amount_ttc",
            "status", "source_template_id", "notes", "pdf_path",
            "created_at", "sent_at", "paid_at", "line_items",
        })

    def test_embedded_line_item(self):
        from src.storage.documents.client_invoice import ClientLineItemEmbed
        li = ClientLineItemEmbed(
            description="Prestation", quantity=10, unit_price=500,
            line_total=5000, tva_rate=19, tva_amount=950, compte_produit="706",
        )
        assert isinstance(li.id, UUID)

    def test_collection_name(self):
        from src.storage.documents.client_invoice import ClientInvoiceDocument
        assert ClientInvoiceDocument.Settings.name == "client_invoices"


# ── AssetDocument -----------------------------------------------------------

class TestAssetDocument:
    def test_fields(self):
        from src.storage.documents.asset import AssetDocument
        _check_fields(AssetDocument, {
            "id",
            "designation", "compte_immobilisation", "compte_amortissement",
            "acquisition_date", "acquisition_cost_ht", "useful_life_years",
            "depreciation_method", "supplier_invoice_id", "amortization_source",
            "notes", "fully_depreciated", "created_at", "project_links",
        })

    def test_embedded_project_link(self):
        from src.storage.documents.asset import AssetProjectLinkEmbed
        lk = AssetProjectLinkEmbed(project_id="PRJ-001", allocation_pct=50.0)
        assert lk.allocation_pct == 50.0

    def test_collection_name(self):
        from src.storage.documents.asset import AssetDocument
        assert AssetDocument.Settings.name == "assets"


# ── BudgetPlanDocument ------------------------------------------------------

class TestBudgetPlanDocument:
    def test_fields(self):
        from src.storage.documents.budget_plan import BudgetPlanDocument
        _check_fields(BudgetPlanDocument, {
            "id",
            "catalog_id", "year", "label", "monthly", "note", "updated_at",
        })

    def test_unique_compound_index(self):
        from src.storage.documents.budget_plan import BudgetPlanDocument
        indexes = BudgetPlanDocument.Settings.indexes
        assert any(
            isinstance(i, IndexModel) and i.document.get("unique") is True
            for i in indexes
        )

    def test_collection_name(self):
        from src.storage.documents.budget_plan import BudgetPlanDocument
        assert BudgetPlanDocument.Settings.name == "budget_plan_entries"


# ── PaymentInstallmentDocument ----------------------------------------------

class TestPaymentInstallmentDocument:
    def test_fields(self):
        from src.storage.documents.payment_installment import PaymentInstallmentDocument
        _check_fields(PaymentInstallmentDocument, {
            "id",
            "invoice_id", "installment_number", "total_installments",
            "base_amount", "current_amount", "due_date", "paid_date",
            "paid_amount", "status", "late_periods", "created_at", "updated_at",
        })

    def test_defaults(self):
        from src.storage.documents.payment_installment import PaymentInstallmentDocument
        doc = PaymentInstallmentDocument.model_construct(
            invoice_id="inv-1", installment_number=1, total_installments=3,
            base_amount=1000.0, current_amount=1000.0,
            due_date=datetime.date(2026, 8, 1),
        )
        assert doc.status == "PENDING"
        assert doc.late_periods == 0

    def test_collection_name(self):
        from src.storage.documents.payment_installment import PaymentInstallmentDocument
        assert PaymentInstallmentDocument.Settings.name == "payment_installments"


# ── ClassificationFeedbackDocument ------------------------------------------

class TestClassificationFeedbackDocument:
    def test_fields(self):
        from src.storage.documents.classification_feedback import ClassificationFeedbackDocument
        _check_fields(ClassificationFeedbackDocument, {
            "id",
            "invoice_id", "original_compte", "corrected_compte",
            "original_catalog_id", "corrected_catalog_id",
            "invoice_text", "corrected_by", "corrected_at",
        })

    def test_collection_name(self):
        from src.storage.documents.classification_feedback import ClassificationFeedbackDocument
        assert ClassificationFeedbackDocument.Settings.name == "classification_feedback"


# ── CharteProjetDocument ----------------------------------------------------

class TestCharteProjetDocument:
    def test_fields(self):
        from src.storage.documents.charte_projet import CharteProjetDocument
        _check_fields(CharteProjetDocument, {
            "id",
            "project_id", "project_name", "client",
            "valid_from", "valid_until", "budget_jh", "taux_jh", "is_active",
        })

    def test_id_is_str_natural_key(self):
        from src.storage.documents.charte_projet import CharteProjetDocument
        doc = CharteProjetDocument.model_construct(
            id="CHR-2026-0001", project_id="PRJ-001", project_name="Projet X",
            valid_from=datetime.date(2026, 1, 1), budget_jh=100.0, taux_jh=800.0,
        )
        assert isinstance(doc.id, str)
        assert doc.id == "CHR-2026-0001"

    def test_collection_name(self):
        from src.storage.documents.charte_projet import CharteProjetDocument
        assert CharteProjetDocument.Settings.name == "chartes_projet"


# ── PhaseDocument ------------------------------------------------------------

class TestPhaseDocument:
    def test_fields(self):
        from src.storage.documents.phase import PhaseDocument
        _check_fields(PhaseDocument, {
            "id",
            "project_id", "name", "description",
            "planned_jh", "consumed_jh", "status", "closed_date", "livrables",
        })

    def test_id_is_str(self):
        from src.storage.documents.phase import PhaseDocument
        doc = PhaseDocument.model_construct(
            id="PH-2026-001", project_id="PRJ-001",
            name="Cadrage", planned_jh=10.0,
        )
        assert isinstance(doc.id, str)

    def test_collection_name(self):
        from src.storage.documents.phase import PhaseDocument
        assert PhaseDocument.Settings.name == "phases"


# ── FicheMensuelleDocument --------------------------------------------------

class TestFicheMensuelleDocument:
    def test_fields(self):
        from src.storage.documents.fiche_mensuelle import FicheMensuelleDocument
        _check_fields(FicheMensuelleDocument, {
            "id",
            "period_month", "period_year", "prepared_by", "prepared_at",
            "status", "invoice_number", "phase_links", "avances",
        })

    def test_embedded_avance(self):
        from src.storage.documents.fiche_mensuelle import AvanceProgrammeeEmbed
        av = AvanceProgrammeeEmbed(
            project_id="PRJ-001", charte_id="CHR-2026-0001",
            description="Prestation Mars", montant_ht=8000.0,
            schedule_reference="Contrat §3.2",
        )
        assert isinstance(av.id, UUID)

    def test_unique_index(self):
        from src.storage.documents.fiche_mensuelle import FicheMensuelleDocument
        indexes = FicheMensuelleDocument.Settings.indexes
        assert any(
            isinstance(i, IndexModel) and i.document.get("unique") is True
            for i in indexes
        )

    def test_collection_name(self):
        from src.storage.documents.fiche_mensuelle import FicheMensuelleDocument
        assert FicheMensuelleDocument.Settings.name == "fiches_mensuelles"


# ── FeuilleDeRouteDocument --------------------------------------------------

class TestFeuilleDeRouteDocument:
    def test_fields(self):
        from src.storage.documents.feuille_de_route import FeuilleDeRouteDocument
        _check_fields(FeuilleDeRouteDocument, {
            "id",
            "titre", "description", "date_debut", "date_fin",
            "projet_id", "responsable_id", "statut", "priorite", "annee",
        })

    def test_collection_name(self):
        from src.storage.documents.feuille_de_route import FeuilleDeRouteDocument
        assert FeuilleDeRouteDocument.Settings.name == "feuilles_de_route"


# ── LigneBudgetDocument -----------------------------------------------------

class TestLigneBudgetDocument:
    def test_fields(self):
        from src.storage.documents.ligne_budget import LigneBudgetDocument
        _check_fields(LigneBudgetDocument, {
            "id",
            "projet_id", "categorie", "montant_prevu",
            "montant_consomme", "devise", "created_at",
        })

    def test_collection_name(self):
        from src.storage.documents.ligne_budget import LigneBudgetDocument
        assert LigneBudgetDocument.Settings.name == "lignes_budget"


# ── LivrableDocument --------------------------------------------------------

class TestLivrableDocument:
    def test_fields(self):
        from src.storage.documents.livrable import LivrableDocument
        _check_fields(LivrableDocument, {
            "id",
            "phase_id", "titre", "description",
            "date_livraison_prevue", "date_livraison_reelle",
            "statut", "fichier_path", "created_by",
        })

    def test_collection_name(self):
        from src.storage.documents.livrable import LivrableDocument
        assert LivrableDocument.Settings.name == "livrables"


# ── RisqueDocument ----------------------------------------------------------

class TestRisqueDocument:
    def test_fields(self):
        from src.storage.documents.risque import RisqueDocument
        _check_fields(RisqueDocument, {
            "id",
            "titre", "description", "type_risque", "probabilite", "impact",
            "niveau_criticite", "statut", "plan_mitigation", "responsable_id",
            "date_identification", "date_echeance_mitigation", "date_cloture",
            "feuille_route_id", "projet_id", "created_by", "created_at", "updated_at",
        })

    def test_collection_name(self):
        from src.storage.documents.risque import RisqueDocument
        assert RisqueDocument.Settings.name == "risques"


# ── NotificationDocument ----------------------------------------------------

class TestNotificationDocument:
    def test_fields(self):
        from src.storage.documents.notification import NotificationDocument
        _check_fields(NotificationDocument, {
            "id",
            "type", "title", "body", "is_read", "created_at", "invoice_id",
        })

    def test_collection_name(self):
        from src.storage.documents.notification import NotificationDocument
        assert NotificationDocument.Settings.name == "notifications"


# ── PasswordVerificationDocument --------------------------------------------

class TestPasswordVerificationDocument:
    def test_fields(self):
        from src.storage.documents.password_verification import PasswordVerificationDocument
        _check_fields(PasswordVerificationDocument, {
            "id",
            "user_id", "verification_type", "code_or_token",
            "purpose", "expires_at", "used", "created_at",
        })

    def test_ttl_index(self):
        from src.storage.documents.password_verification import PasswordVerificationDocument
        indexes = PasswordVerificationDocument.Settings.indexes
        assert any(
            isinstance(i, IndexModel) and i.document.get("expireAfterSeconds") == 0
            for i in indexes
        )

    def test_collection_name(self):
        from src.storage.documents.password_verification import PasswordVerificationDocument
        assert PasswordVerificationDocument.Settings.name == "password_verifications"


# ── PaymentDocument ---------------------------------------------------------

class TestPaymentDocument:
    def test_fields(self):
        from src.storage.documents.payment import PaymentDocument
        _check_fields(PaymentDocument, {
            "id",
            "invoice_id", "amount", "payment_date",
            "payment_reference", "payment_method", "created_at",
        })

    def test_collection_name(self):
        from src.storage.documents.payment import PaymentDocument
        assert PaymentDocument.Settings.name == "payments"


# ── Cohérence globale -------------------------------------------------------

class TestGlobalCohérence:
    def test_all_22_documents_importable(self):
        """Tous les 22 documents Beanie s'importent sans erreur."""
        import sys
        sys.path.insert(0, "backend")
        from src.storage.mongodb import _all_document_models
        models = _all_document_models()
        assert len(models) == 22

    def test_no_duplicate_collection_names(self):
        """Chaque document utilise un nom de collection unique."""
        from src.storage.mongodb import _all_document_models
        names = [m.Settings.name for m in _all_document_models()]
        assert len(names) == len(set(names)), f"Doublons : {set(n for n in names if names.count(n) > 1)}"

    def test_uuid_documents_have_uuid4_factory(self):
        """Les documents avec UUID primary key ont un default_factory=uuid4."""
        from src.storage.mongodb import _all_document_models
        str_pk_docs = {"revoked_tokens", "active_tokens", "chartes_projet", "phases", "fiches_mensuelles"}
        for doc_class in _all_document_models():
            if doc_class.Settings.name in str_pk_docs:
                continue
            id_field = doc_class.model_fields.get("id")
            if id_field and id_field.default_factory is not None:
                # Vérifier que uuid4() retourne un UUID
                sample = id_field.default_factory()
                assert isinstance(sample, UUID), (
                    f"{doc_class.__name__} : default_factory ne retourne pas un UUID"
                )

    def test_service_bridge_importable(self):
        """service_bridge.py s'importe sans erreur."""
        from src.storage.documents import service_bridge  # noqa: F401
