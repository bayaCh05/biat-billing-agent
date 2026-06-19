"""Natural language to SQL query engine for BIAT IT billing data.

All inference is local — Ollama qwen2.5:3b. No cloud calls.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import text  # noqa: I001

_SYSTEM_PROMPT = """\
Tu es un assistant financier pour BIAT IT (filiale informatique de la banque BIAT, Tunisie).
Tu as accès à une base de données SQLite avec les tables suivantes:

TABLE: invoices  (factures fournisseurs reçues)
  id, issuer_name, invoice_number, invoice_date, due_date,
  amount_ht, tva_rate, tva_amount, amount_ttc,
  status, direction, cost_catalog_id, charge_type,
  accounting_compte, human_review_required, paid_at
  Valeurs status: RECEIVED, EXTRACTING, EXTRACTED, CLASSIFYING,
    CLASSIFIED, VALIDATING, VALIDATED, EXPORTED, JOURNALING,
    JOURNALED, PAID, FLAGGED, ERROR, EXTRACTION_FAILED
  Valeurs direction: SUPPLIER (fournisseur), CLIENT, UNKNOWN
  Valeurs charge_type: OPEX, CAPEX
  Catégories (cost_catalog_id): telecommunications, formation_personnel,
    licences_saas, materiel_informatique, honoraires_conseil,
    fournitures_bureau, gardiennage_securite,
    maintenance_informatique, electricite_steg

TABLE: journal_entries  (écritures comptables)
  id, reference, date_ecriture, description,
  source_invoice_id, source_asset_id

TABLE: journal_lines  (lignes de chaque écriture)
  id, entry_id, compte, libelle, debit, credit
  Comptes importants: 401 (fournisseurs), 4366 (TVA déductible),
    6xxx (charges OPEX), 2xxx (immobilisations CAPEX),
    6811 (dotations amortissements), 28xx (amortissements cumulés)

TABLE: assets  (immobilisations CAPEX)
  id, designation, compte_immobilisation, compte_amortissement,
  acquisition_date, acquisition_cost_ht,
  useful_life_years, depreciation_method, fully_depreciated

TABLE: client_invoices  (factures émises à BIAT groupe)
  id, invoice_number, invoice_date, due_date,
  client_name, amount_ht, tva_amount, amount_ttc,
  status, paid_at
  Valeurs status: draft, sent, paid, cancelled

TABLE: chartes_projet  (contrats projets)
  id, project_id, project_name, budget_jh, taux_jh, valid_from

TABLE: phases  (phases de chaque projet)
  id, project_id, name, planned_jh, consumed_jh, status, closed_date

TABLE: asset_project_links  (clé de répartition CAPEX → projets)
  asset_id, project_id, allocation_pct

Réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans explication en dehors du JSON:
{
  "sql": "SELECT ...",
  "explanation": "courte explication en français de ce qui est calculé"
}

Règles SQL importantes:
- SQLite uniquement — utilise strftime('%Y', colonne) pour extraire l'année
- Factures traitées (dépense réelle): status IN ('VALIDATED','EXPORTED','JOURNALED','PAID')
- Factures fournisseurs: direction = 'SUPPLIER'
- Année courante: strftime('%Y', invoice_date) = '2026'
- Pour les VNC (valeur nette comptable): acquisition_cost_ht - (acquisition_cost_ht/useful_life_years) * (strftime('%Y','now') - strftime('%Y',acquisition_date))
- N'utilise JAMAIS INSERT, UPDATE, DELETE, DROP, ALTER, CREATE
- Si la question ne peut pas être répondue avec ces tables, retourne:
  {"sql": null, "explanation": "raison pour laquelle la question ne peut pas être répondue"}

