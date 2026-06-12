"""Registre des immobilisations CAPEX — plans d'amortissement."""
from __future__ import annotations

from datetime import date
from uuid import uuid4

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app._backend import (
    require_auth,
    format_tnd,
    get_asset_repo,
    get_depreciation_calculator,
    get_depreciation_entry_generator,
    get_journal_repo,
    get_project_repo,
)
from src.accounting.plan_comptable import ComptesAmortissement
from src.models.asset import Asset

require_auth()

st.title("🏗️ Registre des Immobilisations")
st.caption("Suivi CAPEX — plans d'amortissement linéaire et dégressif (PCE tunisien).")

asset_repo = get_asset_repo()
calc = get_depreciation_calculator()

# French labels for depreciation methods (display only — internal values unchanged)
_METHOD_FR = {"linear": "Linéaire", "degressive": "Dégressive"}

def _method_label(method: str) -> str:
    return _METHOD_FR.get(method, method.capitalize())

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs([
    "📋 Registre",
    "📈 Plan d'amortissement",
    "➕ Ajouter une immobilisation",
])

# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 — Asset register
# ─────────────────────────────────────────────────────────────────────────────

with tab1:
    st.subheader("Registre des immobilisations")

    show_fully = st.checkbox("Inclure les immobilisations totalement amorties", value=False)
    assets = asset_repo.list_all(include_fully_depreciated=show_fully)

    if not assets:
        st.info("Aucune immobilisation enregistrée. Utilisez l'onglet **➕ Ajouter** pour commencer.")
    else:
        today = date.today()
        rows = []
        for a in assets:
            vnc = a.book_value_at(today)
            amort_cumule = round(a.acquisition_cost_ht - vnc, 2)
            pct = round(amort_cumule / a.acquisition_cost_ht * 100, 1) if a.acquisition_cost_ht else 0
            end_year = a.acquisition_date.year + a.useful_life_years
            fully = round(vnc, 2) == 0.0
            rows.append({
                "Statut":             "✅ Amorti" if fully else "🔄 En cours",
                "Désignation":        a.designation,
                "Compte immo":        a.compte_immobilisation,
                "Méthode":            _method_label(a.depreciation_method),
                "Date acquisition":   a.acquisition_date.strftime("%d/%m/%Y"),
                "Valeur brute (TND)": round(a.acquisition_cost_ht, 2),
                "Amort. cumulé":      amort_cumule,
                "VNC (TND)":          round(vnc, 2),
                "Amorti %":           f"{pct:.1f}%",
                "Fin amort.":         end_year,
                "_id":                str(a.id),
            })

        df = pd.DataFrame(rows)
        display_cols = [c for c in df.columns if c != "_id"]
        styled_register = df[display_cols].style.set_properties(
            subset=["Valeur brute (TND)", "Amort. cumulé", "VNC (TND)"],
            **{"text-align": "right"},
        )
        st.dataframe(styled_register, width="stretch", hide_index=True)

        # KPIs
        total_brut = sum(a.acquisition_cost_ht for a in assets)
        total_vnc = sum(a.book_value_at(today) for a in assets)
        total_amort = total_brut - total_vnc

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Immobilisations", len(assets))
        k2.metric("Valeur brute totale", format_tnd(total_brut, 0))
        k3.metric("Amort. cumulé total", format_tnd(total_amort, 0))
        k4.metric("VNC totale", format_tnd(total_vnc, 0))

        st.divider()

        # Delete action
        with st.expander("Supprimer une immobilisation"):
            asset_labels = {str(a.id): a.designation for a in assets}
            to_delete = st.selectbox(
                "Choisir l'immobilisation à supprimer",
                options=list(asset_labels.keys()),
                format_func=lambda k: asset_labels[k],
            )
            if st.button("Supprimer", type="secondary"):
                from uuid import UUID
                asset_repo.delete(UUID(to_delete))
                st.success("Immobilisation supprimée.")
                st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 — Depreciation schedule
# ─────────────────────────────────────────────────────────────────────────────

