"""KPI Dashboard — Indicateurs clés de performance BIAT IT."""
from __future__ import annotations

import statistics
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app._backend import (
    _cost_catalog,
    format_tnd,
    get_aggregator,
    get_budget_tracker,
    get_cost_analyzer,
    get_journal_repo,
    get_ml_classifier,
    get_repo,
    require_auth,
)
from src.models.enums import FlagType, InvoiceStatus

require_auth()

st.title("📈 KPI Dashboard")
st.caption("Indicateurs clés de performance — Exercice 2026")

if st.button("🔄 Actualiser"):
    st.cache_resource.clear()
    st.rerun()

today      = date.today()
year       = today.year
month      = today.month
year_start = date(year, 1, 1)

# ── Load all data ─────────────────────────────────────────────────────────────

with st.spinner("Chargement…"):
    repo         = get_repo()
    journal_repo = get_journal_repo()

    try:
        snap = get_aggregator().snapshot()
    except Exception:
        snap = None

    try:
        tracker        = get_budget_tracker()
        budget_summary = tracker.summary(year, month)
        ytd_variances  = tracker.ytd_variance(year, month)
    except Exception:
        budget_summary = None
        ytd_variances  = []

    try:
        analyzer      = get_cost_analyzer()
        catalog       = _cost_catalog()
        catalog_labels = {e.id: e.label for e in catalog.all_entries()}
    except Exception:
        analyzer      = None
        catalog_labels = {}

    try:
        all_invoices = repo.list_all()
    except Exception:
        all_invoices = []

    try:
        journal_entries = journal_repo.get_by_date_range(year_start, today)
    except Exception:
        journal_entries = []

    try:
        status_counts = repo.count_by_status()
    except Exception:
        status_counts = {}

    try:
        clf = get_ml_classifier()
    except Exception:
        clf = None

# ═════════════════════════════════════════════════════════════════════════════
# Summary row — 4 top-level KPIs
# ═════════════════════════════════════════════════════════════════════════════

TERMINAL_OK = [
    InvoiceStatus.EXPORTED, InvoiceStatus.JOURNALED,
    InvoiceStatus.PAID,     InvoiceStatus.COLLECTED,
]
try:
    _total_done, _auto_done = repo.count_auto_approved(TERMINAL_OK)
except Exception:
    _total_done, _auto_done = 0, 0

