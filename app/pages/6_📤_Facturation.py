"""Facturation client — émission mensuelle BIAT IT → BIAT (projet par projet)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

import pandas as pd
import streamlit as st

from app._backend import (
    format_tnd,
    get_client_invoice_repo,
    get_invoice_builder,
    get_monthly_invoice_builder,
    get_pdf_generator,
    get_project_repo,
    require_auth,
)
from src.billing.invoice_numbering import InvoiceNumberer
from src.models.project import (
    AvanceProgrammee,
    CharteProjet,
    FicheMensuelle,
    FicheStatus,
    Phase,
    PhaseStatus,
)

require_auth()

st.title("📤 Facturation Client")
st.caption("Émission mensuelle BIAT IT → BIAT — phases clôturées et avances sur projets.")

if st.button("🔄 Actualiser"):
    st.cache_resource.clear()
    st.rerun()

tab1, tab2, tab3 = st.tabs([
    "📋 Projets & Chartes",
    "📝 Fiche Mensuelle",
    "📜 Historique",
])

# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 — Chartes & phases
# ─────────────────────────────────────────────────────────────────────────────

with tab1:
    project_repo = get_project_repo()
    chartes = project_repo.list_active_chartes()

    # ── Chartes table ──────────────────────────────────────────────────────────
    st.subheader(f"Chartes de projet actives ({len(chartes)})")
    if chartes:
        rows = []
        for c in chartes:
            phases = project_repo.list_phases_by_project(c.project_id)
            closed = sum(1 for p in phases if p.status == PhaseStatus.CLOSED)
            rows.append({
                "Réf. charte":   c.id,
                "Projet":        c.project_name,
                "Budget JH":     c.budget_jh,
                "Taux JH (TND)": f"{c.taux_jh:,.2f}",
                "Valide jusqu'au": str(c.valid_until) if c.valid_until else "—",
                "Phases (clôt./tot.)": f"{closed}/{len(phases)}",
                "Statut":        "✅ Active" if c.is_active else "⚪ Inactive",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("Aucune charte active. Ajoutez-en une ci-dessous.")

    st.divider()

    # ── Add charte form ────────────────────────────────────────────────────────
    with st.expander("➕ Nouvelle charte de projet"):
        with st.form("new_charte_form"):
            c1, c2 = st.columns(2)
            charte_id    = c1.text_input("Réf. charte *", placeholder="CHR-2026-0001")
            project_id   = c2.text_input("ID projet *",   placeholder="PRJ-001")
            project_name = st.text_input("Nom du projet *")
            c3, c4 = st.columns(2)
            budget_jh = c3.number_input("Budget JH *", min_value=1.0, value=100.0, step=10.0)
            taux_jh   = c4.number_input("Taux JH (TND) *", min_value=1.0, value=850.0, step=50.0)
            c5, c6 = st.columns(2)
            valid_from  = c5.date_input("Valide à partir du *", value=date.today())
            valid_until = c6.date_input("Valide jusqu'au (optionnel)", value=None)
            submitted = st.form_submit_button("Enregistrer", type="primary")
        if submitted:
            if not charte_id.strip() or not project_id.strip() or not project_name.strip():
                st.error("Réf. charte, ID projet et Nom du projet sont obligatoires.")
            else:
                project_repo.save_charte(CharteProjet(
                    id=charte_id.strip(),
                    project_id=project_id.strip(),
                    project_name=project_name.strip(),
                    valid_from=valid_from,
                    valid_until=valid_until,
                    budget_jh=budget_jh,
                    taux_jh=taux_jh,
                ))
                st.success(f"Charte **{charte_id}** enregistrée.")
                st.rerun()

    st.divider()

    # ── Phases per charte ──────────────────────────────────────────────────────
    if chartes:
        st.subheader("Phases par projet")
        _STATUS_ICON = {
            PhaseStatus.OPEN:      "🔵 Ouverte",
            PhaseStatus.CLOSED:    "✅ Clôturée",
            PhaseStatus.CANCELLED: "⚪ Annulée",
        }
        for c in chartes:
            phases = project_repo.list_phases_by_project(c.project_id)
            label = f"**{c.project_name}** ({c.id}) — {len(phases)} phase(s)"
            with st.expander(label):
                if phases:
                    rows = []
                    for p in phases:
                        rows.append({
                            "Phase":       p.name,
                            "JH planifié": p.planned_jh,
                            "JH consommé": p.consumed_jh,
                            "Montant HT":  format_tnd(p.consumed_jh * c.taux_jh),
                            "Livrables":   ", ".join(p.livrables) or "—",
                            "Statut":      _STATUS_ICON.get(p.status, p.status.value),
                            "Clôturée le": str(p.closed_date) if p.closed_date else "—",
                        })
                    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                else:
                    st.info("Aucune phase enregistrée pour ce projet.")

                # Close open phases
                open_phases = [p for p in phases if p.status == PhaseStatus.OPEN]
                if open_phases:
                    st.markdown("**Clôturer une phase**")
                    for phase in open_phases:
                        with st.container(border=True):
                            st.caption(f"Phase : {phase.name} — {phase.planned_jh} JH planifiés")
                            with st.form(f"close_phase_{phase.id}"):
                                cp1, cp2 = st.columns(2)
                                consumed_jh = cp1.number_input(
                                    "JH consommés",
                                    min_value=0.0,
                                    value=float(phase.planned_jh),
                                    step=0.5,
                                    key=f"jh_{phase.id}",
                                )
                                closed_date = cp2.date_input(
                                    "Date de clôture",
                                    value=date.today(),
                                    key=f"date_{phase.id}",
                                )
                                livrables_text = st.text_area(
                                    "Livrables (un par ligne)",
                                    key=f"liv_{phase.id}",
                                    height=80,
                                )
                                if st.form_submit_button(f"✅ Clôturer {phase.name}", type="primary"):
                                    livrables = [
                                        l.strip()
                                        for l in livrables_text.split("\n")
                                        if l.strip()
                                    ]
                                    try:
                                        project_repo.close_phase(
                                            phase.id,
                                            closed_date,
                                            consumed_jh,
                                            livrables,
                                        )
                                        st.success(
                                            f"Phase **{phase.name}** clôturée — "
                                            f"{consumed_jh} JH enregistrés."
                                        )
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(f"Erreur : {exc}")

                # Add phase form
                with st.form(f"new_phase_{c.project_id}"):
                    st.caption("Ajouter une phase")
                    p1, p2 = st.columns(2)
                    phase_id   = p1.text_input("ID phase *", key=f"pid_{c.project_id}")
                    phase_name = p2.text_input("Nom de la phase *", key=f"pname_{c.project_id}")
                    planned_jh = st.number_input("JH planifié *", min_value=0.1, value=10.0,
                                                  key=f"pjh_{c.project_id}")
                    if st.form_submit_button("Ajouter"):
                        if phase_id.strip() and phase_name.strip():
                            project_repo.save_phase(Phase(
                                id=phase_id.strip(),
                                project_id=c.project_id,
                                name=phase_name.strip(),
                                planned_jh=planned_jh,
                                status=PhaseStatus.OPEN,
                            ))
                            st.success(f"Phase **{phase_name}** ajoutée.")
                            st.rerun()
                        else:
                            st.error("ID et nom de la phase sont obligatoires.")


# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 — Fiche mensuelle
# ─────────────────────────────────────────────────────────────────────────────

with tab2:
    project_repo = get_project_repo()

    # ── Section A — Period ─────────────────────────────────────────────────────
    st.subheader("Paramètres de la période")
    c1, c2 = st.columns(2)
    today = date.today()
    period_month = c1.selectbox(
        "Mois",
        options=list(range(1, 13)),
        index=today.month - 1,
        format_func=lambda m: [
            "Janvier","Février","Mars","Avril","Mai","Juin",
            "Juillet","Août","Septembre","Octobre","Novembre","Décembre"
        ][m - 1],
    )
    period_year = c2.number_input("Année", value=today.year, min_value=2020, max_value=2040)

    st.divider()

    chartes = project_repo.list_active_chartes()
    charte_by_project: dict[str, CharteProjet] = {c.project_id: c for c in chartes}

    # ── Section B — Phases clôturées ───────────────────────────────────────────
    st.subheader("Phases clôturées ce mois")

    # Collect already-billed phase IDs (in submitted/billed fiches for any period)
    existing_fiches = project_repo.list_fiches(year=int(period_year))
    billed_phase_ids: set[str] = set()
    for f in existing_fiches:
        if f.status in (FicheStatus.SUBMITTED, FicheStatus.BILLED):
            billed_phase_ids.update(f.phases_cloturees)

    # Gather all closed phases across all projects
    all_closed: list[tuple[Phase, CharteProjet]] = []
    for charte in chartes:
        for phase in project_repo.list_phases_by_project(
            charte.project_id, status=PhaseStatus.CLOSED
        ):
            all_closed.append((phase, charte))

    if not all_closed:
        st.info("Aucune phase clôturée disponible. Clôturez des phases dans l'onglet **Projets & Chartes**.")

    selected_phase_ids: list[str] = []
    if "phase_selections" not in st.session_state:
        st.session_state.phase_selections = {}

    for phase, charte in all_closed:
        already = phase.id in billed_phase_ids
        col_cb, col_info = st.columns([1, 8])
        default_checked = st.session_state.phase_selections.get(phase.id, not already)
        checked = col_cb.checkbox(
            phase.name, key=f"cb_{phase.id}", value=default_checked,
            disabled=already, label_visibility="hidden",
        )
        st.session_state.phase_selections[phase.id] = checked
        montant = phase.consumed_jh * charte.taux_jh
        with col_info.container(border=True):
            badge = "🔒 Déjà facturée" if already else ""
            st.markdown(
                f"**[{charte.project_id}] {charte.project_name}** — {phase.name}  {badge}\n\n"
                f"Charte : `{charte.id}` &nbsp;|&nbsp; "
                f"Livrables : {', '.join(phase.livrables) or '—'} &nbsp;|&nbsp; "
                f"**{phase.consumed_jh} JH × {charte.taux_jh:,.2f} TND = "
                f"{format_tnd(montant)}**"
            )
        if checked and not already:
            selected_phase_ids.append(phase.id)

    st.divider()

    # ── Section C — Avances ────────────────────────────────────────────────────
    st.subheader("Avances sur projets programmés")

    if "avance_lines" not in st.session_state:
        st.session_state.avance_lines = []

    def _remove_avance(idx: int):
        st.session_state.avance_lines.pop(idx)

    for i, av in enumerate(st.session_state.avance_lines):
        with st.container(border=True):
            st.caption(f"Avance {i + 1}")
            ac1, ac2, ac3 = st.columns([3, 2, 1])
            ac1.markdown(f"**{av['project_id']}** — {av['description'][:60]}")
            ac2.markdown(f"Réf : `{av['schedule_reference']}`")
            ac3.markdown(format_tnd(av["montant_ht"]))
            if st.button("✖ Supprimer", key=f"del_av_{i}"):
                _remove_avance(i)
                st.rerun()

    with st.expander("➕ Ajouter une avance"):
        with st.form("add_avance_form"):
            if chartes:
                av_project = st.selectbox(
                    "Projet *",
                    options=[c.project_id for c in chartes],
                    format_func=lambda pid: next(
                        (c.project_name for c in chartes if c.project_id == pid), pid
                    ),
                )
                av_charte = charte_by_project.get(av_project)
                av_ref    = st.text_input("Référence planning *", placeholder="PLAN-2026-Q3")
                av_desc   = st.text_area("Description *", height=80)
                av_amt    = st.number_input("Montant HT (TND) *", min_value=0.01, value=10000.0, step=500.0)
                if st.form_submit_button("Ajouter"):
                    if av_ref.strip() and av_desc.strip() and av_charte:
                        st.session_state.avance_lines.append({
                            "project_id":         av_project,
                            "charte_id":          av_charte.id,
                            "description":        av_desc.strip(),
                            "schedule_reference": av_ref.strip(),
                            "montant_ht":         av_amt,
                        })
                        st.rerun()
                    else:
                        st.error("Tous les champs sont obligatoires.")
            else:
                st.info("Aucune charte active disponible.")
                st.form_submit_button("Ajouter", disabled=True)

    st.divider()

    # ── Section D — Preview & Generate ────────────────────────────────────────
    st.subheader("Récapitulatif & Génération")

    # Build totals from selection
    phase_map = {p.id: (p, c) for p, c in all_closed}
    total_jh  = sum(
        phase_map[pid][0].consumed_jh
        for pid in selected_phase_ids if pid in phase_map
    )
    total_phase_ht = sum(
        phase_map[pid][0].consumed_jh * phase_map[pid][1].taux_jh
        for pid in selected_phase_ids if pid in phase_map
    )
    total_avance_ht = sum(av["montant_ht"] for av in st.session_state.avance_lines)
    grand_total_ht  = total_phase_ht + total_avance_ht

    m1, m2, m3 = st.columns(3)
    m1.metric("Phases sélectionnées", len(selected_phase_ids))
    m2.metric("Total JH", f"{total_jh:.1f} JH")
    m3.metric("Total HT", format_tnd(grand_total_ht))

    can_generate = len(selected_phase_ids) > 0 or len(st.session_state.avance_lines) > 0

    if not can_generate:
        st.info("Sélectionnez au moins une phase clôturée ou ajoutez une avance pour générer la facture.")

    if can_generate and st.button("✅ Générer la facture mensuelle", type="primary"):
        try:
            with st.spinner("Génération en cours…"):
                # Build avance models
                avances = [
                    AvanceProgrammee(
                        project_id=av["project_id"],
                        charte_id=av["charte_id"],
                        description=av["description"],
                        montant_ht=av["montant_ht"],
                        schedule_reference=av["schedule_reference"],
                    )
                    for av in st.session_state.avance_lines
                ]

                # Create and save fiche
                fiche = FicheMensuelle(
                    id=f"FICHE-{int(period_year)}-{int(period_month):02d}-{uuid4().hex[:6].upper()}",
                    period_month=int(period_month),
                    period_year=int(period_year),
                    prepared_by="BIAT IT",
                    prepared_at=datetime.now(timezone.utc),
                    phases_cloturees=selected_phase_ids,
                    avances=avances,
                    status=FicheStatus.DRAFT,
                )
                project_repo.save_fiche(fiche)
                fiche = project_repo.submit_fiche(fiche.id)  # DRAFT → SUBMITTED

                # Build ClientInvoice
                client_inv_repo = get_client_invoice_repo()
                numberer = InvoiceNumberer(client_inv_repo)
                builder  = get_monthly_invoice_builder()
                invoice  = builder.build_from_fiche(fiche, project_repo, numberer)

                # Save invoice
                client_inv_repo.save(invoice)

                # Generate PDF
                pdf_gen   = get_pdf_generator()
                pdf_bytes = pdf_gen.generate_to_bytes(invoice)
                client_inv_repo.update_status(
                    invoice.id, invoice.status,
                    pdf_path=str(pdf_gen.generate(invoice)),
                )

            # Clear session state
            st.session_state.avance_lines = []
            st.session_state.phase_selections = {}

            st.success(f"Facture **{invoice.invoice_number}** générée — fiche `{fiche.id}`.")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("N° facture",   invoice.invoice_number)
            m2.metric("HT",           format_tnd(invoice.amount_ht))
            m3.metric("TVA",          format_tnd(invoice.tva_amount))
            m4.metric("TTC",          format_tnd(invoice.amount_ttc))

            st.download_button(
                "⬇ Télécharger la facture PDF",
                data=pdf_bytes,
                file_name=f"{invoice.invoice_number}.pdf",
                mime="application/pdf",
                type="primary",
            )
        except Exception as exc:
            st.error(f"Erreur lors de la génération : {exc}")
            raise


# ─────────────────────────────────────────────────────────────────────────────
# Tab 3 — Historique
# ─────────────────────────────────────────────────────────────────────────────

with tab3:
    project_repo = get_project_repo()
    today = date.today()

    year_hist = st.number_input(
        "Exercice", value=today.year, min_value=2020, max_value=2040, key="hist_year"
    )
    fiches = project_repo.list_fiches(year=int(year_hist))

    if not fiches:
        st.info(f"Aucune fiche mensuelle pour l'exercice {int(year_hist)}.")
    else:
        _FICHE_STATUS = {
            FicheStatus.DRAFT:     "⚪ Brouillon",
            FicheStatus.SUBMITTED: "🔵 Soumise",
            FicheStatus.BILLED:    "✅ Facturée",
        }

        client_inv_repo = get_client_invoice_repo()
        # Index invoices by the fiche ID embedded in their notes field (O(1) lookup)
        inv_by_fiche: dict[str, object] = {}
        for inv in client_inv_repo.list_all():
            if inv.notes:
                # notes format: "... réf. {fiche.id}"
                for part in inv.notes.split("réf. "):
                    key = part.strip().split()[0] if part.strip() else ""
                    if key.startswith("FICHE-"):
                        inv_by_fiche[key] = inv
                        break

        rows = []
        for f in sorted(fiches, key=lambda x: (x.period_year, x.period_month), reverse=True):
            matched_inv = inv_by_fiche.get(f.id)
            rows.append({
                "Période":     f"{f.period_month:02d}/{f.period_year}",
                "Réf. fiche":  f.id,
                "Nb phases":   len(f.phases_cloturees),
                "Nb avances":  len(f.avances),
                "Statut":      _FICHE_STATUS.get(f.status, f.status.value),
                "N° Facture":  matched_inv.invoice_number if matched_inv else "—",
                "Total HT":    format_tnd(matched_inv.amount_ht) if matched_inv else "—",
            })

        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        # Detail expanders
        st.divider()
        for f in sorted(fiches, key=lambda x: (x.period_year, x.period_month), reverse=True):
            matched_inv = inv_by_fiche.get(f.id)
            with st.expander(f"📄 {f.id} — {f.period_month:02d}/{f.period_year}"):
                c1, c2 = st.columns(2)
                c1.markdown(f"**Statut :** {_FICHE_STATUS.get(f.status, f.status.value)}")
                c1.markdown(f"**Phases clôturées :** {len(f.phases_cloturees)}")
                c2.markdown(f"**Avances :** {len(f.avances)}")
                c2.markdown(f"**Préparée par :** {f.prepared_by}")

                if matched_inv:
                    st.markdown(f"**Facture :** `{matched_inv.invoice_number}` — "
                                f"HT {format_tnd(matched_inv.amount_ht)}")
                    try:
                        pdf_gen   = get_pdf_generator()
                        pdf_bytes = pdf_gen.generate_to_bytes(matched_inv)
                        st.download_button(
                            "⬇ PDF",
                            data=pdf_bytes,
                            file_name=f"{matched_inv.invoice_number}.pdf",
                            mime="application/pdf",
                            key=f"dl_hist_{f.id}",
                        )
                    except Exception:
                        pass
