"""Natural language to MongoDB aggregation query engine for BIAT IT billing data.

All inference is local — Ollama qwen2.5:3b. No cloud calls.

Migrated from the SQLite/SQLAlchemy version (raw SQL generation) to MongoDB —
the LLM now generates an aggregation pipeline (JSON) against a single
collection instead of a SQL string. Cross-collection joins ($lookup) are
deliberately not supported: the schema below documents which data now lives
embedded within a single document (journal_entries.lines, client_invoices
line items) precisely so most questions don't need one.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from uuid import UUID

_ALLOWED_COLLECTIONS = {
    "invoices", "journal_entries", "assets", "client_invoices",
    "chartes_projet", "phases",
}

# Aggregation stages that write, execute arbitrary JS, or expose server
# internals — never allowed in an LLM-generated pipeline. $lookup is banned
# too: not unsafe, just unsupported (see module docstring) — a pipeline that
# tries to join now gets a clear rejection instead of a confusing Mongo error.
_FORBIDDEN_STAGES = {
    "$out", "$merge", "$function", "$accumulator", "$where",
    "$currentOp", "$collStats", "$indexStats", "$planCacheStats",
    "$listSessions", "$listLocalSessions", "$lookup", "$graphLookup",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2}(\.\d+)?Z?)?$")


def _build_system_prompt() -> str:
    current_year = datetime.now().year
    return f"""\
Tu es un assistant financier pour BIAT IT (filiale informatique de la banque BIAT, Tunisie).
Tu as accès à une base de données MongoDB avec les collections suivantes:

COLLECTION: invoices  (factures fournisseurs reçues)
  issuer_name, invoice_number, invoice_date, due_date,
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

COLLECTION: journal_entries  (écritures comptables — double partie)
  reference, date_ecriture, description,
  source_invoice_id, source_asset_id,
  lines: [ {{ compte, libelle, debit, credit }}, ... ]   ← tableau EMBARQUÉ
  Comptes importants: 401 (fournisseurs), 4366 (TVA déductible),
    6xxx (charges OPEX), 2xxx (immobilisations CAPEX),
    6811 (dotations amortissements), 28xx (amortissements cumulés)
  IMPORTANT : il n'existe PAS de collection "journal_lines" séparée. Les
  lignes d'écriture sont dans le champ "lines" du document journal_entries.
  Pour filtrer/sommer par compte, utilise $unwind sur "lines" d'abord.

COLLECTION: assets  (immobilisations CAPEX)
  designation, compte_immobilisation, compte_amortissement,
  acquisition_date, acquisition_cost_ht,
  useful_life_years, depreciation_method, fully_depreciated

COLLECTION: client_invoices  (factures émises à BIAT groupe)
  invoice_number, invoice_date, due_date,
  client_name, amount_ht, tva_amount, amount_ttc,
  status, paid_at
  Valeurs status: draft, sent, paid, cancelled

COLLECTION: chartes_projet  (contrats projets)
  project_id, project_name, budget_jh, taux_jh, valid_from

COLLECTION: phases  (phases de chaque projet)
  project_id, name, planned_jh, consumed_jh, status, closed_date

Réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans explication en dehors du JSON:
{{
  "collection": "invoices",
  "pipeline": [ {{"$match": {{...}}}}, {{"$group": {{...}}}}, ... ],
  "explanation": "courte explication en français de ce qui est calculé"
}}

Règles de pipeline importantes:
- Une seule collection par requête — PAS de $lookup, PAS de jointure entre collections.
- N'utilise JAMAIS $out, $merge, $function, $accumulator, $where (exécution de code).
- "Combien de..." / "Nombre de..." = TOUJOURS terminer le pipeline par une étape
  {{"$count": "nb"}} — ne retourne JAMAIS les documents bruts pour une question de
  comptage. Exemple correct (combien de factures FLAGGED) : collection "invoices",
  pipeline: [{{"$match": {{"status": "FLAGGED"}}}}, {{"$count": "nb"}}]
