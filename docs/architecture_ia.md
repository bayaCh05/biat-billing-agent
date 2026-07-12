# Architecture IA — BIAT IT Billing Agent

*Rapport d'audit explicatif — lecture seule, aucun fichier modifié*
*Juillet 2026*

---

## Table des matières

1. [Système RAG pour la classification PCE tunisien](#1-système-rag-pour-la-classification-pce-tunisien)
   - [1.1 Pourquoi un RAG ici — justification du choix](#11-pourquoi-un-rag-ici--justification-du-choix)
   - [1.2 Flux bout en bout — de la facture à la classification](#12-flux-bout-en-bout--de-la-facture-à-la-classification)
   - [1.3 Implémentation technique](#13-implémentation-technique)
   - [1.4 Analyse critique — ce choix était-il le bon ?](#14-analyse-critique--ce-choix-était-il-le-bon-)
   - [1.5 Où ailleurs dans le projet un RAG pourrait aider](#15-où-ailleurs-dans-le-projet-un-rag-pourrait-aider)
   - [1.6 Résumé rapport de stage](#16-résumé-rapport-de-stage)
2. [Architecture multi-agents et orchestration](#2-architecture-multi-agents-et-orchestration)
   - [2.1 Pourquoi une architecture multi-agents — justification du choix](#21-pourquoi-une-architecture-multi-agents--justification-du-choix)
   - [2.2 Comment l'orchestrateur fonctionne concrètement](#22-comment-lorchéstrateur-fonctionne-concrètement)
   - [2.3 Implémentation technique](#23-implémentation-technique)
   - [2.4 L'architecture est-elle justifiée — analyse critique tranchée](#24-larchitecture-est-elle-justifiée--analyse-critique-tranchée)
   - [2.5 Recommandation finale](#25-recommandation-finale)
   - [2.6 Résumé rapport de stage](#26-résumé-rapport-de-stage)

---

# 1. Système RAG pour la classification PCE tunisien

## 1.1 Pourquoi un RAG ici — justification du choix

### Le problème métier

La classification comptable consiste à associer une facture reçue à une entrée du Plan Comptable des Entreprises tunisien (PCE, loi 96-112) : compte de charge ou d'immobilisation, taux TVA applicable, nature OPEX/CAPEX. Pour BIAT IT, cela se traduit concrètement : une facture Dell doit atterrir sur `2183 – Matériel informatique` (CAPEX, 19 % TVA), pas sur `6112 – Maintenance informatique` (OPEX).

**Pourquoi un LLM seul ne suffit pas.** Un modèle comme `qwen2.5:3b` a une connaissance générale du droit comptable, mais le PCE tunisien est une norme nationale spécifique (33 entrées définies dans `config/cost_catalog.yaml`) avec des nuances propres au secteur bancaire tunisien : les primes d'assurance sont exonérées de TVA, les SaaS sont en OPEX (6133) tandis que les licences perpétuelles sont en CAPEX (2284), etc. Sans ancrage dans le catalogue exact de BIAT IT, le LLM inventerait des comptes plausibles mais faux.

**Pourquoi pas une table statique mots-clés → compte.** Cette approche est d'ailleurs implémentée en Pass A (`CostCatalog.match()`, fuzzy keyword). Elle fonctionne pour 80–90 % des cas prévisibles ("maintenance serveur" → `6112`, "facture STEG" → `6241`). Mais elle échoue sur les libellés imprécis, les factures multilingues (arabe/français), les cas ambigus (un "contrat de service Microsoft" peut être SaaS 6133 ou licence perpétuelle 2284 selon le contrat). Ces cas résiduels représentent typiquement les factures à fort enjeu comptable — exactement là où une erreur est la plus coûteuse.

**Pourquoi pas un prompt statique contenant tout le PCE.** Le catalogue `config/cost_catalog.yaml` contient **33 entrées** avec leurs libellés, mots-clés et notes. Un prompt statique incluant toutes les entrées tiendrait dans une fenêtre de contexte de 4K tokens — `qwen2.5:3b` supporte 8K. Il serait *techniquement* possible de tout injecter à chaque appel. Cependant :

1. **Performance** : chaque appel OCR → classification transmettrait ~2K tokens de contexte fixe, pour un modèle 3B qui tourne en local sur du matériel potentiellement limité. Sur un pic de traitement (20 factures), cela représente 40K tokens de contexte PCE inutilement répété.
2. **Précision** : avec 33 entrées listées, le LLM tend à "lire" toutes les options et hésite davantage. Le RAG réduit le choix à 3 candidats pertinents — le problème devient trivial pour le modèle.
3. **Extensibilité** : si le PCE était étendu à 200 entrées (PCE complet tunisien), le prompt dépasserait la fenêtre. Le RAG passe sans modification.

**Pourquoi pas un fine-tuning.** Fine-tuner `qwen2.5:3b` sur des exemples de factures → compte PCE nécessite un dataset étiqueté de plusieurs milliers d'exemples, une infrastructure GPU, et doit être refait à chaque modification du catalogue. Pour 33 catégories stables, c'est un effort disproportionné. Le RAG met à jour le vectorstore en appelant `store.reindex_pce()` — aucun réentraînement.

**Ce choix est-il documenté dans le code ?** Partiellement. Le fichier `src/ai_agents/rag/rag_classifier.py` a un docstring d'une ligne (`"""Pass C: embed query → ChromaDB → Ollama picks from candidates."""`) et `classification_agent.py` documente les 3 passes dans sa docstring de module. Il n'existe pas de document d'architecture expliquant le *pourquoi* du choix RAG vs alternatives. C'est un choix d'architecture non justifié par écrit dans le projet.

---

## 1.2 Flux bout en bout — de la facture à la classification

### Schéma de flux

```
Facture PDF reçue
       │
       ▼
ExtractionAgent (Agent 1)
  ↳ HybridExtractor → texte brut + line_items extraits
  ↳ payment_term_days calculé
       │
       ▼
ClassificationAgent (Agent 2)
  ├── Pass A : CostCatalog.match() — fuzzy keyword TF-IDF interne
  │            (ex: "maintenance serveur" → score 92 → 6112) → STOP si match
  ├── Pass B : TF-IDF + LogisticRegression ML
  │            (modèle entraîné sur historique VALIDATED/EXPORTED) → STOP si classé
  └── Pass C : RAGClassifier — seulement si A+B échouent
               ├── 1. Construire la requête
               ├── 2. PCEEmbedder.embed() → vecteur 384 dims
               ├── 3. ChromaDB.search_pce() → top-3 + scores
               ├── 4. Filtrer par MIN_SIMILARITY ≥ 0.45
               └── 5. Prompt Ollama : "choisis parmi ces 3 candidats"
```

### Données exactes envoyées en requête de similarité

Dans `rag_classifier.py`, la requête construite est :

```python
query = invoice_text[:300]          # 300 premiers chars du texte brut OCR/PDF
if line_items:
    descs = " ".join(item.description for item in line_items if item.description)
    query = f"{query} {descs}"      # + descriptions des lignes de facture
```

**Ce qui est indexé dans ChromaDB** pour chaque entrée PCE (`_index_pce` dans `pce_vectorstore.py`) :

```python
text = f"{e.label} {' '.join(e.keywords)}"
# Exemple : "Matériel informatique (serveurs, PC, écrans, équipements réseau)
#            serveur ordinateur PC laptop écran switch routeur firewall ..."
```

Les métadonnées stockées par entrée : `id`, `label`, `compte`, `charge_type`, `tva_rate`.

### Exemple concret — Facture Dell serveurs

**Entrée** : une facture PDF de Dell Technologies Tunisia, `"PowerEdge R750 Servers x2 — 85 000 TND HT"`.

Supposons que Passes A et B échouent (libellé trop technique, pas dans l'historique).

**Pass C :**

1. **Requête** : `"Dell Technologies PowerEdge R750 Servers rack infrastructure"` (texte OCR tronqué à 300 chars)

2. **Embeddings + ChromaDB search** → top-3 avec scores (cosinus) :

```
1. materiel_informatique — "Matériel informatique (serveurs, PC, écrans...)
                            serveur ordinateur PC laptop écran switch..."
   similarity: 0.87

2. maintenance_informatique — "Maintenance et support informatique
                               maintenance serveur contrat de maintenance..."
   similarity: 0.61

3. logiciels_acquis — "Logiciels acquis (licences perpétuelles)
                       ERP progiciel licence définitive..."
   similarity: 0.38  ← filtré (< 0.45)
```

3. **Prompt envoyé à Ollama** :

```
Tu es un expert-comptable tunisien.
Une facture contient: "Dell Technologies PowerEdge R750 Servers rack..."

Voici 2 catégories comptables PCE possibles:
1. Matériel informatique (serveurs, PC, écrans...) (compte 2183)
2. Maintenance et support informatique (compte 6112)

Réponds UNIQUEMENT en JSON sans markdown:
{"choice": 1, "reason": "une phrase en français"}
```

4. **Réponse Ollama** : `{"choice": 1, "reason": "Achat de serveurs physiques = immobilisation CAPEX 2183"}` → `materiel_informatique` retenu, confiance = 0.5

5. Comme 0.5 < `_CONF_THRESHOLD = 0.80` → `invoice.human_review_required = True` automatiquement.

### Fallback si aucun candidat pertinent

Si `search_pce()` retourne 0 candidats au-dessus de `MIN_SIMILARITY=0.45` :
- `RAGClassifier.classify()` retourne `None`
- `ClassificationAgent._try_rag_pass()` retourne `"NONE"` sans modifier la facture
- La facture est signalée `FlagType.CATALOG_NO_MATCH` et mise en file de révision humaine

---

## 1.3 Implémentation technique

### Architecture des collections ChromaDB

```
data/chromadb/              ← CHROMADB_PATH (configurable via env)
├── pce_catalog/            ← PCE entries (33 entrées)
└── invoice_embeddings/     ← factures indexées post-JOURNALED
```

**Collection `pce_catalog`** (espace cosinus `hnsw:space: cosine`) :
- **Vecteurs** : embeddings 384 dims de `f"{label} {keywords}"` pour chaque entrée
- **Métadonnées** : `{id, label, compte, charge_type, tva_rate}`
- **Taille** : 33 vecteurs — taille négligeable (~0.1 Mo)
- **Initialisation** : `api/main.py` lignes 122–134, au démarrage de FastAPI via `startup` event
- **Idempotence** : `initialize_pce()` vérifie `self._pce_col.count() == len(entries)` avant d'indexer

**Collection `invoice_embeddings`** :
- **Usage** : détection de doublons sémantiques dans `AnomalyAgent._check_semantic_duplicate()`
- **Format** : `{issuer_name} {invoice_number} {amount_ttc} {invoice_date}`
- **Indexation** : après `InvoiceStatus.JOURNALED` dans `AIOrchestrator._embed_invoice()`
- **Seuil** : similarité > 0.92 → flag `NEAR_DUPLICATE`

### Modèle d'embedding

**Actuel** : `paraphrase-multilingual-MiniLM-L12-v2`
- 12 couches transformer, 384 dimensions de sortie
- Supporté nativement par `sentence-transformers` (pip install)
- Couverture : français, arabe, anglais, 50+ langues
- Performance comparable à `all-MiniLM-L6-v2` sur l'anglais, meilleure sur le français et l'arabe

### Fichiers clés

| Fichier | Rôle |
|---------|------|
| `src/ai_agents/rag/embedder.py` | `PCEEmbedder` — singleton, charge le modèle, cache LRU 1000 entrées |
| `src/ai_agents/rag/pce_vectorstore.py` | `PCEVectorStore` — singleton ChromaDB, gère les 2 collections |
| `src/ai_agents/rag/rag_classifier.py` | `RAGClassifier.classify()` — construit la requête, filtre, prompt Ollama |
| `src/ai_agents/classification_agent.py` | `ClassificationAgent._try_rag_pass()` — invoque RAGClassifier en Pass C |
| `api/main.py` lignes 122–134 | Appel `initialize_pce()` au démarrage |
| `config/cost_catalog.yaml` | Source de vérité des 33 entrées PCE |

### Cache d'embeddings (PCEEmbedder)

`PCEEmbedder` utilise un `OrderedDict` comme cache LRU borné à 1000 entrées (`EMBEDDER_CACHE_SIZE`) :
- **Lecture** : `move_to_end()` pour marquer l'entrée comme récente
- **Écriture** : si `len(cache) > CACHE_MAX` → `popitem(last=False)` pour évincer la plus ancienne
- **Pertinence** : les 33 textes PCE sont embedés une fois à l'initialisation et restent toujours en cache. Le LRU est surtout utile pour les embeddings de requêtes de factures répétées.

---

## 1.4 Analyse critique — ce choix était-il le bon ?

### Comparaison des alternatives

| Approche | Coût de mise en place | Précision estimée | Maintenabilité |
|----------|-----------------------|-------------------|----------------|
| **Table statique mots-clés** (Pass A actuelle) | Quasi-nul | 80–90 % | Excellente |
| **ML supervisé TF-IDF/LR** (Pass B actuelle) | Faible (CSV d'exemples) | 85–92 % | Bonne |
| **Prompt statique PCE complet** | Nul | 88–93 % (limitée par taille du modèle) | Excellente |
| **RAG ChromaDB + Ollama** (Pass C) | Moyen (ChromaDB, embeddings) | 90–95 % | Bonne |
| **Fine-tuning qwen2.5 sur PCE** | Élevé (dataset, GPU, cycle) | 95–98 % | Faible |

### Honnêteté sur les limites spécifiques à CE projet

**La vraie question : 33 entrées justifient-elles un RAG ?**

Non — pas seul. Un prompt statique contenant les 33 entrées PCE tiendrait dans ~800 tokens, bien en dessous de la fenêtre de `qwen2.5:3b`. Pour 33 catégories, un prompt bien structuré avec toutes les options serait probablement *plus* précis qu'un RAG, car le LLM verrait toutes les options sans dépendre de la qualité des embeddings.

**Pourquoi le RAG reste justifié ici malgré tout :**

1. **Architecture à trois passes** : le RAG n'est que le Pass C, appelé seulement quand les passes A et B échouent. En pratique, sur un historique d'entreprise rodé, ≤10 % des factures atteignent le Pass C. Il n'est pas le système principal, il est le filet de sécurité de dernier recours.

2. **Réutilisation de l'infrastructure** : la collection `invoice_embeddings` sert aussi à la détection de doublons sémantiques (`AnomalyAgent._check_semantic_duplicate()`). ChromaDB n'est donc pas installé uniquement pour la classification — la complexité est amortie sur deux usages.

3. **Extensibilité vers un PCE étendu** : si le projet est déployé à d'autres filiales du groupe BIAT avec un catalogue plus large, le RAG passe sans refactoring.

**Limite réelle la plus importante (au-delà du bug initialize_pce désormais corrigé) :** La confiance retournée par le Pass C est fixée à `0.5` dans `ClassificationAgent._try_rag_pass()` :

```python
conf = 0.5  # RAG result is lower confidence
```

Cela force systématiquement une revue humaine (seuil à 0.80) pour toute classification RAG, quelle que soit la qualité du résultat Ollama. C'est conservateur mais correct pour un projet bancaire.

---

## 1.5 Où ailleurs dans le projet un RAG pourrait aider

### NLQueryEngine / page Requêtes IA (texte → pipeline MongoDB)

**Avis : NON — le prompt statique suffit et est supérieur.**

Depuis la migration Mongo (2026-07), l'approche actuelle (`src/query/nl_query_engine.py`) fait générer par le LLM un pipeline d'agrégation MongoDB (`{"collection": ..., "pipeline": [...]}`), plus une requête SQL brute. Le `_SYSTEM_PROMPT` (~80 lignes) décrit les collections autorisées, leurs champs exacts, et les stages interdits (`$out`, `$merge`, `$lookup`, `$where`, ...) — voir `NLQueryEngine._is_safe()`. Ce prompt fait ~1 200 tokens — bien dans la fenêtre. Un RAG sur des "exemples de requêtes passées" serait contre-productif ici : les questions NL sont trop variées (agrégats, conditions temporelles) pour qu'un "exemple similaire" soit réutilisable — d'autant que les jointures inter-collections (`$lookup`) sont interdites, donc peu de requêtes "types" à indexer.

**Pertinence : Basse | Effort : Moyen | Verdict : À ne pas implémenter.**

### AnomalyAgent — RAG sur l'historique des anomalies résolues

**Avis : PEUT-ÊTRE — pertinent mais à faible retour sur investissement à ce stade.**

L'`AnomalyAgent` utilise déjà des requêtes sur l'historique (`_check_category_price`, `_check_payment_term`, désormais `historical_amounts_for_catalog_sync`/`historical_payment_terms_sync` sur MongoDB depuis la migration) qui comparent statistiquement les factures VALIDATED/EXPORTED précédentes. C'est une forme de RAG implicite via requêtes structurées, plus robuste et plus rapide qu'un vectorstore pour des données structurées.

**Pertinence : Basse | Effort : Élevé | Verdict : requêtes statistiques déjà présentes, ne pas dupliquer.**

### RiskAgent — RAG sur les mitigations passées

**Avis : OUI — valeur réelle, implémentation légère.**

Le `RiskAgent._draft_mitigation()` génère 3 actions de mitigation à partir du titre du risque. Si l'application accumule des données sur 1–2 ans, une collection ChromaDB des mitigations *effectivement appliquées* (statut `MAITRISE`) permettrait au RAG de proposer des actions qui ont déjà fonctionné pour des risques similaires.

**Implémentation** : ajouter une collection `risk_mitigations` dans `PCEVectorStore` ; indexer les `RisqueDocument` (collection Mongo `risques`) dont `statut IN ('MAITRISE', 'CLOTURE')` avec leur `plan_mitigation` ; modifier `_draft_mitigation()` pour injecter les 2–3 mitigations similaires dans le prompt Ollama.

**Pertinence : Haute | Effort : Faible (3–4h) | Verdict : À implémenter dans une V2.**

### InsightAgent — RAG sur les résumés exécutifs précédents

**Avis : NON — complexité non justifiée.**

L'`InsightAgent._health_summary()` génère un résumé sur des KPIs chiffrés. La cohérence de ton est pilotée par des instructions explicites dans le prompt — c'est suffisant. Indexer les résumés précédents dans un vectorstore pour maintenir la cohérence stylistique serait une sur-ingénierie.

**Pertinence : Basse | Effort : Moyen | Verdict : À ne pas implémenter.**

### Synthèse — tableau de priorisation

| Cas d'usage RAG | Pertinence | Effort | Verdict |
|-----------------|-----------|--------|---------|
| Classification PCE (actuel) | **Haute** | Moyen | ✅ Implémenté (Pass C) |
| Détection doublons sémantiques (actuel) | **Haute** | Faible | ✅ Implémenté |
| Mitigations risques historiques (V2) | **Haute** | Faible | ✅ À implémenter |
| NLQuery (exemples de requêtes passées) | Basse | Moyen | ❌ Prompt statique meilleur |
| AnomalyAgent (anomalies résolues) | Basse | Élevé | ❌ SQL statistique déjà présent |
| InsightAgent (résumés précédents) | Basse | Moyen | ❌ Sur-ingénierie |

---

## 1.6 Résumé rapport de stage

> Le projet intègre un système RAG (Retrieval-Augmented Generation) pour la classification comptable automatique des factures selon le Plan Comptable des Entreprises tunisien (PCE). Le choix s'est porté sur cette architecture en trois passes — règles, machine learning, puis RAG — car ni un LLM seul ni une table de correspondance statique ne sont suffisants : le PCE tunisien contient des nuances métier spécifiques au secteur bancaire (distinction OPEX/CAPEX sur les licences, exonérations TVA sur les assurances) que seul un catalogue structuré peut garantir. L'approche RAG consiste à encoder les 33 catégories comptables en vecteurs sémantiques via `sentence-transformers` (modèle multilingue), à stocker ces vecteurs dans ChromaDB, puis à présenter uniquement les 3 candidats les plus proches au LLM local Ollama plutôt que l'intégralité du plan comptable, améliorant ainsi la précision du choix final. La même infrastructure ChromaDB est réutilisée pour la détection de doublons sémantiques entre factures, amortissant la complexité opérationnelle sur deux usages distincts. Cette architecture, entièrement locale conformément aux contraintes de résidence des données bancaires, pourrait être étendue à une troisième application : la suggestion de plans de mitigation pour les risques projet, en indexant les mitigations ayant réellement abouti dans l'historique de l'outil.

---

---

# 2. Architecture multi-agents et orchestration

## 2.1 Pourquoi une architecture multi-agents — justification du choix

### Le problème : pourquoi pas un seul agent "tout en un" ?

La question est légitime. Un seul prompt structuré pourrait théoriquement faire : *"Voici le texte OCR d'une facture. Retourne en JSON : compte PCE, montant HT/TVA, écriture comptable, anomalies."* Ça fonctionnerait pour les cas simples. Ça échouerait structurellement pour plusieurs raisons liées à ce projet précis.

**La raison principale est que les 4 étapes n'utilisent pas les mêmes outils.** Ce n'est pas 4 étapes LLM — c'est 4 étapes dont certaines sont déterministes, d'autres statistiques, d'autres LLM :

| Agent | Outil principal | LLM Ollama impliqué ? |
|-------|-----------------|----------------------|
| ExtractionAgent | HybridExtractor (OCR/PDF → Tesseract/PyMuPDF) | Non — délègue à l'extracteur existant |
| ClassificationAgent | AccountingCoder (fuzzy + ML TF-IDF), puis RAG | Oui — 1 appel pour l'explication en texte |
| AnomalyAgent | 4 validateurs déterministes (field, coherence, duplicate, anomaly) | Non |
| AccountingAgent | EntryGenerator (arithmétique pure), AssetRepository | Oui — 1-2 appels pour explication + durée amortissement |

Fusionner ExtractionAgent et ClassificationAgent dans un "super-prompt LLM" n'est pas possible parce qu'ExtractionAgent n'appelle pas Ollama — il appelle Tesseract, PyMuPDF, et le `HybridExtractor`. Il y a une incompatibilité d'outils, pas seulement de responsabilités.

### Agent par agent : la fusion est-elle possible sans perte ?

**ExtractionAgent + ClassificationAgent → fusionnables techniquement, pas conceptuellement.**

Le texte brut OCR est l'entrée de la classification. Techniquement, on pourrait appeler les deux dans une fonction. Mais l'ExtractionAgent peut échouer (fichier corrompu, OCR illisible), et cet échec doit arrêter le pipeline immédiatement — ce qui est d'ailleurs ce qu'il fait (`EXTRACTION_FAILED`). Séparer les deux permet d'identifier précisément quelle étape a échoué en production, ce qui est utile pour le débogage opérationnel.

**AnomalyAgent + AccountingAgent → la fusion serait une erreur.**

L'AnomalyAgent peut décider que la facture doit aller en révision humaine (`FLAGGED`), ce qui *annule* AccountingAgent. C'est le seul vrai branchement conditionnel du pipeline. Si les deux étaient fusionnés, il faudrait du code conditionnel interne pour décider de ne pas générer l'écriture comptable — ce que l'orchestrateur fait aujourd'hui de façon plus lisible.

**RiskAgent et InsightAgent → leur présence dans la même hiérarchie de classes est discutable.**

Ces deux agents ne font pas partie du pipeline de traitement des factures. Ils sont appelés dans des flux *secondaires indépendants* (scan nightly de la roadmap, résumé exécutif Direction). Les regrouper dans la même classe de base `BaseAgent` que les 4 agents du pipeline facture est une décision de cohérence de code — pas d'architecture opérationnelle.

### Ce choix est-il documenté ?

Non, formellement. La docstring de `orchestrator.py` dit : *"Coordinates AI agents for the complete invoice processing pipeline."* Celle de chaque agent décrit ce que l'agent fait, pas *pourquoi* il est séparé. Il n'existe aucun document d'architecture, aucun README AI, aucun commentaire expliquant le raisonnement derrière le découpage en 6.

---

## 2.2 Comment l'orchestrateur fonctionne concrètement

### Ce que fait l'AIOrchestrator

Lire `orchestrator.py` honnêtement : l'orchestrateur fait principalement **trois choses** :

1. **Séquencement et gestion de l'état** : instantiation des agents, passage de l'`InvoiceRecord` muté, mise à jour du statut de la facture entre chaque étape via `repository.save()`.
2. **Un seul vrai branchement conditionnel** : si `AnomalyAgent` retourne `requires_human_review = True`, le pipeline s'arrête et AccountingAgent est sauté (status `FLAGGED`).
3. **Observabilité structurée** : chaque étape génère un `PipelineStep` avec `status`, `duration_ms`, `summary` — utile pour le debugging et l'UI `AIActivityPage`.

**Ce qu'il ne fait pas :** retry au niveau global, parallélisme, routing dynamique, sélection conditionnelle d'agents alternatifs, gestion de priorité. Il n'y a pas d'algorithme d'ordonnancement — l'ordre est toujours 1→2→3→4.

### Flux concret pour une facture — tous les appels dans l'ordre

Exemple : facture Dell PowerEdge 85 000 TND TTC.

```
AIOrchestrator.process_invoice(invoice)
│
├── [1] ExtractionAgent.run({"invoice": invoice})
│       → self._extractor.extract(invoice)         # HybridExtractor (OCR/PyMuPDF)
│       → invoice.issuer_name.value = "Dell Technologies"
│       → invoice.amount_ttc.value = 85000.0
│       → invoice.payment_term_days = 30           # calculé depuis due_date - invoice_date
│       → AgentResult(success=True, confidence=0.91)
│   Orchestrateur : _audit_ai("AI_EXTRACT", ...) + invoice.status = EXTRACTED + save()
│
├── [2] ClassificationAgent.run({"invoice": invoice, "degraded_mode": False})
│       → self._classifier.classify(invoice)       # règles direction : SUPPLIER
│       → self._coder.assign(invoice)              # Pass A fuzzy : "serveur" → materiel_informatique
│       → invoice.cost_catalog_id = "materiel_informatique"
│       → invoice.accounting_compte = "2183"
│       → charge_type = CAPEX
│       → [Ollama call 1] _generate_explanation()  # "Achat de matériel..."
│       → AgentResult(success=True, confidence=1.0, pass_used="CATALOG_FUZZY")
│   Orchestrateur : _audit_ai("AI_CLASSIFY", ...) + invoice.status = CLASSIFIED + save()
│
├── [3] AnomalyAgent.run({"invoice": invoice, "db": db})
│       → self._fv.validate(invoice)               # champs manquants ?
│       → self._cc.check(invoice)                  # TVA cohérente ?
│       → self._dd.detect(invoice)                 # doublon ?
│       → self._ad.detect(invoice)                 # montant plausible ?
│       → _check_category_price(invoice, db)       # p90 historique ?
│       → _check_payment_term(invoice, db)         # délai habituel ?
│       → _check_semantic_duplicate(invoice)       # ChromaDB ?
│       → AgentResult(success=True, anomaly_count=0, requires_human_review=False)
│   Orchestrateur : _audit_ai("AI_ANOMALY", ...) + invoice.status = VALIDATED + save()
│           ← NOTE : si requires_human_review=True ici → STOP, AccountingAgent sauté
│
└── [4] AccountingAgent.run({"invoice": invoice, "db": db})
        → _post_journal(invoice, catalog_entry, db)
              → self._entry_gen.generate(invoice, catalog_entry)  # 2183 / 4366 / 401
              → [Ollama call 2] _generate_accounting_explanation()
              → self._journal_repo.save(entry)
        → _create_capex_asset(invoice, catalog_entry, db)         # charge_type = CAPEX
              → [Ollama call 3] _get_amortization_duration()      # "5 ans" pour matériel
              → AssetRepository.save(asset)
        → _create_payment_schedule(invoice, db)                   # payment_term_days = 30
              → 1 PaymentInstallmentORM créé
        → AgentResult(success=True, is_balanced=True)
    Orchestrateur : _audit_ai("AI_JOURNAL", ...) + invoice.status = JOURNALED + save()
```

**Total pour cette facture : 3 appels Ollama** (explication classification + explication comptable + durée amortissement), ou 4 si la classification avait échoué et utilisé le RAG.

### Y a-t-il du branchement conditionnel réel ?

**Un seul.** La condition à la fin de l'étape 3 :

```python
if result3.output.get("requires_human_review"):
    invoice.status = InvoiceStatus.FLAGGED
    ...
    return OrchestratorResult(final_status="FLAGGED", ...)
    # AccountingAgent ne s'exécute pas
```

C'est le seul endroit où le pipeline bifurque. Pour le reste, le flux est strictement linéaire et identique quelle que soit la facture : Extraction → Classification → Anomalie → Comptabilité, dans cet ordre, toujours.

---

## 2.3 Implémentation technique

### Ce que BaseAgent mutualise réellement

```python
class BaseAgent(ABC):
    def __init__(self): self._ollama = ...; self._call_count = 0
    @abstractmethod
    def run(self, context: dict) -> AgentResult: ...
    def _call_ollama(self, ...): ...          # JAMAIS appelé par aucun agent
    def _parse_json_response(self, ...): ...  # JAMAIS appelé par aucun agent
    def _safe_float(self, ...): ...           # JAMAIS appelé par aucun agent
    def _timed_run(self, fn): ...             # JAMAIS appelé par aucun agent
```

**Fait notable** : `_call_ollama()`, `_parse_json_response()`, `_safe_float()` et `_timed_run()` sont définis dans `BaseAgent` mais **aucun des 6 agents ne les appelle jamais**. Chaque agent appelle `OllamaClient.get().complete()` directement, fait son propre parsing JSON avec `re.search()` ou `json.loads()`, et chronomètre lui-même avec `time.monotonic()`.

**Ce que BaseAgent apporte réellement :**
1. `self._call_count` : compteur d'appels Ollama, incrémenté manuellement par chaque agent
2. L'interface abstraite `run(context: dict) -> AgentResult` : contrat uniforme qui rend les agents interchangeables dans l'orchestrateur

### Le couplage réel via InvoiceRecord muté en place

L'`InvoiceRecord` est un dataclass Python classique (pas Pydantic) passé par référence dans toute la chaîne. Chaque agent le lit et le modifie directement :

```python
# ExtractionAgent ajoute :
invoice.payment_term_days = delta          # attribut dynamique, pas déclaré dans __init__

# ClassificationAgent lit et écrit :
invoice.cost_catalog_id = entry.id         # lu par AccountingAgent
invoice.accounting_compte = entry.compte
invoice.charge_type = entry.type_charge    # conditionne _create_capex_asset()

# AnomalyAgent écrit :
invoice.human_review_required = True       # lu par l'orchestrateur pour le branchement
invoice.add_flag(ValidationFlag(...))

# AccountingAgent lit :
invoice.cost_catalog_id  # issu de ClassificationAgent
invoice.charge_type      # issu de ClassificationAgent
invoice.payment_term_days  # issu de ExtractionAgent
```

**Ce couplage contredit l'idée d'agents "indépendants".** Un agent qui recevrait un `InvoiceRecord` vide produirait des résultats incorrects ou planterait silencieusement. AccountingAgent dépend implicitement du fait que ClassificationAgent a déjà renseigné `cost_catalog_id`. ExtractionAgent crée `payment_term_days` avec `setattr` — c'est un attribut dynamique invisible au lecteur qui regarde seulement `invoice.py`.

Ce n'est pas un problème d'architecture multi-agents en général — c'est une implémentation spécifique où le "contrat" entre agents est implicite plutôt qu'explicite (un schéma Pydantic par transition aurait formalisé ça).

### Fichiers clés

| Fichier | Rôle | LOC environ |
|---------|------|-------------|
| `src/ai_agents/base_agent.py` | Classe de base abstraite | 73 |
| `src/ai_agents/models.py` | AgentResult, PipelineStep, OrchestratorResult | 38 |
| `src/ai_agents/orchestrator.py` | AIOrchestrator — séquencement + 1 branchement | 263 |
| `src/ai_agents/extraction_agent.py` | Wrapper HybridExtractor | 79 |
| `src/ai_agents/classification_agent.py` | 3 passes + explication | 156 |
| `src/ai_agents/anomaly_agent.py` | 7 checks + sémantique | 204 |
| `src/ai_agents/accounting_agent.py` | Journal + CAPEX + échéancier | 290 |
| `src/ai_agents/risk_agent.py` | Scan roadmap + mitigation | 203 |
| `src/ai_agents/insight_agent.py` | NL query + résumé exécutif | 226 |

---

## 2.4 L'architecture est-elle justifiée — analyse critique tranchée

### Comparaison des trois alternatives

**Option A — Un seul agent monolithique**

```
InvoiceRecord + PDF → [MEGA PROMPT Ollama] → EcritureComptable + Flags
```

*Fiabilité :* catastrophique. Un seul point de défaillance LLM pour toutes les étapes. Si Ollama retourne un JSON mal formé pour le compte PCE, on perd aussi l'explication comptable et la durée d'amortissement. Le debug est impossible ("l'agent a planté" — mais sur quelle étape ?). Sans compter que l'extraction OCR est *physiquement incompatible* avec une approche tout-LLM : Tesseract ne s'intègre pas dans un prompt.

*Coût :* 1 appel Ollama par facture.

*Maintenabilité :* nulle. Le prompt monolithique mélange des domaines complètement distincts (OCR, PCE tunisien, comptabilité à partie double). Ajouter la détection de doublons sémantiques ou les pénalités de retard est impossible sans tout réécrire.

*Verdict :* irréaliste pour ce projet. L'OCR seul interdit cette approche.

---

**Option B — Deux agents (analyse + décision) sans orchestrateur dédié**

```python
def process_invoice_with_ai(invoice, components, db):
    # Agent "analyse" : Extraction + Classification
    invoice = components.extractor.extract(invoice)
    invoice = components.coder.assign(invoice)
    if low_confidence: invoice.human_review_required = True

    # Branchement unique
    flags = run_all_validators(invoice, db)
    if requires_review(flags): return "FLAGGED"

    # Agent "décision" : Journal + CAPEX + Schedule
    journal = components.entry_gen.generate(invoice, catalog_entry)
    if invoice.charge_type == CAPEX: create_asset(invoice, db)
    ...
```

*Fiabilité :* bonne. Les erreurs de l'étape extraction sont séparées des erreurs comptables. On peut ajouter des logs précis par bloc.

*Coût :* identique à l'architecture actuelle (même nombre d'appels Ollama).

*Maintenabilité :* meilleure que l'architecture actuelle, paradoxalement — moins de classes, moins d'indirections.

*Pertinence académique :* faible. "J'ai écrit une fonction pipeline avec deux blocs" n'est pas une architecture.

*Verdict :* fonctionnellement équivalent à l'architecture actuelle, avec moins de code. La seule perte est l'observabilité structurée (`PipelineStep` + `AgentResult`) et l'extensibilité formelle.

---

**Option C — Architecture actuelle (6 agents + orchestrateur)**

*Fiabilité :* bonne, avec une limite importante : le couplage implicite via `InvoiceRecord` crée des dépendances invisibles.

*Coût :* 2–4 appels Ollama par facture.

*Maintenabilité :* bonne pour l'extension (ajouter un 7e agent est simple), variable pour la modification.

*Pertinence académique :* élevée — c'est une architecture reconnaissable, documentable, qui justifie son niveau de complexité dans un rapport.

---

### Verdict honnête : surdimensionné ? Partiellement, oui.

**La séparation en 4 étapes du pipeline facture est pleinement justifiée.** Les 4 opérations sont fondamentalement hétérogènes (OCR, ML, règles déterministes, arithmétique comptable), et le branchement FLAGGED est un vrai point de contrôle métier.

**Ce qui est surdimensionné :**

1. **`BaseAgent` en tant que classe abstraite** avec 4 méthodes utilitaires dont 0 sont utilisées. La valeur réelle de `BaseAgent` est l'interface `run(context) → AgentResult` — ça pourrait être un simple Protocol Python en 3 lignes.

2. **RiskAgent et InsightAgent dans la même hiérarchie** que les agents du pipeline facture. Ces deux agents ne traitent pas de factures — les appeler "agents" dans le même sens qu'ExtractionAgent est un abus de vocabulaire.

3. **Le terme "orchestrateur"** suggère une coordination dynamique (routing, retry, parallélisme) qui n'existe pas. Ce que `AIOrchestrator.process_invoice()` fait réellement : appeler 4 fonctions séquentielles avec une condition d'arrêt. C'est un **pipeline avec un branchement conditionnel**, pas un orchestrateur au sens technique.

**Ce qui est justifié et utile même si "suringénié" :**

- `AgentResult` avec `duration_ms` et `ollama_calls_made` : observable, debuggable, affiché dans `AIActivityPage`
- `PipelineStep` : permet à l'UI de montrer l'avancement étape par étape en temps réel
- La séparation des classes facilite les tests unitaires (chaque agent est mockable isolément)
- Le mode dégradé (`degraded_mode: bool`) peut être passé sélectivement aux agents qui ont besoin d'Ollama

---

## 2.5 Recommandation finale

### Verdict : Garder tel quel pour la soutenance, en nuançant dans le rapport

**Ne pas refactoriser maintenant.** La refonte de l'architecture représente un effort moyen (3–5 jours), avec un risque de régression élevé sur les fonctionnalités déjà démontrées. Le gain opérationnel serait marginal.

**Ce qu'il faudrait corriger à terme** (effort faible, sans risque de régression) :
- Supprimer les 4 méthodes mortes dans `BaseAgent` ou commenter pourquoi elles existent
- Renommer `AIOrchestrator` en `InvoicePipeline` pour refléter la réalité
- Déplacer `RiskAgent` et `InsightAgent` dans `src/ai_agents/services/` pour les distinguer des agents du pipeline

### Arguments à préparer pour une soutenance

Si un jury demande *"pourquoi 6 agents plutôt qu'un seul ?"*, les arguments les plus solides sont :

**1. Incompatibilité d'outils, pas seulement de responsabilités.** L'extraction nécessite Tesseract et PyMuPDF. La classification utilise un modèle ML TF-IDF scikit-learn. La validation est 100% déterministe. La comptabilité est de l'arithmétique pure. Ces 4 opérations ne peuvent pas être fusionnées dans un seul appel LLM.

**2. Isolation des pannes et observabilité.** En production, savoir qu'une facture a échoué à l'étape *classification* plutôt qu'à l'étape *validation* est critique pour le diagnostic. L'architecture actuelle produit un `PipelineStep` par étape avec son statut, sa durée et son résumé — visible dans l'interface `AIActivityPage`.

**3. Le branchement conditionnel est une exigence métier.** Une facture détectée comme anomale ne doit jamais générer d'écriture comptable automatique. Ce point d'arrêt (`FLAGGED` → skip AccountingAgent) est un garde-fou délibéré, pas un détail d'implémentation.

**4. Testabilité indépendante.** Chaque agent peut être testé en isolation avec un mock de ses dépendances. Un agent monolithique rendrait impossible de tester la logique de classification sans passer par l'OCR.

### Nuance honnête à mentionner en soutenance

> L'implémentation réelle est plus proche d'un pipeline séquentiel avec un branchement conditionnel que d'un vrai système multi-agents au sens de la littérature LLM (où les agents s'appellent mutuellement de façon dynamique, négocient, ou exécutent des sous-tâches en parallèle). Le terme "agent" est utilisé dans son sens le plus large — une unité de traitement avec une interface standardisée et une responsabilité unique — ce qui est architecturalement valide sans être le sens fort du terme en IA générative.

---

## 2.6 Résumé rapport de stage

> Le projet structure le traitement des factures en quatre agents spécialisés coordonnés par un orchestrateur central, reflet d'une réalité technique : les quatre opérations métier (extraction OCR, classification PCE, détection d'anomalies, génération d'écritures comptables) ne partagent pas les mêmes outils et n'ont pas la même nature — l'extraction mobilise Tesseract et PyMuPDF, la classification combine ML supervisé et embeddings, la validation est purement déterministe, et la comptabilité est de l'arithmétique réglementaire. Le découpage en agents séparés permet d'isoler les pannes (une facture sait à quelle étape précise elle a échoué), de tester chaque composant indépendamment, et de maintenir un garde-fou métier essentiel : une facture détectée comme anomale ne génère jamais automatiquement d'écriture comptable. Il serait honnête de noter que l'implémentation reste plus proche d'un pipeline séquentiel avec un branchement conditionnel que d'un vrai système multi-agents au sens fort — le terme "orchestrateur" est quelque peu ambitieux pour ce qui est essentiellement une fonction de 250 lignes appelant quatre composants dans un ordre fixe. La valeur réelle de l'architecture réside moins dans la sophistication de la coordination que dans la standardisation de l'interface (`AgentResult` avec durée, appels LLM, statut) qui rend le système observable et extensible.
