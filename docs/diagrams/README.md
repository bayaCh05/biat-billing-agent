# BIAT IT Billing Agent — Diagram Set

All 17 diagrams for the BIAT IT Billing Agent project.
Each file contains Eraser-compatible diagram-as-code.

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
| 01 | `01_architecture_technique.md` | Cloud Architecture | Tech stack (5 layers) |
| 02 | `02_architecture_fonctionnelle.md` | Flowchart | 8 functional modules |
| 03 | `03_architecture_agents_ia.md` | Cloud Architecture | 6 AI agents + RAG |
| 04 | `04_architecture_securite.md` | Flowchart | 5 security layers |
| 05 | `05_schema_base_donnees.md` | Entity Relationship | 9 main tables + FKs |
| 06 | `06_cas_utilisation.md` | Flowchart | Complete use cases |
| 07 | `07_diagramme_classes.md` | Class Diagram | All models + enums |
| 08 | `08_diagramme_objet.md` | Entity Relationship | CAPEX snapshot |
| 09 | `09_seq_traitement_facture.md` | Sequence | PDF → JOURNALED |
| 10 | `10_seq_authentification.md` | Sequence | Login + OTP + refresh |
| 11 | `11_seq_validation_manuelle.md` | Sequence | FLAGGED → JOURNALED |
| 12 | `12_seq_facture_client.md` | Sequence | Client invoice flow |
| 13 | `13_seq_capex.md` | Sequence | CAPEX + AI amortization |
| 14 | `14_workflow_statuts_facture.md` | State Diagram | Invoice state machine |
| 15 | `15_workflow_echeancier_penalites.md` | Flowchart | Payments + penalties |
| 16 | `16_workflow_gestion_risques.md` | Flowchart | Risk lifecycle |
| 17 | `17_flux_par_role.md` | Flowchart | Daily workflow per role |
