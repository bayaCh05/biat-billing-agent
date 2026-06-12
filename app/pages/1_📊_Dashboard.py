"""Dashboard — KPIs, ageing analysis, invoice status overview."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app._backend import get_aggregator, get_config, get_ml_classifier, get_repo, get_stuck_invoices, require_auth, status_badge
from src.models.enums import InvoiceStatus

require_auth()
st.title("📊 Dashboard")

# ── Stuck invoice banner ──────────────────────────────────────────────────────
try:
    stuck = get_stuck_invoices()
    if stuck:
        cfg = get_config()
        timeout = cfg["agent"].get("stuck_invoice_timeout_minutes", 30)
        st.warning(
            f"⚠️ **{len(stuck)} invoice(s) stuck** in a transition state for more than "
            f"{timeout} minutes. Check the agent or review the invoice list."
        )
except Exception:
    pass
st.caption("Live overview of invoice processing activity.")

if st.button("🔄 Refresh"):
    st.cache_resource.clear()

st.divider()

# ── Fetch data ────────────────────────────────────────────────────────────────

try:
    snap = get_aggregator().snapshot()
    repo = get_repo()
except Exception as exc:
    st.error(f"Cannot connect to database: {exc}")
    st.stop()

# ── KPI cards ─────────────────────────────────────────────────────────────────

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total Invoices",    sum(snap.invoices_by_status.values()))
k2.metric("Auto-approved",     f"{snap.auto_approval_rate:.0%}")
k3.metric("Pending Review",    snap.flagged_count)
k4.metric("Overdue",           snap.overdue_count)
k5.metric("Total Payables",    f"{snap.total_payables:,.0f} TND")

st.divider()

# ── Charts ────────────────────────────────────────────────────────────────────

col_status, col_ageing = st.columns(2, gap="large")

with col_status:
    st.subheader("Invoices by Status")
    status_data = {k: v for k, v in snap.invoices_by_status.items() if v > 0}
    if status_data:
        import plotly.express as px
        fig = px.pie(
            values=list(status_data.values()),
            names=list(status_data.keys()),
            color_discrete_sequence=px.colors.qualitative.Set3,
            hole=0.4,
        )
        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=300,
                          legend=dict(orientation="h", yanchor="bottom", y=-0.3))
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No invoices yet.")

with col_ageing:
    st.subheader("Payables Ageing (TND)")
    ag = snap.payables_ageing
    ageing_data = {
        "Current":  ag.current,
        "1–30 d":   ag.days_1_30,
        "31–60 d":  ag.days_31_60,
        "61–90 d":  ag.days_61_90,
        "90+ d":    ag.over_90,
    }
    non_zero = {k: v for k, v in ageing_data.items() if v > 0}
    if non_zero:
        import plotly.express as px
        fig = px.bar(
            x=list(non_zero.keys()),
            y=list(non_zero.values()),
            color=list(non_zero.keys()),
            color_discrete_sequence=["#2ecc71", "#f39c12", "#e67e22", "#e74c3c", "#c0392b"],
            labels={"x": "Bucket", "y": "Amount (TND)"},
        )
        fig.update_layout(showlegend=False, margin=dict(t=0, b=0), height=300)
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No overdue payables.")

st.divider()

# ── Recent invoices ────────────────────────────────────────────────────────────

st.subheader("Recent Invoices")
try:
    all_invoices = []
    for status in [InvoiceStatus.JOURNALED, InvoiceStatus.EXPORTED, InvoiceStatus.FLAGGED,
                   InvoiceStatus.ERROR, InvoiceStatus.VALIDATED]:
        all_invoices.extend(repo.get_by_status(status))

    if all_invoices:
        import pandas as pd
        rows = []
        for inv in sorted(all_invoices, key=lambda x: x.updated_at, reverse=True)[:20]:
            rows.append({
                "Status":     inv.status.value,
                "Direction":  inv.direction.value,
                "Issuer":     inv.issuer_name.value or "—",
                "Invoice #":  inv.invoice_number.value or "—",
                "Date":       str(inv.invoice_date.value) if inv.invoice_date.value else "—",
                "TTC":        f"{inv.amount_ttc.value:,.3f}" if inv.amount_ttc.value else "—",
                "Flags":      sum(1 for f in inv.flags if not f.resolved),
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("No processed invoices yet. Upload one on the Home page.")
except Exception as exc:
    st.warning(f"Could not load recent invoices: {exc}")

st.divider()

# ── Classifier ────────────────────────────────────────────────────────────────

with st.expander("🤖 Classifier", expanded=False):
    clf = get_ml_classifier()
    if clf.is_trained():
        st.success(f"Model trained — {len(clf._classes)} categories: {', '.join(clf._classes)}")
        import os
        from pathlib import Path as _Path
        cfg = get_config()
        model_path = _Path(cfg["classification"].get("ml_model_path", "data/ml_model.joblib"))
        if model_path.exists():
            import datetime as _dt
            mtime = _dt.datetime.fromtimestamp(model_path.stat().st_mtime)
            st.caption(f"Last trained: {mtime.strftime('%Y-%m-%d %H:%M')}")
    else:
        st.info("Model not yet trained — approve invoices in the Review Queue to generate training data.")

    if st.button("🔄 Retrain classifier", type="primary"):
        with st.spinner("Retraining classifier on approved invoices…"):
            try:
                clf.retrain_from_repo(get_repo())
                if clf.is_trained():
                    st.success(f"Retrained on {len(clf._classes)} categories.")
                else:
                    st.warning("Not enough labeled invoices to train (need ≥5 across ≥2 categories). Approve more invoices first.")
            except Exception as exc:
                st.error(f"Retraining failed: {exc}")