with tab2:
    st.subheader("Plan d'amortissement détaillé")

    assets_all = asset_repo.list_all(include_fully_depreciated=True)

    if not assets_all:
        st.info("Aucune immobilisation enregistrée.")
    else:
        selected_id = st.selectbox(
            "Choisir une immobilisation",
            options=[str(a.id) for a in assets_all],
            format_func=lambda aid: next(
                (a.designation for a in assets_all if str(a.id) == aid), aid
            ),
        )
        selected_asset = next((a for a in assets_all if str(a.id) == selected_id), None)

        if selected_asset:
            schedule = calc.schedule(
                asset_id=str(selected_asset.id),
                designation=selected_asset.designation,
                acquisition_cost_ht=selected_asset.acquisition_cost_ht,
                acquisition_date=selected_asset.acquisition_date,
                useful_life_years=selected_asset.useful_life_years,
                method=selected_asset.depreciation_method,
            )

            # Summary header — item 3 (2 dp) + item 5 (French method label)
            c1, c2, c3 = st.columns(3)
            c1.metric("Valeur d'entrée HT", format_tnd(selected_asset.acquisition_cost_ht))
            c2.metric("Durée", f"{selected_asset.useful_life_years} ans")
            c3.metric("Méthode", _method_label(selected_asset.depreciation_method))

            # Year filter
            all_years = sorted({ln.year for ln in schedule.lines})
            view_mode = st.radio("Affichage", ["Par année", "Tableau complet"], horizontal=True)

            if view_mode == "Par année":
                chosen_year = st.selectbox("Année", options=all_years)
                year_lines = schedule.lines_for_year(chosen_year)
                month_names = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]
                sched_df = pd.DataFrame([
                    {
                        "Mois":               month_names[ln.month - 1],
                        "Dotation (TND)":     round(ln.depreciation_amount, 2),
                        "Amort. cumulé":      round(ln.cumulated_depreciation, 2),
                        "VNC (TND)":          round(ln.book_value, 2),
                        "Méthode appliquée":  ln.method_used,
                    }
                    for ln in year_lines
                ])
                # Item 4 — right-align numeric columns
                styled_sched = sched_df.style.set_properties(
                    subset=["Dotation (TND)", "Amort. cumulé", "VNC (TND)"],
                    **{"text-align": "right"},
                )
                st.dataframe(styled_sched, width="stretch", hide_index=True)
                annual = schedule.annual_depreciation_for_year(chosen_year)
                # Item 2 — 2 dp on dotation caption
                st.caption(f"Dotation annuelle {chosen_year} : **{format_tnd(annual)}**")

                # Item 7 — download button
                csv_data = sched_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="⬇️ Télécharger le plan (.csv)",
                    data=csv_data,
                    file_name=f"plan_amort_{selected_asset.designation}_{chosen_year}.csv",
                    mime="text/csv",
                )

            else:
                sched_df = pd.DataFrame([
                    {
                        "Période":            ln.period_label,
                        "Dotation (TND)":     round(ln.depreciation_amount, 2),
                        "Amort. cumulé":      round(ln.cumulated_depreciation, 2),
                        "VNC (TND)":          round(ln.book_value, 2),
                        "Méthode":            ln.method_used,
                    }
                    for ln in schedule.lines
                ])
                # Item 4 — right-align numeric columns
                styled_sched = sched_df.style.set_properties(
                    subset=["Dotation (TND)", "Amort. cumulé", "VNC (TND)"],
                    **{"text-align": "right"},
                )
                st.dataframe(styled_sched, width="stretch", hide_index=True)

                # Item 7 — download button
                csv_data = sched_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="⬇️ Télécharger le plan (.csv)",
                    data=csv_data,
                    file_name=f"plan_amort_{selected_asset.designation}_complet.csv",
                    mime="text/csv",
                )

            # VNC chart
            st.subheader("Évolution de la VNC")
            annual_data: dict[int, dict] = {}
            for ln in schedule.lines:
                if ln.month == 12 or ln == schedule.lines[-1]:
                    annual_data[ln.year] = {
                        "vnc": ln.book_value,
                        "amort": ln.cumulated_depreciation,
                    }

            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=list(annual_data.keys()),
                y=[v["amort"] for v in annual_data.values()],
                name="Amort. cumulé",
                marker_color="#FFB800",
            ))
            fig.add_trace(go.Bar(
                x=list(annual_data.keys()),
                y=[v["vnc"] for v in annual_data.values()],
                name="VNC",
                marker_color="#003366",
            ))
            fig.add_trace(go.Scatter(
                x=list(annual_data.keys()),
                y=[v["vnc"] for v in annual_data.values()],
                mode="lines+markers",
                name="VNC (ligne)",
                line=dict(color="#e53935", width=2),
                yaxis="y",
            ))
            fig.update_layout(
                barmode="stack",
                xaxis_title="Année",
                yaxis_title="TND",
                height=380,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(t=40, b=40),
            )
            # Item 1 — force integer year ticks on X axis
            min_year = min(annual_data.keys()) if annual_data else date.today().year
            fig.update_xaxes(
                tickmode="linear",
                tick0=int(min_year),
                dtick=1,
                tickformat="d",
            )
            st.plotly_chart(fig, width="stretch")

            # Generate journal entries
            st.subheader("Générer les écritures comptables")
            col_y, col_m, col_btn = st.columns([2, 2, 3])
            with col_y:
                entry_year = st.selectbox("Année", options=all_years, key="entry_year")
            with col_m:
                entry_mode = st.radio("Mode", ["Mensuel", "Annuel"], horizontal=True)

            if entry_mode == "Mensuel":
                with col_m:
                    entry_month = st.selectbox(
                        "Mois", options=list(range(1, 13)),
                        format_func=lambda m: ["Jan","Fév","Mar","Avr","Mai","Jun",
                                               "Jul","Aoû","Sep","Oct","Nov","Déc"][m-1],
                        key="entry_month",
                    )
                target_lines = [
                    ln for ln in schedule.lines
                    if ln.year == entry_year and ln.month == entry_month
                ]
            else:
                target_lines = schedule.lines_for_year(entry_year)
                entry_month = None

            with col_btn:
                st.write("")
                if st.button("Générer & Enregistrer l'écriture", type="primary"):
                    gen = get_depreciation_entry_generator()
                    journal_repo = get_journal_repo()

                    if entry_mode == "Mensuel" and target_lines:
                        ln = target_lines[0]
                        entry = gen.monthly_entry(selected_asset, ln.year, ln.month, ln.depreciation_amount)
                        journal_repo.save(entry)
                        # Item 2 — 2 dp on success amounts
                        st.success(f"Écriture mensuelle enregistrée : **{entry.reference}** — {format_tnd(ln.depreciation_amount)}")
                    elif entry_mode == "Annuel" and target_lines:
                        annual_amount = sum(ln.depreciation_amount for ln in target_lines)
                        entry = gen.annual_entry(selected_asset, entry_year, annual_amount)
                        journal_repo.save(entry)
                        st.success(f"Écriture annuelle enregistrée : **{entry.reference}** — {format_tnd(annual_amount)}")
                    else:
                        st.warning("Aucune ligne d'amortissement pour la période sélectionnée.")

            # ── Project allocation ────────────────────────────────────────────
            st.divider()
            st.subheader("Allocation aux projets")
            st.caption(
                "Définissez quelle part de cet actif est affectée à chaque projet. "
                "La somme doit être égale à 100 %."
            )

            _proj_repo = get_project_repo()
            try:
                project_repo = _proj_repo
                chartes = project_repo.list_active_chartes()

                # Current monthly depreciation for this asset (current month)
                today_alloc = date.today()
                monthly_dep = next(
                    (ln.depreciation_amount for ln in schedule.lines
                     if ln.year == today_alloc.year and ln.month == today_alloc.month),
                    0.0,
                )

                # Load existing links
                existing_links = {
                    lnk.project_id: lnk.allocation_pct
                    for lnk in asset_repo.get_links_by_asset(str(selected_asset.id))
                }

                if not chartes:
                    st.info("Aucune charte active. Ajoutez des projets dans l'onglet Facturation.")
                else:
                    with st.form(f"alloc_form_{selected_asset.id}"):
                        alloc_vals: dict[str, float] = {}
                        for charte in chartes:
                            default_pct = existing_links.get(charte.project_id, 0.0)
                            alloc_vals[charte.project_id] = st.number_input(
                                f"{charte.project_name} ({charte.project_id})",
                                min_value=0.0, max_value=100.0,
                                value=default_pct, step=5.0,
                                key=f"alloc_{selected_asset.id}_{charte.project_id}",
                            )
                        total_pct = sum(alloc_vals.values())
                        st.caption(f"Total alloué : **{total_pct:.1f}%** (doit être 100%)")

                        if st.form_submit_button("Enregistrer l'allocation", type="primary"):
                            if abs(total_pct - 100.0) > 0.01 and total_pct > 0:
                                st.error(f"La somme des pourcentages est {total_pct:.1f}% — elle doit être 100%.")
                            else:
                                from src.models.cost_allocation import AssetProjectLink
                                for pid, pct in alloc_vals.items():
                                    if pct > 0:
                                        asset_repo.save_link(AssetProjectLink(
                                            asset_id=str(selected_asset.id),
                                            project_id=pid,
                                            allocation_pct=pct,
                                        ))
                                st.success("Allocation enregistrée.")
                                st.rerun()

                    # Monthly CAPEX value per project
                    if existing_links and monthly_dep > 0:
                        st.markdown("**Valeur mensuelle CAPEX par projet** "
                                    f"(base : {format_tnd(monthly_dep)}/mois)")
                        cols = st.columns(min(len(existing_links), 4))
                        for i, (pid, pct) in enumerate(existing_links.items()):
                            cname = next(
                                (c.project_name for c in chartes if c.project_id == pid), pid
                            )
                            monthly_val = monthly_dep * pct / 100
                            cols[i % len(cols)].metric(
                                cname,
                                f"{monthly_val:,.2f} TND/mois",
                                help=f"{pct:.1f}% de {format_tnd(monthly_dep)}/mois",
                            )
            except Exception as exc:
                st.warning(f"Allocation non disponible : {exc}")
            finally:
                _proj_repo.session.close()