total_invoices = _total_done
auto_rate      = (_auto_done / _total_done) if _total_done else 0.0
total_spend    = budget_summary["total_actual_ytd"] if budget_summary else 0.0
budget_pct     = (
    total_spend / budget_summary["total_budget_ytd"] * 100
    if budget_summary and budget_summary.get("total_budget_ytd")
    else 0.0
)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Factures traitées",        total_invoices)
col2.metric("Taux d'auto-approbation",  f"{auto_rate:.1%}")
col3.metric("Dépenses YTD",             format_tnd(total_spend))
col4.metric("Consommation budget",      f"{budget_pct:.1f}%")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# KPI 1 — Invoice processing rate
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("KPI 1 — Taux de traitement automatique", expanded=True):
    try:
        total_done = _total_done
        auto_done  = _auto_done
        human_done = total_done - auto_done
        errors = sum(
            status_counts.get(s.value, 0)
            for s in (InvoiceStatus.ERROR, InvoiceStatus.EXTRACTION_FAILED, InvoiceStatus.REJECTED)
        )
        rate = auto_done / total_done * 100 if total_done else 0.0

        m1, m2 = st.columns(2)
        m1.metric("Taux d'auto-approbation", f"{rate:.1f}%")
        m2.metric("Factures traitées",        total_done)

        if total_done:
            fig = go.Figure(go.Bar(
                x=[auto_done, human_done, errors],
                y=["Auto-approuvées", "Examinées (humain)", "Erreurs"],
                orientation="h",
                marker_color=["#003366", "#FFB800", "#e53935"],
                text=[str(auto_done), str(human_done), str(errors)],
                textposition="auto",
            ))
            fig.update_layout(
                height=200,
                margin=dict(t=10, b=10, l=10, r=10),
                showlegend=False,
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Données insuffisantes — aucune facture en statut terminal.")
    except Exception as exc:
        st.info(f"Données insuffisantes : {exc}")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# KPI 2 — Budget consumption by category
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("KPI 2 — Consommation budgétaire par catégorie", expanded=True):
    if ytd_variances:
        has_spend = any(yv.actual_ytd > 0 for yv in ytd_variances)
        if not has_spend:
            st.info("Aucune dépense enregistrée — consommation budgétaire non disponible.")
        else:
            top = sorted(
                [yv for yv in ytd_variances if yv.budget_ytd > 0],
                key=lambda yv: yv.budget_ytd, reverse=True,
            )[:12]
            labels   = [yv.label[:28] for yv in top]
            budgets  = [yv.budget_ytd  for yv in top]
            actuals  = [yv.actual_ytd  for yv in top]
            # Red if over-budget by more than 20%, amber otherwise
            act_colors = [
                "#e53935" if yv.variance_pct_ytd < -20 else "#FFB800"
                for yv in top
            ]

            fig = go.Figure()
            fig.add_trace(go.Bar(
                name="Budget alloué",
                y=labels, x=budgets,
                orientation="h",
                marker_color="rgba(0,51,102,0.35)",
                width=0.6,
            ))
            fig.add_trace(go.Bar(
                name="Réalisé",
                y=labels, x=actuals,
                orientation="h",
                marker_color=act_colors,
                width=0.4,
            ))
            fig.update_layout(
                barmode="overlay",
                height=max(300, len(top) * 28),
                margin=dict(t=10, b=10, l=200, r=10),
                xaxis_title="TND",
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig, width="stretch")
    else:
        st.info("Données insuffisantes.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# KPI 3 — Average processing time
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("KPI 3 — Délai moyen de traitement", expanded=True):
    DONE = {
        InvoiceStatus.EXPORTED, InvoiceStatus.JOURNALED,
        InvoiceStatus.PAID,     InvoiceStatus.COLLECTED,
    }
    finished = [
        inv for inv in all_invoices
        if inv.status in DONE
        and inv.received_at is not None
        and inv.updated_at is not None
    ]

    if finished:
        times = [
            max(0.0, (inv.updated_at - inv.received_at).total_seconds() / 60)
            for inv in finished
        ]
        avg_min = sum(times) / len(times)
        med_min = statistics.median(times)

        m1, m2, m3 = st.columns(3)
        m1.metric("Délai moyen",      f"{avg_min:.0f} min")
        m2.metric("Délai médian",     f"{med_min:.0f} min")
        m3.metric("Factures mesurées", len(finished))

        fig = go.Figure(go.Histogram(
            x=times, nbinsx=20, marker_color="#003366",
        ))
        fig.update_layout(
            height=300,
            xaxis_title="Délai (minutes)",
            yaxis_title="Nombre de factures",
            margin=dict(t=10, b=30),
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Données insuffisantes — aucune facture en statut terminal.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# KPI 4 — Top 5 cost categories YTD
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("KPI 4 — Top 5 catégories de dépenses YTD", expanded=True):
    if analyzer and catalog_labels:
        try:
            top5 = analyzer.top_categories(
                year=year, through_month=month,
                top_n=5, catalog_labels=catalog_labels,
            )
            if top5:
                cat_labels = [t["label"][:30] for t in top5]
                cat_totals = [t["total"]       for t in top5]
                cat_texts  = [format_tnd(t['total']) for t in top5]

                fig = go.Figure(go.Bar(
                    x=cat_labels, y=cat_totals,
                    marker_color="#003366",
                    text=cat_texts, textposition="outside",
                ))
                fig.update_layout(
                    height=300,
                    yaxis_title="Montant HT (TND)",
                    margin=dict(t=30, b=80),
                    xaxis_tickangle=-30,
                )
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("Aucune dépense enregistrée pour l'exercice en cours.")
        except Exception:
            st.info("Données insuffisantes.")
    else:
        st.info("Données insuffisantes.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# KPI 5 — CAPEX vs OPEX ratio
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("KPI 5 — Répartition CAPEX / OPEX", expanded=True):
    capex = sum(
        inv.amount_ht.value or 0.0
        for inv in all_invoices
        if inv.accounting_compte
        and inv.accounting_compte.startswith("2")
        and inv.amount_ht.value is not None
    )
    opex = sum(
        inv.amount_ht.value or 0.0
        for inv in all_invoices
        if inv.accounting_compte
        and inv.accounting_compte.startswith("6")
        and inv.amount_ht.value is not None
    )
    grand = capex + opex

    if grand > 0:
        fig = px.pie(
            values=[capex, opex],
            names=["CAPEX", "OPEX"],
            color_discrete_map={"CAPEX": "#1A3A5C", "OPEX": "#F0A500"},
            hole=0.5,
        )
        fig.update_traces(textinfo="percent+label")
        fig.update_layout(height=300, margin=dict(t=20, b=20))
        st.plotly_chart(fig, width="stretch")

        c1, c2 = st.columns(2)
        c1.metric("CAPEX total", format_tnd(capex))
        c2.metric("OPEX total",  format_tnd(opex))
    else:
        st.info("Données insuffisantes — aucune facture classifiée avec compte comptable.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# KPI 6 — TVA recoverability
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("KPI 6 — Taux de récupération TVA", expanded=True):
    tva_ded = 0.0
    tva_col = 0.0
    for e in journal_entries:
        for ln in e.lines:
            if ln.compte == "4366" and ln.debit:
                tva_ded += ln.debit
            elif ln.compte == "4367" and ln.credit:
                tva_col += ln.credit
    net = tva_ded - tva_col

    c1, c2, c3 = st.columns(3)
    c1.metric("TVA déductible",    format_tnd(tva_ded),
              help="Compte 4366 — TVA récupérable sur achats fournisseurs")
    c2.metric("TVA collectée",     format_tnd(tva_col),
              help="Compte 4367 — TVA due sur ventes clients")
    c3.metric(
        "Position TVA nette",
        format_tnd(net),
        delta="À récupérer" if net > 0 else "À reverser",
        delta_color="normal" if net > 0 else "inverse",
    )

    if tva_ded == 0 and tva_col == 0:
        st.info("Aucune écriture TVA pour l'exercice en cours.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# KPI 7 — Overdue invoice ageing
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("KPI 7 — Ageing des factures en retard", expanded=True):
    if snap:
        ag = snap.payables_ageing
        buckets = {
            "0–30 j":  ag.days_1_30,
            "31–60 j": ag.days_31_60,
            "61–90 j": ag.days_61_90,
            "90+ j":   ag.over_90,
        }
        colors = ["#4caf50", "#ff9800", "#f44336", "#7b0000"]

        if ag.total_overdue > 0:
            fig = go.Figure(go.Bar(
                x=list(buckets.keys()),
                y=list(buckets.values()),
                marker_color=colors,
                text=[f"{v:,.2f}" for v in buckets.values()],
                textposition="outside",
            ))
            fig.update_layout(
                height=300,
                xaxis_title="Tranche",
                yaxis_title="TND",
                margin=dict(t=10, b=30),
                showlegend=False,
            )
            st.plotly_chart(fig, width="stretch")
            st.caption(f"Total en retard : **{format_tnd(ag.total_overdue)}**")
        else:
            st.success("✅ Aucune facture en retard de paiement.")
    else:
        st.info("Données insuffisantes.")

st.divider()

# ═════════════════════════════════════════════════════════════════════════════
# KPI 8 — ML classifier performance
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("KPI 8 — Performance du classificateur ML", expanded=True):
    if clf is not None:
        # Last training date — derived from model file mtime
        model_path = clf._path
        if clf.is_trained() and model_path.exists():
            mtime = datetime.fromtimestamp(model_path.stat().st_mtime)
            last_trained = mtime.strftime("%d/%m/%Y %H:%M")
            n_classes = len(clf._classes)
        else:
            last_trained = "Jamais"
            n_classes    = 0

        # Training sample count — labeled invoices in DB (proxy, no stored count)
        TRAIN_OK = {
            InvoiceStatus.VALIDATED, InvoiceStatus.EXPORTED,
            InvoiceStatus.JOURNALED, InvoiceStatus.PAID,
        }
        n_samples = sum(
            1 for inv in all_invoices
            if inv.status in TRAIN_OK and inv.cost_catalog_id
        )

        # Classification accuracy — invoices without CATALOG_NO_MATCH flag
        # (exclude invoices still in early pipeline stages)
        EARLY = {InvoiceStatus.RECEIVED, InvoiceStatus.EXTRACTING, InvoiceStatus.EXTRACTED}
        classifiable = [inv for inv in all_invoices if inv.status not in EARLY]
        classified_ok = [
            inv for inv in classifiable
            if not any(f.flag_type == FlagType.CATALOG_NO_MATCH for f in inv.flags)
        ]
        accuracy = len(classified_ok) / len(classifiable) * 100 if classifiable else 0.0

        m1, m2, m3 = st.columns(3)
        m1.metric("Dernière mise à jour",       last_trained)
        m2.metric("Échantillons d'entraînement", n_samples)
        m3.metric("Taux de classification",     f"{accuracy:.1f}%")

        if clf.is_trained():
            preview = clf._classes[:8]
            suffix  = " …" if len(clf._classes) > 8 else ""
            st.caption(f"Catégories : {', '.join(preview)}{suffix}")
        else:
            st.warning(
                "Modèle non entraîné — approuvez des factures dans la "
                "file de révision pour générer des données d'entraînement."
            )

        if st.button("🔄 Réentraîner le classificateur", key="kpi8_retrain"):
            with st.spinner("Entraînement en cours…"):
                try:
                    clf.retrain_from_repo(repo)
                    if clf.is_trained():
                        st.success(
                            f"Modèle réentraîné — "
                            f"{len(clf._classes)} catégories."
                        )
                    else:
                        st.warning(
                            "Données insuffisantes — au moins 5 factures "
                            "approuvées sur ≥2 catégories sont requises."
                        )
                except Exception as exc:
                    st.error(f"Erreur : {exc}")
    else:
        st.info("Données insuffisantes — classificateur non disponible.")

# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    f"Exercice **{year}** · {month} mois analysés · "
    "BIAT IT — Système de gestion de la facturation v3"
)
