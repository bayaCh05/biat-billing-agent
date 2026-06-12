"""Budget — Prévu vs Réel et analyse des coûts."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app._backend import (
    require_auth,
    format_tnd,
    get_asset_repo,
    get_budget_tracker,
    get_cost_analyzer,
    get_depreciation_calculator,
    get_project_repo,
    _budget_plan,
    _cost_catalog,
)

require_auth()

st.title("📊 Budget & Analyse des Coûts")
st.caption("Comparaison budget prévu / réalisé — données factures validées.")

# ── Sidebar controls ──────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Paramètres")
    current_year = date.today().year
    year = st.selectbox("Exercice", options=[current_year, current_year - 1], index=0)
    through_month = st.slider(
        "Mois analysé (YTD jusqu'à)",
        min_value=1,
        max_value=12,
        value=date.today().month,
        format="%d",
    )
    month_names = [
        "Jan", "Fév", "Mar", "Avr", "Mai", "Jun",
        "Jul", "Aoû", "Sep", "Oct", "Nov", "Déc",
    ]
    st.caption(f"YTD jusqu'à **{month_names[through_month - 1]} {year}**")

# ── Load data ─────────────────────────────────────────────────────────────────

tracker = get_budget_tracker()
analyzer = get_cost_analyzer()
plan = _budget_plan()
catalog = _cost_catalog()
catalog_labels = {e.id: e.label for e in catalog.all_entries()}

summary = tracker.summary(year, through_month)
ytd_variances = tracker.ytd_variance(year, through_month)

# ── KPI row ───────────────────────────────────────────────────────────────────

k1, k2, k3, k4 = st.columns(4)

variance_color = "inverse" if summary["total_variance_ytd"] > 0 else "normal"

k1.metric(
    "Budget YTD",
    f"{summary['total_budget_ytd']:,.0f} TND",
)
k2.metric(
    "Réalisé YTD",
    f"{summary['total_actual_ytd']:,.0f} TND",
    delta=f"{summary['total_variance_ytd']:+,.0f} TND",
    delta_color=variance_color,
)
k3.metric(
    "Écart %",
    f"{summary['variance_pct']:+.1f}%",
    delta_color=variance_color,
)
k4.metric(
    "Lignes en dépassement",
    summary["lines_over_budget"],
    delta=f"{summary['lines_warning']} en alerte",
    delta_color="off",
)

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 Tableau Budget vs Réel",
    "📈 Évolution mensuelle",
    "🏆 Top catégories",
    "🚨 Anomalies",
])

# ─────────────────────────────────────────────────────────────────────────────
# Tab 1 — Budget vs Réel table
# ─────────────────────────────────────────────────────────────────────────────

with tab1:
    st.subheader(f"Budget vs Réalisé — YTD {month_names[through_month - 1]} {year}")

    status_filter = st.multiselect(
        "Filtrer par statut",
        options=["on_budget", "warning", "over", "under"],
        default=["on_budget", "warning", "over", "under"],
        format_func=lambda s: {
            "on_budget": "✅ Dans le budget",
            "warning":   "⚠️ Alerte",
            "over":      "🔴 Dépassement",
            "under":     "🔵 Sous-réalisé",
        }[s],
    )

    rows = []
    for yv in ytd_variances:
        if yv.status not in status_filter:
            continue
        status_icon = {
            "on_budget": "✅",
            "warning":   "⚠️",
            "over":      "🔴",
            "under":     "🔵",
        }.get(yv.status, "—")
        rows.append({
            "Statut":        status_icon,
            "Catégorie":     yv.label,
            "Budget YTD":    round(yv.budget_ytd, 2),
            "Réalisé YTD":   round(yv.actual_ytd, 2),
            "Écart":         round(yv.variance_ytd, 2),
            "Écart %":       f"{yv.variance_pct_ytd:+.1f}%",
        })

    if not rows:
        st.info("Aucune ligne pour les filtres sélectionnés.")
    else:
        df = pd.DataFrame(rows)
        st.dataframe(
            df.style.map(
                lambda v: "color: #d32f2f; font-weight: bold" if isinstance(v, (int, float)) and v > 0 else
                          "color: #1565c0" if isinstance(v, (int, float)) and v < 0 else "",
                subset=["Écart"],
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            f"Total : Budget **{sum(r['Budget YTD'] for r in rows):,.0f} TND** · "
            f"Réalisé **{sum(r['Réalisé YTD'] for r in rows):,.0f} TND**"
        )

    # Waterfall chart — top overruns
    over_yv = sorted(
        [yv for yv in ytd_variances if yv.variance_ytd != 0],
        key=lambda yv: abs(yv.variance_ytd),
        reverse=True,
    )[:12]

    if over_yv:
        st.subheader("Écarts les plus significatifs")
        fig_wf = go.Figure(go.Bar(
            x=[yv.label[:30] for yv in over_yv],
            y=[yv.variance_ytd for yv in over_yv],
            marker_color=[
                "#d32f2f" if yv.variance_ytd > 0 else "#1565c0"
                for yv in over_yv
            ],
            text=[f"{yv.variance_ytd:+,.0f}" for yv in over_yv],
            textposition="outside",
        ))
        fig_wf.update_layout(
            xaxis_title="Catégorie",
            yaxis_title="Écart (TND)",
            xaxis_tickangle=-35,
            height=400,
            showlegend=False,
            margin=dict(t=20, b=120),
        )
        st.plotly_chart(fig_wf, width="stretch")

# ─────────────────────────────────────────────────────────────────────────────
# Tab 2 — Monthly evolution
# ─────────────────────────────────────────────────────────────────────────────

with tab2:
    st.subheader("Évolution mensuelle — Budget vs Réalisé")

    # Aggregate all categories into a total per month
    monthly_totals: dict[int, dict[str, float]] = {m: {"budget": 0.0, "actual": 0.0} for m in range(1, through_month + 1)}
    for yv in ytd_variances:
        for mv in yv.monthly:
            if mv.month <= through_month:
                monthly_totals[mv.month]["budget"] += mv.budget
                monthly_totals[mv.month]["actual"] += mv.actual

    months_labels = [month_names[m - 1] for m in range(1, through_month + 1)]
    budget_vals = [round(monthly_totals[m]["budget"], 2) for m in range(1, through_month + 1)]
    actual_vals = [round(monthly_totals[m]["actual"], 2) for m in range(1, through_month + 1)]

    fig_line = go.Figure()
    fig_line.add_trace(go.Scatter(
        x=months_labels, y=budget_vals,
        name="Budget prévu",
        mode="lines+markers",
        line=dict(color="#003366", width=2, dash="dash"),
        marker=dict(size=7),
    ))
    fig_line.add_trace(go.Scatter(
        x=months_labels, y=actual_vals,
        name="Réalisé",
        mode="lines+markers",
        line=dict(color="#FFB800", width=2),
        marker=dict(size=7),
        fill="tonexty",
        fillcolor="rgba(255,184,0,0.10)",
    ))
    fig_line.update_layout(
        xaxis_title="Mois",
        yaxis_title="Montant (TND HT)",
        height=380,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=40, b=40),
    )
    st.plotly_chart(fig_line, width="stretch")

    # Per-category monthly breakdown
    st.subheader("Détail mensuel par catégorie")
    selected_cat = st.selectbox(
        "Choisir une catégorie",
        options=[yv.catalog_id for yv in ytd_variances],
        format_func=lambda cid: catalog_labels.get(cid, cid),
    )

    cat_yv = next((yv for yv in ytd_variances if yv.catalog_id == selected_cat), None)
    if cat_yv:
        cat_df = pd.DataFrame([
            {
                "Mois":        month_names[mv.month - 1],
                "Budget":      round(mv.budget, 2),
                "Réalisé":     round(mv.actual, 2),
                "Écart":       round(mv.variance, 2),
                "Statut":      {"on_budget": "✅", "warning": "⚠️", "over": "🔴", "under": "🔵"}.get(mv.status, "—"),
            }
            for mv in cat_yv.monthly
        ])
        st.dataframe(cat_df, width="stretch", hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# Tab 3 — Top categories
# ─────────────────────────────────────────────────────────────────────────────

with tab3:
    st.subheader(f"Top 10 catégories de dépenses — YTD {month_names[through_month - 1]} {year}")

    top = analyzer.top_categories(
        year=year,
        through_month=through_month,
        top_n=10,
        catalog_labels=catalog_labels,
    )

    if not top:
        st.info("Aucune dépense réalisée sur la période sélectionnée.")
    else:
        col_chart, col_table = st.columns([3, 2])

        with col_chart:
            fig_pie = px.pie(
                values=[t["total"] for t in top],
                names=[t["label"][:25] for t in top],
                color_discrete_sequence=px.colors.sequential.Blues_r,
                hole=0.4,
            )
            fig_pie.update_traces(textposition="inside", textinfo="percent+label")
            fig_pie.update_layout(height=400, showlegend=False, margin=dict(t=20))
            st.plotly_chart(fig_pie, width="stretch")

        with col_table:
            top_df = pd.DataFrame([
                {
                    "Catégorie":   t["label"],
                    "Total (TND)": f"{t['total']:,.0f}",
                    "Factures":    t["invoice_count"],
                    "Part %":      f"{t['pct_of_total']:.1f}%",
                }
                for t in top
            ])
            st.dataframe(top_df, width="stretch", hide_index=True)

        # Horizontal bar chart
        fig_bar = px.bar(
            x=[t["total"] for t in reversed(top)],
            y=[t["label"][:30] for t in reversed(top)],
            orientation="h",
            color=[t["total"] for t in reversed(top)],
            color_continuous_scale=["#cce0ff", "#003366"],
            labels={"x": "Montant HT (TND)", "y": ""},
        )
        fig_bar.update_layout(
            height=380,
            coloraxis_showscale=False,
            margin=dict(t=20, b=20, l=200),
        )
        st.plotly_chart(fig_bar, width="stretch")

# ─────────────────────────────────────────────────────────────────────────────
# Tab 4 — Anomalies
# ─────────────────────────────────────────────────────────────────────────────

with tab4:
    st.subheader("Détection d'anomalies de dépenses")
    st.caption(
        "Une anomalie est détectée quand le réalisé d'un mois dépasse **1.5×** "
        "la moyenne historique de la même catégorie (⚠️ alerte) ou **2×** (🔴 critique)."
    )

    col_y, col_m = st.columns(2)
    with col_y:
        anom_year = st.selectbox("Année", options=[current_year, current_year - 1], index=0, key="anom_year")
    with col_m:
        anom_month = st.selectbox(
            "Mois",
            options=list(range(1, 13)),
            index=date.today().month - 1,
            format_func=lambda m: month_names[m - 1],
            key="anom_month",
        )

    anomalies = analyzer.anomalies(
        year=anom_year,
        month=anom_month,
        catalog_labels=catalog_labels,
    )

    if not anomalies:
        st.success("Aucune anomalie détectée pour cette période.")
    else:
        for anom in anomalies:
            icon = "🔴" if anom.severity == "critical" else "⚠️"
            with st.expander(
                f"{icon} {anom.label} — {anom.amount:,.0f} TND "
                f"(×{anom.ratio:.1f} la moyenne historique)",
                expanded=anom.severity == "critical",
            ):
                c1, c2, c3 = st.columns(3)
                c1.metric("Réalisé", f"{anom.amount:,.0f} TND")
                c2.metric("Moyenne historique", f"{anom.historical_avg:,.0f} TND")
                c3.metric("Excès", f"+{anom.excess_amount:,.0f} TND", delta_color="inverse")
                st.caption(
                    f"Catégorie `{anom.catalog_id}` · "
                    f"{anom.invoice_count} facture(s) ce mois · "
                    f"Sévérité : **{anom.severity}**"
                )

# ─────────────────────────────────────────────────────────────────────────────
# OPEX/CAPEX cost allocation per project
# ─────────────────────────────────────────────────────────────────────────────

st.divider()
with st.expander("🏗️ Coût total par projet (OPEX + CAPEX)", expanded=False):
    st.caption(
        "Comparaison du coût réel alloué à chaque projet (OPEX prorata JH + "
        "amortissement CAPEX) avec le montant facturé à BIAT sur la même période."
    )
    try:
        from src.billing.cost_allocator import CostAllocator
        from src.models.asset import Asset

        project_repo = get_project_repo()
        asset_repo   = get_asset_repo()
        calc         = get_depreciation_calculator()
        allocator    = CostAllocator()
        chartes      = project_repo.list_active_chartes()

        if not chartes:
            st.info("Aucune charte de projet active. Créez des projets dans l'onglet Facturation.")
        else:
            # JH per project from all fiches in the YTD range (months 1..through_month)
            fiches_ytd = project_repo.list_fiches(year=year)  # all months for year
            fiches_ytd = [f for f in fiches_ytd if f.period_month <= through_month]

            # Batch-load all phases referenced in those fiches to avoid N+1 queries
            all_phase_ids = {pid for f in fiches_ytd for pid in f.phases_cloturees}
            phase_by_id = {}
            for pid in all_phase_ids:
                p = project_repo.get_phase(pid)
                if p:
                    phase_by_id[p.id] = p

            all_jh: dict[str, float] = {}
            for fiche in fiches_ytd:
                for pid in fiche.phases_cloturees:
                    phase = phase_by_id.get(pid)
                    if phase:
                        all_jh[phase.project_id] = (
                            all_jh.get(phase.project_id, 0.0) + phase.consumed_jh
                        )

            if not any(all_jh.values()):
                st.info(
                    f"Aucun JH enregistré pour {month_names[through_month - 1]} {year}. "
                    "Soumettez une fiche mensuelle pour alimenter cette analyse."
                )
            else:
                # OPEX total for the period from budget tracker
                opex_total = summary.get("total_actual_ytd", 0.0) or 0.0

                # Assets and links
                all_assets: dict[str, Asset] = {
                    str(a.id): a for a in asset_repo.list_all(include_fully_depreciated=False)
                }
                rows = []
                for charte in chartes:
                    if charte.project_id not in all_jh:
                        continue
                    links = asset_repo.get_links_by_project(charte.project_id)
                    alloc = allocator.compute_allocation(
                        project_id=charte.project_id,
                        period_month=through_month,
                        period_year=year,
                        all_jh=all_jh,
                        opex_total=opex_total,
                        asset_links=links,
                        assets=all_assets,
                        depreciation_calculator=calc,
                        taux_jh=charte.taux_jh,
                    )
                    profitable = alloc.montant_ht >= alloc.total_cost
                    rows.append({
                        "Projet":         charte.project_name,
                        "JH":             alloc.jh_allocated,
                        "Ratio":          f"{alloc.allocation_ratio:.1%}",
                        "OPEX alloué":    alloc.opex_allocated,
                        "CAPEX (amort.)": alloc.capex_allocated,
                        "Coût total":     alloc.total_cost,
                        "Facturé (JH)":   alloc.montant_ht,
                        "Résultat":       "🟢 Bénéfice" if profitable else "🔴 Perte",
                        "_profitable":    profitable,
                    })

                if rows:
                    display_cols = [c for c in rows[0] if not c.startswith("_")]
                    df_alloc = pd.DataFrame(rows)[display_cols]

                    def _color_result(val):
                        if "🟢" in str(val):
                            return "color: #1b5e20; font-weight: bold"
                        if "🔴" in str(val):
                            return "color: #b71c1c; font-weight: bold"
                        return ""

                    styled = df_alloc.style.map(_color_result, subset=["Résultat"])
                    st.dataframe(styled, width="stretch", hide_index=True)

                    # Summary metrics
                    total_cost_all  = sum(r["Coût total"]  for r in rows)
                    total_billed    = sum(r["Facturé (JH)"] for r in rows)
                    margin = total_billed - total_cost_all
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Coût total alloué", format_tnd(total_cost_all, 0))
                    m2.metric("Total facturé",     format_tnd(total_billed, 0))
                    m3.metric(
                        "Marge globale",
                        format_tnd(margin, 0),
                        delta=f"{margin / total_cost_all:.1%}" if total_cost_all else "—",
                        delta_color="normal" if margin >= 0 else "inverse",
                    )
                else:
                    st.info("Aucun projet avec des JH alloués sur la période.")
    except Exception as exc:
        st.warning(f"Allocation OPEX/CAPEX non disponible : {exc}")
