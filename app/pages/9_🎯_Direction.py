"""Tableau de bord Direction — vue consolidée de tous les modules."""
from __future__ import annotations

from datetime import date

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import streamlit as st

from app._backend import (
    require_auth,
    format_tnd,
    get_aggregator,
    get_budget_tracker,
    get_cost_analyzer,
    get_asset_repo,
    get_depreciation_calculator,
    get_client_invoice_repo,
    get_journal_repo,
    _budget_plan,
    _cost_catalog,
)
from src.models.client_invoice import ClientInvoiceStatus

require_auth()

st.title("🎯 Tableau de Bord Direction")
st.caption("Vue consolidée — Trésorerie · Budget · CAPEX · Facturation · Journal")

if st.button("🔄 Actualiser"):
    st.cache_resource.clear()
    st.rerun()

today = date.today()
current_year = today.year
through_month = today.month

# ── Load all data ─────────────────────────────────────────────────────────────

with st.spinner("Chargement des données…"):
    try:
        snap = get_aggregator().snapshot()
    except Exception:
        snap = None

    try:
        plan = _budget_plan()
        tracker = get_budget_tracker()
        budget_summary = tracker.summary(current_year, through_month)
        ytd_variances = tracker.ytd_variance(current_year, through_month)
    except Exception:
        budget_summary = None
        ytd_variances = []

    try:
        asset_repo = get_asset_repo()
        assets = asset_repo.list_all(include_fully_depreciated=False)
        total_brut = sum(a.acquisition_cost_ht for a in assets)
        total_vnc = sum(a.book_value_at(today) for a in assets)
        total_amort_cumul = total_brut - total_vnc
    except Exception:
        assets = []
        total_brut = total_vnc = total_amort_cumul = 0.0

    try:
        client_repo = get_client_invoice_repo()
        all_client_invoices = client_repo.list_all()
        client_sent = [i for i in all_client_invoices if i.status == ClientInvoiceStatus.SENT]
        client_paid = [i for i in all_client_invoices if i.status == ClientInvoiceStatus.PAID]
        total_factured = sum(i.amount_ttc for i in all_client_invoices
                             if i.status != ClientInvoiceStatus.CANCELLED)
        total_encaisse = sum(i.amount_ttc for i in client_paid)
    except Exception:
        client_sent = client_paid = []
        total_factured = total_encaisse = 0.0

    try:
        journal_repo = get_journal_repo()
        journal_entries = journal_repo.get_by_date_range(date(current_year, 1, 1), today)
        total_journal_debit = sum(
            sum(ln.debit or 0 for ln in e.lines) for e in journal_entries
        )
    except Exception:
        journal_entries = []
        total_journal_debit = 0.0

    try:
        catalog = _cost_catalog()
        catalog_labels = {e.id: e.label for e in catalog.all_entries()}
        analyzer = get_cost_analyzer()
    except Exception:
        catalog_labels = {}
        analyzer = None

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# Section 1 — KPI headline row
# ═════════════════════════════════════════════════════════════════════════════

st.subheader("Vue d'ensemble financière")

c1, c2, c3, c4, c5, c6 = st.columns(6)

with c1:
    payables = snap.total_payables if snap else 0.0
    st.metric("Dettes fournisseurs", format_tnd(payables, 0),
              help="Factures fournisseurs validées non encore payées")

with c2:
    receivables = snap.total_receivables if snap else 0.0
    st.metric("Créances clients", format_tnd(receivables, 0),
              help="Factures clients exportées non encore encaissées")

with c3:
    if budget_summary:
        total_actual = budget_summary.get("total_actual_ytd", 0) or 0
        if total_actual == 0:
            st.info("Aucune dépense enregistrée — écart non significatif.")
        else:
            variance = budget_summary["total_variance_ytd"]
            st.metric(
                "Écart budget YTD",
                f"{variance:+,.0f} TND",
                delta=f"{budget_summary['variance_pct']:+.1f}%",
                delta_color="inverse" if variance > 0 else "normal",
            )
    else:
        st.metric("Écart budget YTD", "—")

with c4:
    st.metric("VNC immobilisations", format_tnd(total_vnc, 0),
              help=f"Valeur brute : {format_tnd(total_brut, 0)} · Amort. cumulé : {format_tnd(total_amort_cumul, 0)}")

with c5:
    st.metric("Facturé clients YTD", format_tnd(total_factured, 0),
              delta=f"{total_encaisse:,.0f} encaissé",
              delta_color="normal")

