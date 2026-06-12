"""Suivi de Paiement — payment tracking, collections, overdue management."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app._backend import get_reconciler, get_repo, get_tracker, require_auth, status_badge
from src.models.enums import InvoiceDirection, InvoiceStatus
from src.models.invoice import InvoiceRecord

st.set_page_config(page_title="Suivi de Paiement — Invoice Agent", page_icon="💳", layout="wide")
require_auth()
st.title("💳 Suivi de Paiement")
st.caption("Track outstanding payables, receivables, and overdue invoices.")

if st.button("🔄 Refresh"):
    st.rerun()

st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────

try:
    repo       = get_repo()
    tracker    = get_tracker()
    reconciler = get_reconciler()
    pending_pay  = repo.get_pending_payment()
    pending_col  = repo.get_pending_collection()
    overdue      = repo.get_overdue()
except Exception as exc:
    st.error(f"Cannot connect to database: {exc}")
    st.stop()

# ── Summary KPIs ──────────────────────────────────────────────────────────────

k1, k2, k3 = st.columns(3)
k1.metric("Pending Payment",    len(pending_pay),
          delta=f"{sum(i.amount_ttc.value or 0 for i in pending_pay):,.0f} TND",
          delta_color="off")
k2.metric("Pending Collection", len(pending_col),
          delta=f"{sum(i.amount_ttc.value or 0 for i in pending_col):,.0f} TND",
          delta_color="off")
k3.metric("Overdue",            len(overdue),
          delta=f"{sum(i.amount_ttc.value or 0 for i in overdue):,.0f} TND",
          delta_color="inverse")

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_pay, tab_col, tab_over, tab_match = st.tabs([
    f"💸 Pending Payment ({len(pending_pay)})",
    f"📥 Pending Collection ({len(pending_col)})",
    f"🔴 Overdue ({len(overdue)})",
    "🔍 Match Payment",
])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _days_until_due(inv: InvoiceRecord) -> str | None:
    due = inv.due_date.value
    if due is None:
        return None
    today = datetime.now(tz=timezone.utc).date()
    delta = (due - today).days
    if delta < 0:
        return f"🔴 {-delta}d overdue"
    if delta == 0:
        return "🟠 Due today"
    if delta <= 7:
        return f"🟡 {delta}d left"
    return f"🟢 {delta}d left"


def _invoice_table_rows(invoices: list[InvoiceRecord]) -> pd.DataFrame:
    today = datetime.now(tz=timezone.utc).date()
    rows = []
    for inv in sorted(invoices, key=lambda x: x.due_date.value or today):
        due = inv.due_date.value
        rows.append({
            "Status":     status_badge(inv.status),
            "Direction":  inv.direction.value,
            "Issuer":     inv.issuer_name.value or "—",
            "Invoice #":  inv.invoice_number.value or "—",
            "Date":       str(inv.invoice_date.value) if inv.invoice_date.value else "—",
            "Due Date":   str(due) if due else "—",
            "TTC (TND)":  f"{inv.amount_ttc.value:,.3f}" if inv.amount_ttc.value else "—",
            "Due In":     _days_until_due(inv) or "—",
        })
    return pd.DataFrame(rows)


def _record_payment_form(inv: InvoiceRecord, action: str, form_prefix: str) -> None:
    """Render inline payment/collection recording form inside an expander."""
    issuer  = inv.issuer_name.value or str(inv.id)[:8]
    inv_num = inv.invoice_number.value or str(inv.id)[:8]
    ttc     = inv.amount_ttc.value or 0.0

    with st.expander(f"💳 Record {action} — {issuer} · {inv_num}"):
        with st.form(key=f"{form_prefix}_{inv.id}"):
            col_a, col_b = st.columns(2)
            amount    = col_a.number_input("Amount (TND)", value=ttc, min_value=0.01, step=0.001, format="%.3f")
            reference = col_b.text_input("Reference", placeholder="e.g. VIR-2024-0001")
            method    = st.selectbox("Payment method",
                                     ["bank_transfer", "cheque", "cash", "direct_debit", "other"])
            reviewer  = st.text_input("Recorded by", placeholder="Your name")
            submitted = st.form_submit_button(f"✅ Confirm {action}", type="primary")

        if submitted:
            if not reference.strip():
                st.error("Reference is required.")
            elif not reviewer.strip():
                st.error("'Recorded by' is required.")
            else:
                try:
                    if action == "Payment":
                        tracker.mark_paid(
                            invoice_id=inv.id,
                            payment_reference=reference.strip(),
                            amount=amount,
                            payment_method=method,
                        )
                    else:
                        tracker.mark_collected(
                            invoice_id=inv.id,
                            collection_reference=reference.strip(),
                            amount=amount,
                        )
                    st.success(f"✅ {action} recorded for {inv_num}.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Error: {exc}")


# ── Tab 1: Pending Payment ────────────────────────────────────────────────────

with tab_pay:
    if not pending_pay:
        st.success("No outstanding payables — all supplier invoices are settled.")
    else:
        st.subheader(f"{len(pending_pay)} supplier invoice(s) awaiting payment")
        st.dataframe(_invoice_table_rows(pending_pay), width="stretch", hide_index=True)
        st.divider()
        for inv in sorted(pending_pay, key=lambda x: x.due_date.value or datetime.now(tz=timezone.utc).date()):
            _record_payment_form(inv, "Payment", "pay")


# ── Tab 2: Pending Collection ─────────────────────────────────────────────────

with tab_col:
    if not pending_col:
        st.success("No outstanding receivables — all client invoices are collected.")
    else:
        st.subheader(f"{len(pending_col)} client invoice(s) awaiting collection")
        st.dataframe(_invoice_table_rows(pending_col), width="stretch", hide_index=True)
        st.divider()
        for inv in sorted(pending_col, key=lambda x: x.due_date.value or datetime.now(tz=timezone.utc).date()):
            _record_payment_form(inv, "Collection", "col")


# ── Tab 3: Overdue ────────────────────────────────────────────────────────────

with tab_over:
    if not overdue:
        st.success("No overdue invoices.")
    else:
        today = datetime.now(tz=timezone.utc).date()
        st.error(f"⚠️ {len(overdue)} overdue invoice(s) — immediate attention required.")

        rows = []
        for inv in sorted(overdue, key=lambda x: x.due_date.value or today):
            due   = inv.due_date.value
            delta = (today - due).days if due else 0
            rows.append({
                "Direction":  inv.direction.value,
                "Issuer":     inv.issuer_name.value or "—",
                "Invoice #":  inv.invoice_number.value or "—",
                "Due Date":   str(due) if due else "—",
                "Days Overdue": delta,
                "TTC (TND)":  f"{inv.amount_ttc.value:,.3f}" if inv.amount_ttc.value else "—",
            })
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
        st.divider()
        for inv in overdue:
            direction = inv.direction.value
            action = "Payment" if inv.direction == InvoiceDirection.SUPPLIER else "Collection"
            _record_payment_form(inv, action, "over")


# ── Tab 4: Match Payment ──────────────────────────────────────────────────────

with tab_match:
    st.subheader("Match an incoming payment to an invoice")
    st.caption("Provide any combination of fields — the reconciler will find the best match.")

    with st.form("match_form"):
        col1, col2 = st.columns(2)
        ref        = col1.text_input("Export / Payment reference", placeholder="e.g. VIR-2024-0001")
        inv_num    = col2.text_input("Invoice number",             placeholder="e.g. FAC-2024-0147")
        col3, col4 = st.columns(2)
        tax_id     = col3.text_input("Issuer MF",                  placeholder="e.g. 1234567/A/M/000")
        amount     = col4.number_input("Amount (TND)", min_value=0.0, step=0.001, format="%.3f")
        submitted  = st.form_submit_button("🔍 Find Match", type="primary")

    if submitted:
        payment_data = {}
        if ref.strip():       payment_data["reference"]      = ref.strip()
        if inv_num.strip():   payment_data["invoice_number"] = inv_num.strip()
        if tax_id.strip():    payment_data["issuer_tax_id"]  = tax_id.strip()
        if amount > 0:        payment_data["amount"]         = float(amount)

        if not payment_data:
            st.warning("Enter at least one search criterion.")
        else:
            try:
                match = reconciler.match_payment(payment_data)
                if match is None:
                    st.warning("No matching invoice found.")
                else:
                    st.success(f"✅ Match found — **{match.invoice_number.value or match.id}**")
                    col_a, col_b, col_c, col_d = st.columns(4)
                    col_a.metric("Status",    match.status.value)
                    col_b.metric("Issuer",    match.issuer_name.value or "—")
                    col_c.metric("TTC (TND)", f"{match.amount_ttc.value:,.3f}" if match.amount_ttc.value else "—")
                    col_d.metric("Due Date",  str(match.due_date.value) if match.due_date.value else "—")

                    if match.status in (InvoiceStatus.EXPORTED, InvoiceStatus.JOURNALED):
                        st.divider()
                        direction = match.direction
                        action = "Payment" if direction == InvoiceDirection.SUPPLIER else "Collection"
                        _record_payment_form(match, action, "match")
            except Exception as exc:
                st.error(f"Reconciler error: {exc}")
