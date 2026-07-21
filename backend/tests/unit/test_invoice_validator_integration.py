"""Integration tests: every cost-catalog category must pass InvoiceValidator."""
from __future__ import annotations

import pytest

from src.extraction.invoice_validator import InvoiceValidator

_v = InvoiceValidator()

# Minimal invoice text template per catalog category.
# Each entry must generate enough signal to clear _MIN_SCORE = 3.
_CATEGORY_TEXTS = {
    "telecommunications": (
        "OOREDOO TUNISIE SA\nMF: 0038472K/A/M/000\n"
        "Facture N° FAC-2026-01-OOREDOO\n"
        "Abonnement fibre optique 1 Gbps\n"
        "TVA 19%: 712.500 TND\nTotal TTC: 4,462.500 TND"
    ),
    "formation_personnel": (
        "GLOBAL TECH TRAINING\nMF: 1256398F/A/M/000\n"
        "Facture N° FAC-2026-06-GTT\n"
        "Formation AWS Cloud Practitioner — 3 jours\n"
        "Montant HT: 6,500.000 TND\nTVA: 0%\nTotal TTC: 6,500.000 TND"
    ),
    "licences_saas": (
        "MICROSOFT TUNISIE SARL\nMF: 0764321K/A/M/000\n"
        "Facture N° FAC-2026-13-MS\n"
        "Renouvellement Microsoft 365 — 60 licences\n"
        "TVA 19%: 3,420.000 TND\nTotal TTC: 21,420.000 TND"
    ),
    "materiel_informatique": (
        "DELL TECHNOLOGIES TN\nMF: 0567891M/A/M/000\n"
        "Facture N° FAC-2026-16-DELL\n"
        "Lot 4 serveurs Dell PowerEdge R760\n"
        "Montant HT: 62,000.000 TND\nTVA 19%: 11,780.000 TND\n"
        "Total TTC: 73,780.000 TND"
    ),
    "honoraires_conseil": (
        "KPMG TUNISIE\nMF: 0098765J/A/M/000\n"
        "Facture N° FAC-2026-14-KPMG\n"
        "Honoraires audit processus DSI — S1 2026\n"
        "TVA 19%: 2,280.000 TND\nTotal TTC: 14,280.000 TND"
    ),
    "fournitures_bureau": (
        "PAPETERIE DU CENTRE\nMF: 0876543J/A/M/000\n"
        "Facture N° FAC-2026-12-PDC\n"
        "Ramettes A4, classeurs, fournitures bureau\n"
        "TVA 19%: 123.500 TND\nTotal TTC: 773.500 TND"
    ),
    "gardiennage_securite": (
        "SECURITAS TUNISIE\nMF: 0887632B/A/M/000\n"
        "Facture N° FAC-2026-04-SECURITAS\n"
        "Gardiennage et surveillance immeuble siège\n"
        "TVA 19%: 988.000 TND\nTotal TTC: 6,188.000 TND"
    ),
    "maintenance_informatique": (
        "NEXIA INFORMATIQUE SARL\nMF: 1472583D/A/M/000\n"
        "Facture N° FAC-2026-03-NEXIA\n"
        "Contrat TMA serveurs et postes de travail\n"
        "TVA 19%: 855.000 TND\nTotal TTC: 5,355.000 TND"
    ),
    "electricite_steg": (
        "STEG - Societe Tunisienne de l'Electricite et du Gaz\n"
        "MF: 0000045A/P/M/000\n"
        "Facture N° FAC-2026-03-STEG\n"
        "Consommation electrique Data Center\n"
        "TVA 19%: 456.000 TND\nTotal TTC: 2,856.000 TND"
    ),
}


class TestAllCatalogCategoriesPass:
    """Every cost-catalog category must pass InvoiceValidator.

    Ensures no valid supplier invoice category is accidentally blocked.
    """

    @pytest.mark.parametrize("category", list(_CATEGORY_TEXTS.keys()))
    def test_category_passes_validation(self, category: str) -> None:
        text = _CATEGORY_TEXTS[category]
        result = _v.validate(text)
        assert result is None, (
            f"Category '{category}' was unexpectedly rejected by InvoiceValidator"
        )

    def test_primary_catalog_categories_covered(self) -> None:
        """The 9 primary BIAT IT cost categories all have test cases."""
        primary = {
            "telecommunications", "formation_personnel", "licences_saas",
            "materiel_informatique", "honoraires_conseil", "fournitures_bureau",
            "gardiennage_securite", "maintenance_informatique", "electricite_steg",
        }
        tested = set(_CATEGORY_TEXTS.keys())
        missing = primary - tested
        assert not missing, (
            f"Primary catalog IDs missing validator test: {missing}"
        )

    def test_no_category_text_is_below_min_chars(self) -> None:
        for cat, text in _CATEGORY_TEXTS.items():
            assert len(text.strip()) >= _v._MIN_CHARS, (
                f"Category '{cat}' test text is below _MIN_CHARS={_v._MIN_CHARS}"
            )

    def test_all_categories_have_numeric_values(self) -> None:
        import re
        pattern = re.compile(_v._NUMERIC_RE.pattern)
        for cat, text in _CATEGORY_TEXTS.items():
            nums = pattern.findall(text)
            assert nums, f"Category '{cat}' has no formatted numbers"
