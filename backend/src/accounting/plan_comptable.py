"""Comptes structurels du Plan Comptable des Entreprises (PCE) tunisien.

Ce module ne définit que les comptes "structurels" utilisés dans les schémas
d'écritures standard (tiers, TVA, amortissements).
Les comptes de charges (classe 6) et de produits (classe 7) sont définis dans
cost_catalog.yaml et portés par chaque CostCatalogEntry.

Source : Système Comptable des Entreprises (SCE), Tunisie.
Tous les codes doivent être confirmés avec le comptable BIAT IT avant production.
"""


class ComptesTiers:
    """Comptes de tiers (classe 4)."""
    FOURNISSEURS = "401"    # dettes fournisseurs
    CLIENTS = "411"         # créances clients
    PERSONNEL = "421"       # personnel — rémunérations dues


class ComptesTVA:
    """Comptes de TVA (classe 4)."""
    TVA_DEDUCTIBLE = "4366"    # TVA sur achats (récupérable)
    TVA_COLLECTEE = "4367"     # TVA sur ventes (à reverser à l'État)


class ComptesAmortissement:
    """Comptes d'amortissement (dotations classe 6, cumulés classe 2)."""
    # Dotation (charge annuelle/mensuelle)
    DOTATION = "6811"

    # Amortissements cumulés — par nature d'immobilisation
    # Correspondance avec les comptes d'immobilisation du cost_catalog.yaml :
    #   2183 Matériel informatique  → 2893
    #   2284 Logiciels              → 2894
    #   2184 Matériel de bureau     → 2884
    AMORT_MATERIEL_INFORMATIQUE = "2893"
    AMORT_LOGICIELS = "2894"
    AMORT_MATERIEL_BUREAU = "2884"

    # Mapping immobilisation → compte d'amortissement cumulé
    AMORT_PAR_COMPTE_IMMO: dict[str, str] = {
        "2183": "2893",
        "2284": "2894",
        "2184": "2884",
        "2844": "2854",   # mobilier
        "2241": "2841",   # agencements
    }

    @classmethod
    def get_amort_compte(cls, compte_immo: str) -> str:
        """Retourne le compte d'amortissement cumulé pour une immobilisation."""
        return cls.AMORT_PAR_COMPTE_IMMO.get(compte_immo, "2899")
