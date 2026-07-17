# BIAT IT Billing Agent — Diagram Set

19 diagrams for the BIAT IT Billing Agent project (01–19, no 20 yet).
Each file contains Eraser-compatible diagram-as-code.

**01, 05, 09, and 19 were refreshed/added on 2026-07-15** to match the
current MongoDB-primary architecture, the daemon-free invoice pipeline, and
the finalized Docker Compose deployment package — see each file's own
"Updated" note. **All 19 files were translated to English and reviewed for
accuracy on 2026-07-16** — see "Known limitations" below for a few points
still worth double-checking against the live app.

## How to use

1. Open [app.eraser.io](https://app.eraser.io)
2. Create a new diagram
3. Choose the diagram type (noted at the top of each file)
4. Paste the code from the file into the code editor
5. Export as PNG at high resolution

## Brand colors used throughout

| Color  | Hex       | Usage                          |
|--------|-----------|--------------------------------|
| Navy   | `#1A3A5C` | Primary, headers, actors       |
| Blue   | `#2E86C1` | Secondary, flows, links        |
| Amber  | `#F0A500` | AI elements, warnings          |
| Green  | `#1D9E76` | Success, paid, validated       |
| Red    | `#C0391B` | Errors, risks, rejected        |
| Purple | `#804CD7` | Direction role, tokens         |

## Diagram index

| # | File | Type | Description |
|---|------|------|-------------|
| 01 | `01_architecture_technique.md` | Cloud Architecture | Tech stack — MongoDB-primary, updated 2026-07-15 |
| 02 | `02_architecture_fonctionnelle.md` | Flowchart | 8 functional modules |
| 03 | `03_architecture_agents_ia.md` | Cloud Architecture | 7 AI agents + RAG, updated 2026-07-16 |
| 04 | `04_architecture_securite.md` | Flowchart | 5 security layers, updated 2026-07-16 |
| 05 | `05_schema_base_donnees.md` | Entity Relationship | MongoDB collections + remaining SQLite, updated 2026-07-15 |
| 06 | `06_cas_utilisation.md` | Flowchart | Complete use cases |
| 07 | `07_diagramme_classes.md` | Class Diagram | All models + enums |
| 08 | `08_diagramme_objet.md` | Entity Relationship | CAPEX snapshot |
| 09 | `09_seq_traitement_facture.md` | Sequence | PDF → JOURNALED (no daemon, no EXPORTING), updated 2026-07-15 |
| 10 | `10_seq_authentification.md` | Sequence | Login + OTP + refresh, updated 2026-07-16 |
| 11 | `11_seq_validation_manuelle.md` | Sequence | FLAGGED → JOURNALED |
| 12 | `12_seq_facture_client.md` | Sequence | Client invoice flow |
| 13 | `13_seq_capex.md` | Sequence | CAPEX + AI amortization, updated 2026-07-16 |
| 14 | `14_workflow_statuts_facture.md` | State Diagram | Invoice state machine, updated 2026-07-16 |
| 15 | `15_workflow_echeancier_penalites.md` | Flowchart | Payments + penalties |
| 16 | `16_workflow_gestion_risques.md` | Flowchart | Risk lifecycle, updated 2026-07-16 |
| 17 | `17_flux_par_role.md` | Flowchart | Daily workflow per role |
| 18 | `18_risques_dans_processus.md` | Flowchart | Risks embedded in process |
| 19 | `19_deploiement_docker_compose.md` | Cloud Architecture | Docker Compose deployment package, added 2026-07-15 |

## Known limitations (2026-07-16 translation/review pass)

- `all_plantuml.puml` (a full PlantUML-format duplicate of diagrams 1–18,
  predating the MongoDB migration) is not part of this index and was not
  touched in this pass — it's stale and redundant with the files above, kept
  only pending an explicit decision to remove it.
- French field/attribute names inside diagram code (e.g. `titre`, `statut`,
  `probabilite`, `nom`, `prenom`) were deliberately left untranslated where
  they mirror real code identifiers — translating them would make the
  diagram inaccurate, not just non-English.