with c6:
    approval_rate = snap.auto_approval_rate if snap else 0.0
    overdue = snap.overdue_count if snap else 0
    st.metric("Taux d'auto-approbation", f"{approval_rate:.0%}",
              delta=f"{overdue} en retard",
              delta_color="inverse" if overdue > 0 else "off")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# Section 2 — Budget vs Réel + Trésorerie
# ═════════════════════════════════════════════════════════════════════════════

col_budget, col_treasury = st.columns(2, gap="large")

with col_budget:
    st.subheader("Budget vs Réalisé YTD")
    _no_spend = not budget_summary or (budget_summary.get("total_actual_ytd") or 0) == 0
    if _no_spend:
        st.info("Aucune dépense enregistrée pour cet exercice — écart budgétaire non significatif.")
    elif budget_summary and ytd_variances:
        # Gauge chart
        consumed_pct = (
            budget_summary["total_actual_ytd"] / budget_summary["total_budget_ytd"] * 100
            if budget_summary["total_budget_ytd"] else 0
        )
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=budget_summary["total_actual_ytd"],
            delta={"reference": budget_summary["total_budget_ytd"], "valueformat": ",.0f"},
            number={"suffix": " TND", "valueformat": ",.0f"},
            gauge={
                "axis": {"range": [0, budget_summary["total_budget_ytd"] * 1.3]},
                "bar": {"color": "#003366"},
                "steps": [
                    {"range": [0, budget_summary["total_budget_ytd"] * 0.85], "color": "#e8f4f8"},
                    {"range": [budget_summary["total_budget_ytd"] * 0.85,
                               budget_summary["total_budget_ytd"]], "color": "#fff3cd"},
                ],
                "threshold": {
                    "line": {"color": "#FFB800", "width": 3},
                    "thickness": 0.75,
                    "value": budget_summary["total_budget_ytd"],
                },
            },
            title={"text": f"Réalisé vs Budget YTD ({through_month} mois)"},
        ))
        fig_gauge.update_layout(height=280, margin=dict(t=50, b=10))
        st.plotly_chart(fig_gauge, width="stretch")

        # Top 5 overruns
        over = sorted(
            [yv for yv in ytd_variances if yv.variance_ytd > 0],
            key=lambda yv: yv.variance_ytd, reverse=True,
        )[:5]
        if over:
            st.caption("Top dépassements")
            for yv in over:
                st.progress(
                    min(1.0, yv.actual_ytd / yv.budget_ytd if yv.budget_ytd else 1.0),
                    text=f"{yv.label[:30]} — **+{yv.variance_ytd:,.0f} TND** ({yv.variance_pct_ytd:+.0f}%)",
                )
        else:
            st.success("Aucun dépassement budgétaire.")
    elif not _no_spend:
        st.info("Données budget non disponibles.")

with col_treasury:
    st.subheader("Trésorerie & Ageing")
    if snap:
        ag = snap.payables_ageing
        month_names = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]

        # Ageing waterfall
        ageing = {
            "À échoir":  ag.current,
            "1–30 j":    ag.days_1_30,
            "31–60 j":   ag.days_31_60,
            "61–90 j":   ag.days_61_90,
            "90+ j":     ag.over_90,
        }
        colors = ["#2196f3", "#ff9800", "#f44336", "#b71c1c", "#4a0000"]
        fig_age = go.Figure(go.Bar(
            x=list(ageing.keys()),
            y=list(ageing.values()),
            marker_color=colors,
            text=[f"{v:,.0f}" for v in ageing.values()],
            textposition="outside",
        ))
        fig_age.update_layout(
            title="Ageing fournisseurs (TND)",
            xaxis_title="Tranche",
            yaxis_title="TND",
            height=260,
            showlegend=False,
            margin=dict(t=40, b=30),
        )
        st.plotly_chart(fig_age, width="stretch")

        # Quick stats
        r1, r2, r3 = st.columns(3)
        r1.metric("Factures en retard", snap.overdue_count)
        r2.metric("En attente de revue", snap.flagged_count)
        r3.metric("Créances", format_tnd(snap.total_receivables, 0))
    else:
        st.info("Données de trésorerie non disponibles.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# Section 3 — CAPEX + Facturation clients
# ═════════════════════════════════════════════════════════════════════════════

col_capex, col_billing = st.columns(2, gap="large")

with col_capex:
    st.subheader(f"Portefeuille CAPEX — {len(assets)} immobilisation(s)")
    if assets:
        calc = get_depreciation_calculator()

        # Stacked bar: VNC vs amort per asset
        asset_names = [a.designation[:22] for a in assets]
        vncs = [round(a.book_value_at(today), 0) for a in assets]
        amorts = [round(a.acquisition_cost_ht - a.book_value_at(today), 0) for a in assets]

        fig_capex = go.Figure()
        fig_capex.add_trace(go.Bar(
            name="Amort. cumulé",
            x=asset_names,
            y=amorts,
            marker_color="#FFB800",
        ))
        fig_capex.add_trace(go.Bar(
            name="VNC",
            x=asset_names,
            y=vncs,
            marker_color="#003366",
        ))
        fig_capex.update_layout(
            barmode="stack",
            height=300,
            xaxis_tickangle=-30,
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=40, b=80),
            yaxis_title="TND",
        )
        st.plotly_chart(fig_capex, width="stretch")

        # Annual depreciation for current year
        annual_dotation = 0.0
        for a in assets:
            sched = calc.schedule(
                asset_id=str(a.id),
                designation=a.designation,
                acquisition_cost_ht=a.acquisition_cost_ht,
                acquisition_date=a.acquisition_date,
                useful_life_years=a.useful_life_years,
                method=a.depreciation_method,
            )
            annual_dotation += sched.annual_depreciation_for_year(current_year)

        st.caption(
            f"Dotation annuelle {current_year} : **{format_tnd(annual_dotation)}** · "
            f"VNC totale : **{format_tnd(total_vnc)}**"
        )
    else:
        st.info("Aucune immobilisation enregistrée.")