- Pour les dates : écris-les comme des chaînes ISO "AAAA-MM-JJ" (ex: "2026-06-01") —
  jamais new Date(...) ou ISODate(...), ce ne serait pas du JSON valide.
  Elles seront converties automatiquement en date avant exécution.
- Année courante : {current_year}. Pour filtrer par année, utilise
  {{"$expr": {{"$eq": [{{"$year": "$invoice_date"}}, {current_year}]}}}}
  ou une plage $gte/$lt sur le mois si plus précis.
- Factures traitées (dépense réelle): status in ["VALIDATED","EXPORTED","JOURNALED","PAID"]
- Factures fournisseurs: direction = "SUPPLIER"
- Toujours terminer un $group par un $project qui renomme "_id" en un nom de
  champ lisible (n'affiche jamais un champ brut nommé "_id"). Exemple:
  {{"$project": {{"_id": 0, "categorie": "$_id", "total": 1}}}}
- Pour une question "liste" / "quelles sont" (pas un agrégat), termine TOUJOURS le
  pipeline par un $project qui ne garde QUE les 3-5 champs utiles à la réponse
  (jamais le document entier — il contient des dizaines de champs internes et des
  tableaux imbriqués illisibles). Exemple (les 5 factures les plus chères) :
  [{{"$match": {{...}}}}, {{"$sort": {{"amount_ttc": -1}}}}, {{"$limit": 5}},
   {{"$project": {{"_id": 0, "issuer_name": 1, "invoice_number": 1, "amount_ttc": 1}}}}]
- Si la question ne peut pas être répondue avec ces collections, retourne:
  {{"collection": null, "pipeline": null, "explanation": "raison pour laquelle la question ne peut pas être répondue"}}

Pièges à éviter:
- cost_catalog_id est un champ texte direct du document invoices (ex: 'telecommunications',
  'formation_personnel'). Il n'existe PAS de collection cost_catalog séparée.
- "En attente de validation" ou "à valider" signifie status = "FLAGGED" (factures bloquées
  pour revue humaine).
- Les lignes d'écriture sont dans invoices... non, dans journal_entries.lines (tableau
  embarqué) — $unwind obligatoire avant de filtrer/sommer par compte. Exemple correct
  (montant total des écritures d'un mois) :
  collection "journal_entries", pipeline:
  [
    {{"$match": {{"$expr": {{"$eq": [{{"$dateToString": {{"format": "%Y-%m", "date": "$date_ecriture"}}}}, "2026-06"]}}}}}},
    {{"$unwind": "$lines"}},
    {{"$group": {{"_id": null, "total": {{"$sum": "$lines.debit"}}}}}},
    {{"$project": {{"_id": 0, "total": 1}}}}
  ]
- TVA déductible (compte 4366) apparaît en "debit" dans lines. TVA collectée (compte 4367)
  apparaît en "credit". Exemple (TVA déductible) : collection "journal_entries",
  [{{"$unwind": "$lines"}}, {{"$match": {{"lines.compte": "4366"}}}},
   {{"$group": {{"_id": null, "total": {{"$sum": "$lines.debit"}}}}}},
   {{"$project": {{"_id": 0, "total": 1}}}}]
- IMPORTANT: Les factures émises aux clients (BIAT groupe, etc.) sont EXCLUSIVEMENT dans la
  collection client_invoices, PAS dans invoices. La collection invoices contient UNIQUEMENT
  les factures reçues de fournisseurs. Pour "ce qu'on a facturé à BIAT / un client", utilise
  TOUJOURS client_invoices.
- "Factures en retard de paiement" = status = "EXPORTED" AND due_date < aujourd'hui
  (expédiées mais pas encore payées). Utilise {{"$expr": {{"$lt": ["$due_date", "$$NOW"]}}}}.
- Pour la VNC (valeur nette comptable), utilise EXACTEMENT ce calcul avec $addFields puis
  $group, collection "assets":
  [
    {{"$addFields": {{"annees_ecoulees": {{"$subtract": [{{"$year": "$$NOW"}}, {{"$year": "$acquisition_date"}}]}}}}}},
    {{"$addFields": {{"vnc": {{"$subtract": [
        "$acquisition_cost_ht",
        {{"$multiply": [{{"$divide": ["$acquisition_cost_ht", "$useful_life_years"]}}, "$annees_ecoulees"]}}
    ]}}}}}},
    {{"$match": {{"fully_depreciated": false}}}},
    {{"$group": {{"_id": null, "vnc": {{"$sum": "$vnc"}}}}}},
    {{"$project": {{"_id": 0, "vnc": 1}}}}
  ]
- Pour filtrer une collection par ANNÉE d'une date (ex: actifs acquis en 2026), utilise
  TOUJOURS une comparaison $gte/$lt en dates ISO string, jamais new Date(...) ni $eq sur
  une année exacte. Exemple (actifs CAPEX acquis en 2026) : collection "assets", pipeline:
  [
    {{"$match": {{"acquisition_date": {{"$gte": "2026-01-01", "$lt": "2027-01-01"}}}}}},
    {{"$count": "nb"}}
  ]
"""


class NLQueryEngine:
    """Converts a French question into a MongoDB aggregation pipeline, runs it,
    returns a French answer.

    Processing chain:
      French question → Ollama (local) → pipeline JSON → MongoDB → French answer
    No data leaves the server.
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        model: str = "qwen2.5:3b",
    ) -> None:
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self._call_count = 0

    # ── Public ────────────────────────────────────────────────────────────────

    def query(self, question: str) -> dict:
        """Run a French natural-language question against the database.

        Returns:
            {
              "question":    str,
              "sql":         str | None,  # display string, "db.<coll>.aggregate([...])"
              "result":      list[dict] | None,
              "answer":      str,        # formatted French answer
              "explanation": str,        # one-line description of the query
            }
        """
        raw = self._ask_llm(question)
        parsed = self._parse_llm_response(raw)

        if parsed is None:
            # One automatic retry — JSON invalide dès le premier essai (souvent
            # un cas non couvert par un exemple du prompt) est tout aussi
            # corrigeable qu'une erreur d'exécution (voir le retry plus bas
            # sur exec_error) ; jusqu'ici ce cas n'avait aucun filet de
            # sécurité et échouait immédiatement.
            retry_question = (
                f"{question}\n\n"
                f"[ERREUR: ta réponse précédente n'était pas un JSON valide]\n"
                f"[Réponse invalide: {raw[:300]}]\n"
                "Génère une nouvelle réponse en JSON STRICT uniquement, sans markdown "
                "ni texte hors JSON. Rappel : les dates sont des chaînes ISO "
                '"AAAA-MM-JJ", jamais new Date(...) ni ISODate(...).'
            )
            raw = self._ask_llm(retry_question)
            parsed = self._parse_llm_response(raw)
            if parsed is None:
                return self._err(question, "Réponse LLM non parsable.", raw[:200])

        collection = parsed.get("collection")
        pipeline = parsed.get("pipeline")
        explanation = parsed.get("explanation", "")

        if not collection or not pipeline:
            return {
                "question": question, "sql": None, "result": None,
                "answer": explanation or "Je ne peux pas répondre à cette question.",
                "explanation": explanation,
            }

        safe, reason = self._is_safe(collection, pipeline)
        if not safe:
            return self._err(question, reason, explanation)

        rows, exec_error = self._run_pipeline(collection, pipeline)
        if exec_error:
            # One automatic retry: feed the error back to the LLM
            retry_question = (
                f"{question}\n\n"
                f"[ERREUR précédente: {exec_error}]\n"
                f"[Pipeline incorrect: collection={collection}, pipeline={json.dumps(pipeline)}]\n"
                "Génère une nouvelle collection + pipeline corrigés qui évitent cette erreur."
            )
            raw2 = self._ask_llm(retry_question)
            parsed2 = self._parse_llm_response(raw2)
            if parsed2 and parsed2.get("collection") and parsed2.get("pipeline"):
                safe2, _ = self._is_safe(parsed2["collection"], parsed2["pipeline"])
                if safe2:
                    collection = parsed2["collection"]
                    pipeline = parsed2["pipeline"]
                    explanation = parsed2.get("explanation", explanation)
                    rows, exec_error = self._run_pipeline(collection, pipeline)
            if exec_error:
                return self._err(question, f"Erreur requête: {exec_error}", explanation)

        answer = self._format_answer(explanation, rows)
        return {
            "question": question,
            "sql": self._display_pipeline(collection, pipeline),
            "result": rows, "answer": answer, "explanation": explanation,
        }

    # ── LLM call ─────────────────────────────────────────────────────────────

    def _ask_llm(self, question: str) -> str:
        import requests
        self._call_count += 1
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": _build_system_prompt()},
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
                "collection": None, "pipeline": None,
                "explanation": "Ollama n'est pas disponible. Démarrez-le avec `ollama serve`.",
            })
        except Exception as e:
            return json.dumps({"collection": None, "pipeline": None, "explanation": f"Erreur LLM: {e}"})

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
    def _is_safe(collection: object, pipeline: object) -> tuple[bool, str]:
        if collection not in _ALLOWED_COLLECTIONS:
            return False, f"Collection non autorisée : {collection!r}."
        if not isinstance(pipeline, list) or not pipeline:
            return False, "Pipeline vide ou invalide."
        for stage in pipeline:
            if not isinstance(stage, dict) or len(stage) != 1:
                return False, "Étape de pipeline invalide."
            key = next(iter(stage))
            if not isinstance(key, str) or not key.startswith("$"):
                return False, f"Étape invalide : {key!r}."
            if key in _FORBIDDEN_STAGES:
                return False, f"Étape non autorisée : {key}."
        return True, ""

    @classmethod
    def _coerce_dates(cls, obj):
        """JSON has no date type — turn ISO date/datetime strings the LLM
        emitted for $match literals into real datetimes so they compare
        correctly against BSON Date fields (plain strings never match)."""
        if isinstance(obj, dict):
            return {k: cls._coerce_dates(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [cls._coerce_dates(v) for v in obj]
        if isinstance(obj, str) and _DATE_RE.match(obj):
            try:
                if "T" in obj:
                    return datetime.fromisoformat(obj.replace("Z", "+00:00")).replace(tzinfo=None)
                return datetime.strptime(obj, "%Y-%m-%d")
            except ValueError:
                return obj
        return obj

    def _run_pipeline(self, collection: str, pipeline: list) -> tuple[list[dict], str | None]:
        from src.storage.sync_mongo_repository import _get_db
        try:
            coerced = self._coerce_dates(pipeline)
            cursor = _get_db()[collection].aggregate(coerced, maxTimeMS=10_000)
            return [self._jsonify(doc) for doc in cursor], None
        except Exception as e:
            return [], str(e)

    @staticmethod
    def _jsonify(doc: dict) -> dict:
        """BSON round-trips datetimes/UUIDs as Python objects — make them
        JSON-serializable before returning to the caller."""
        out = {}
        for k, v in doc.items():
            if isinstance(v, datetime):
                out[k] = v.date().isoformat() if v.time().isoformat() == "00:00:00" else v.isoformat()
            elif isinstance(v, UUID):
                out[k] = str(v)
            else:
                out[k] = v
        return out

    @staticmethod
    def _display_pipeline(collection: str, pipeline: list) -> str:
        return f"db.{collection}.aggregate({json.dumps(pipeline, ensure_ascii=False, default=str, indent=2)})"

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
                # Defensive cap independent of prompt quality: if the pipeline
                # forgot a $project and a row still carries the full raw
                # document (40+ fields, embedded arrays), don't dump it all —
                # skip list/dict values and stop after 8 scalar fields.
                for k, v in row.items():
                    if isinstance(v, (list, dict)):
                        continue
                    if isinstance(v, float):
                        parts.append(f"{k}: {v:,.3f}")
                    elif v is None:
                        parts.append(f"{k}: —")
                    else:
                        parts.append(f"{k}: {v}")
                    if len(parts) >= 8:
                        break
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