# ─────────────────────────────────────────────────────────────────────────────
# Tab 3 — Add asset
# ─────────────────────────────────────────────────────────────────────────────

with tab3:
    st.subheader("Enregistrer une nouvelle immobilisation")

    COMPTE_OPTIONS = {
        "2183 — Matériel informatique": ("2183", "2893"),
        "2284 — Logiciels":             ("2284", "2894"),
        "2184 — Matériel de bureau":    ("2184", "2884"),
        "2844 — Mobilier":              ("2844", "2854"),
        "2241 — Agencements":           ("2241", "2841"),
    }

    with st.form("add_asset_form"):
        designation = st.text_input("Désignation *", placeholder="Ex: Serveur Dell PowerEdge R750")
        compte_label = st.selectbox("Compte d'immobilisation *", options=list(COMPTE_OPTIONS.keys()))
        acq_date = st.date_input("Date d'acquisition *", value=date.today())
        acq_cost = st.number_input("Valeur d'acquisition HT (TND) *", min_value=0.01, value=10000.0, step=100.0)
        life_years = st.number_input("Durée d'amortissement (années) *", min_value=1, max_value=30, value=3)
        method = st.radio(
            "Méthode",
            ["linear", "degressive"],
            format_func=_method_label,
            horizontal=True,
        )
        notes = st.text_area("Notes", placeholder="Optionnel — numéro de série, fournisseur, etc.")

        submitted = st.form_submit_button("Enregistrer l'immobilisation", type="primary")

    if submitted:
        if not designation.strip():
            st.error("La désignation est obligatoire.")
        elif acq_cost <= 0:
            st.error("La valeur d'acquisition doit être positive.")
        else:
            compte_immo, compte_amort = COMPTE_OPTIONS[compte_label]
            new_asset = Asset(
                id=uuid4(),
                designation=designation.strip(),
                compte_immobilisation=compte_immo,
                compte_amortissement=compte_amort,
                acquisition_date=acq_date,
                acquisition_cost_ht=float(acq_cost),
                useful_life_years=int(life_years),
                depreciation_method=method,
                notes=notes.strip(),
            )
            asset_repo.save(new_asset)

            # Preview — item 2: 2 dp on all monetary amounts
            monthly = round(new_asset.acquisition_cost_ht / (new_asset.useful_life_years * 12), 2)

            st.success(f"Immobilisation **{designation}** enregistrée.")
            st.info(
                f"Dotation mensuelle indicative : **{monthly:,.2f} TND/mois** · "
                f"Dotation annuelle : **{monthly * 12:,.2f} TND/an** · "
                f"Fin d'amortissement : **{acq_date.year + life_years}**"
            )