with col_billing:
    st.subheader("Facturation clients")
    if all_client_invoices:
        # Status breakdown
        status_counts = {
            "Brouillon":   sum(1 for i in all_client_invoices if i.status == ClientInvoiceStatus.DRAFT),
            "Envoyée":     sum(1 for i in all_client_invoices if i.status == ClientInvoiceStatus.SENT),
            "Payée":       sum(1 for i in all_client_invoices if i.status == ClientInvoiceStatus.PAID),
            "Annulée":     sum(1 for i in all_client_invoices if i.status == ClientInvoiceStatus.CANCELLED),
        }
        non_zero = {k: v for k, v in status_counts.items() if v > 0}

        if non_zero:
            fig_billing = px.pie(
                values=list(non_zero.values()),
                names=list(non_zero.keys()),
                color_discrete_map={
                    "Brouillon": "#90caf9",
                    "Envoyée":   "#FFB800",
                    "Payée":     "#003366",
                    "Annulée":   "#e0e0e0",
                },
                hole=0.45,
            )
            fig_billing.update_traces(textposition="inside", textinfo="percent+label")
            fig_billing.update_layout(
                height=280,
                showlegend=False,
                margin=dict(t=10, b=10),
            )
            st.plotly_chart(fig_billing, width="stretch")

        r1, r2, r3 = st.columns(3)
        r1.metric("Total facturé", format_tnd(total_factured, 0))
        r2.metric("Encaissé", format_tnd(total_encaisse, 0))
        pending = total_factured - total_encaisse
        r3.metric("En attente", format_tnd(pending, 0),
                  delta_color="inverse" if pending > 0 else "off")

        # Recent client invoices table
        if all_client_invoices:
            recent = sorted(
                all_client_invoices,
                key=lambda i: i.invoice_date,
                reverse=True,
            )[:5]
            rows = [
                {
                    "N°":         i.invoice_number,
                    "Client":     i.client_name,
                    "Date":       i.invoice_date.strftime("%d/%m/%Y"),
                    "TTC (TND)":  f"{i.amount_ttc:,.0f}",
                    "Statut":     i.status.value,
                }
                for i in recent
            ]
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("Aucune facture client enregistrée.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# Section 4 — Top spending + Journal activity
# ═════════════════════════════════════════════════════════════════════════════

col_spending, col_journal = st.columns(2, gap="large")

with col_spending:
    st.subheader(f"Top dépenses YTD {current_year}")
    if analyzer and catalog_labels:
        top = analyzer.top_categories(
            year=current_year,
            through_month=through_month,
            top_n=8,
            catalog_labels=catalog_labels,
        )
        if top:
            fig_top = go.Figure(go.Bar(
                x=[t["total"] for t in reversed(top)],
                y=[t["label"][:28] for t in reversed(top)],
                orientation="h",
                marker_color="#003366",
                text=[f"{t['total']:,.0f}" for t in reversed(top)],
                textposition="outside",
            ))
            fig_top.update_layout(
                height=320,
                xaxis_title="Montant HT (TND)",
                margin=dict(t=10, b=10, l=180),
                showlegend=False,
            )
            st.plotly_chart(fig_top, width="stretch")
        else:
            st.info("Aucune dépense enregistrée pour l'exercice en cours.")
    else:
        st.info("Données non disponibles.")

with col_journal:
    st.subheader(f"Activité journal {current_year}")
    if journal_entries:
        # Group entries by month
        by_month: dict[int, int] = {}
        by_month_debit: dict[int, float] = {}
        for e in journal_entries:
            m = e.date_ecriture.month
            by_month[m] = by_month.get(m, 0) + 1
            by_month_debit[m] = by_month_debit.get(m, 0) + sum(ln.debit or 0 for ln in e.lines)

        month_names_short = ["Jan","Fév","Mar","Avr","Mai","Jun","Jul","Aoû","Sep","Oct","Nov","Déc"]
        months = sorted(by_month.keys())

        fig_journal = go.Figure()
        fig_journal.add_trace(go.Bar(
            x=[month_names_short[m - 1] for m in months],
            y=[by_month_debit.get(m, 0) for m in months],
            name="Montant débité (TND)",
            marker_color="#003366",
            yaxis="y",
        ))
        fig_journal.add_trace(go.Scatter(
            x=[month_names_short[m - 1] for m in months],
            y=[by_month.get(m, 0) for m in months],
            name="Nb écritures",
            mode="lines+markers",
            line=dict(color="#FFB800", width=2),
            yaxis="y2",
        ))
        fig_journal.update_layout(
            height=300,
            yaxis=dict(title="Montant (TND)"),
            yaxis2=dict(title="Nb écritures", overlaying="y", side="right"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=40, b=20),
        )
        st.plotly_chart(fig_journal, width="stretch")

        r1, r2 = st.columns(2)
        r1.metric("Écritures YTD", len(journal_entries))
        r2.metric("Total débité YTD", format_tnd(total_journal_debit, 0))
    else:
        st.info("Aucune écriture comptable pour l'exercice en cours.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# Section 5 — Alerts panel
# ═════════════════════════════════════════════════════════════════════════════

st.subheader("🚨 Alertes actives")

alerts: list[tuple[str, str, str]] = []  # (severity, icon, message)

if snap and snap.overdue_count > 0:
    alerts.append(("error", "🔴", f"{snap.overdue_count} facture(s) fournisseur en retard de paiement"))

if snap and snap.flagged_count > 0:
    alerts.append(("warning", "⚠️", f"{snap.flagged_count} facture(s) en attente de revue humaine"))

if budget_summary:
    if budget_summary["lines_over_budget"] > 0:
        alerts.append(("error", "🔴",
            f"{budget_summary['lines_over_budget']} catégorie(s) en dépassement budgétaire"))
    if budget_summary["lines_warning"] > 0:
        alerts.append(("warning", "⚠️",
            f"{budget_summary['lines_warning']} catégorie(s) en alerte budget (>15% d'écart)"))
    if budget_summary["variance_pct"] > 10:
        alerts.append(("error", "🔴",
            f"Dépassement global {budget_summary['variance_pct']:+.1f}% sur le budget YTD"))

if client_sent:
    alerts.append(("warning", "⚠️",
        f"{len(client_sent)} facture(s) client envoyée(s) mais non encore encaissée(s) "
        f"({format_tnd(sum(i.amount_ttc for i in client_sent), 0)})"))

if assets:
    expiring_soon = [
        a for a in assets
        if 0 < (a.acquisition_date.year + a.useful_life_years - current_year) <= 1
    ]
    if expiring_soon:
        alerts.append(("warning", "⚠️",
            f"{len(expiring_soon)} immobilisation(s) arrivent en fin d'amortissement cette année"))

if not alerts:
    st.success("Aucune alerte active. Tous les indicateurs sont dans les normes.")
else:
    for severity, icon, msg in alerts:
        if severity == "error":
            st.error(f"{icon} {msg}")
        else:
            st.warning(f"{icon} {msg}")

# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()

footer_col, dl_col = st.columns([6, 1])
footer_col.caption(
    f"Dernière mise à jour : **{today.strftime('%d/%m/%Y')}** · "
    f"Exercice **{current_year}** · {through_month} mois analysés · "
    "BIAT IT — Système de gestion de la facturation v3"
)
try:
    import pathlib
    arch_path = pathlib.Path("ARCHITECTURE.md")
    if arch_path.exists():
        dl_col.download_button(
            "📄 Architecture",
            data=arch_path.read_text(encoding="utf-8"),
            file_name="ARCHITECTURE.md",
            mime="text/markdown",
            help="Télécharger la documentation technique",
        )
except Exception:
    pass