Pièges à éviter:
- cost_catalog_id est une colonne texte directe dans la table invoices (ex: 'telecommunications', 'formation_personnel'). Il n'existe PAS de table cost_catalog séparée.
- "En attente de validation" ou "à valider" signifie status = 'FLAGGED' (factures bloquées pour revue humaine).
- date_ecriture est une colonne de journal_entries, PAS de journal_lines. Pour filtrer les écritures par date, toujours faire: SELECT SUM(jl.debit) FROM journal_lines jl JOIN journal_entries je ON jl.entry_id = je.id WHERE strftime('%Y-%m', je.date_ecriture) = '2026-06'
- "Montant total des écritures" d'un mois = SUM(jl.debit) des lignes de ce mois. Exemple correct: SELECT SUM(jl.debit) AS total FROM journal_lines jl JOIN journal_entries je ON jl.entry_id = je.id WHERE strftime('%Y-%m', je.date_ecriture) = '2026-06'
- IMPORTANT: La table journal_entries n'a PAS de colonne direction, direction_supplier, status, ou issuer_name. Ses seules colonnes sont: id, reference, date_ecriture, description, source_invoice_id, source_asset_id. N'utilise JAMAIS je.direction ni je.status.
- La table assets ne contient PAS de colonne charge_type. Tous les enregistrements de assets sont des immobilisations CAPEX.
- "Factures en retard de paiement" = status = 'EXPORTED' AND due_date < date('now')  (expédiées mais pas encore payées)
- TVA déductible (compte 4366) apparaît en DEBIT dans journal_lines. Utilise SUM(debit) pour le solde TVA déductible. Exemple correct: SELECT SUM(debit) FROM journal_lines WHERE compte = '4366'
- TVA collectée (compte 4367) apparaît en CREDIT dans journal_lines. Utilise SUM(credit) pour le solde TVA collectée.
- IMPORTANT: Les factures émises aux clients (BIAT groupe, etc.) sont EXCLUSIVEMENT dans la table client_invoices, PAS dans invoices. La table invoices contient UNIQUEMENT les factures reçues de fournisseurs. Pour "ce qu'on a facturé à BIAT / un client", utilise TOUJOURS client_invoices. Exemple: SELECT SUM(amount_ttc) FROM client_invoices WHERE client_name LIKE '%BIAT%' AND strftime('%Y-%m', invoice_date) = '2026-05' AND status != 'cancelled'
- Pour la VNC, utilise EXACTEMENT cette formule avec les parenthèses: acquisition_cost_ht - (acquisition_cost_ht/useful_life_years) * (strftime('%Y','now') - strftime('%Y',acquisition_date)). Exemple: SELECT SUM(acquisition_cost_ht - (acquisition_cost_ht/useful_life_years) * (strftime('%Y','now') - strftime('%Y',acquisition_date))) AS vnc FROM assets WHERE fully_depreciated = 0
"""


class NLQueryEngine:
    """Converts a French question into SQL, runs it, returns a French answer.

    Processing chain:
      French question → Ollama (local) → SQL → SQLite → French answer
    No data leaves the server.
    """

    def __init__(
        self,
        engine,
        ollama_url: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
    ) -> None:
        self.engine = engine
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    # ── Public ────────────────────────────────────────────────────────────────

    def query(self, question: str) -> dict:
        """Run a French natural-language question against the database.

        Returns:
            {
              "question":    str,
              "sql":         str | None,
              "result":      list[dict] | None,
              "answer":      str,        # formatted French answer
              "explanation": str,        # one-line description of the query
            }
        """
        raw = self._ask_llm(question)
        parsed = self._parse_llm_response(raw)

        if parsed is None:
            return self._err(question, "Réponse LLM non parsable.", raw[:200])

        sql = parsed.get("sql")
        explanation = parsed.get("explanation", "")

        if not sql:
            return {
                "question": question, "sql": None, "result": None,
                "answer": explanation or "Je ne peux pas répondre à cette question.",
                "explanation": explanation,
            }

        if not self._is_safe(sql):
            return self._err(question, "Seules les requêtes SELECT sont autorisées.",
                             explanation)

        sql = self._sanitize_sql(sql)
        rows, exec_error = self._run_sql(sql)
        if exec_error:
            # One automatic retry: feed the SQL error back to the LLM
            retry_question = (
                f"{question}\n\n"
                f"[ERREUR SQL précédente: {exec_error}]\n"
                f"[SQL incorrect: {sql}]\n"
                "Génère une nouvelle requête SQL corrigée qui évite cette erreur."
            )
            raw2 = self._ask_llm(retry_question)
            parsed2 = self._parse_llm_response(raw2)
            if parsed2 and parsed2.get("sql") and self._is_safe(parsed2["sql"]):
                sql = self._sanitize_sql(parsed2["sql"])
                explanation = parsed2.get("explanation", explanation)
                rows, exec_error = self._run_sql(sql)
            if exec_error:
                return self._err(question, f"Erreur SQL: {exec_error}", explanation)

        answer = self._format_answer(explanation, rows)
        return {
            "question": question, "sql": sql, "result": rows,
            "answer": answer, "explanation": explanation,
        }

    # ── LLM call ─────────────────────────────────────────────────────────────

    def _ask_llm(self, question: str) -> str:
        import requests
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user",   "content": question},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except requests.exceptions.ConnectionError:
            return json.dumps({
                "sql": None,
                "explanation": "Ollama n'est pas disponible. Démarrez-le avec `ollama serve`.",
            })
        except Exception as e:
            return json.dumps({"sql": None, "explanation": f"Erreur LLM: {e}"})

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_llm_response(self, raw: str) -> dict | None:
        raw = raw.strip()
        # Strip markdown fences if present
        m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
        if m:
            raw = m.group(1)
        # Extract first {...} block
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _sanitize_sql(sql: str) -> str:
        """Strip column references that don't exist on journal_entries."""
        # Remove AND/WHERE conditions referencing non-existent columns on journal_entries
        # e.g. "AND je.direction = 'SUPPLIER'" or "WHERE je.direction = 'SUPPLIER'"
        invalid_je_cols = re.compile(
            r'\s+AND\s+\w+\.(direction|status|issuer_name|charge_type)\s*=\s*\'[^\']*\'',
            re.IGNORECASE,
        )
        return invalid_je_cols.sub("", sql)

    @staticmethod
    def _is_safe(sql: str) -> bool:
        first_word = sql.strip().split()[0].upper() if sql.strip() else ""
        if first_word != "SELECT":
            return False
        forbidden = re.compile(
            r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|REPLACE)\b',
            re.IGNORECASE,
        )
        return not forbidden.search(sql)

    def _run_sql(self, sql: str) -> tuple[list[dict], str | None]:
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql))
                rows = [dict(r._mapping) for r in result]
            return rows, None
        except Exception as e:
            return [], str(e)

    @staticmethod
    def _format_answer(explanation: str, rows: list[dict]) -> str:
        if not rows:
            return f"{explanation} — Aucun résultat trouvé."

        # Single scalar (SUM, COUNT, AVG…)
        if len(rows) == 1 and len(rows[0]) == 1:
            value = list(rows[0].values())[0]
            if value is None:
                return f"{explanation} — Aucune donnée disponible."
            if isinstance(value, float):
                return f"{explanation} : **{value:,.3f} TND**"
            if isinstance(value, int):
                return f"{explanation} : **{value:,}**"
            return f"{explanation} : **{value}**"

        # Small table (≤ 15 rows) — format as bullet list
        if len(rows) <= 15:
            lines = []
            for row in rows:
                parts = []
                for k, v in row.items():
                    if isinstance(v, float):
                        parts.append(f"{k}: {v:,.3f}")
                    elif v is None:
                        parts.append(f"{k}: —")
                    else:
                        parts.append(f"{k}: {v}")
                lines.append("• " + " | ".join(parts))
            header = explanation + "\n" if explanation else ""
            return header + "\n".join(lines)

        return f"{explanation} — {len(rows)} résultats trouvés."

    @staticmethod
    def _err(question: str, answer: str, explanation: str) -> dict:
        return {
            "question": question, "sql": None, "result": None,
            "answer": answer, "explanation": explanation,
        }
