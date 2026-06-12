"""Invoice List — browse and filter all processed invoices."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app._backend import conf_icon, get_repo, render_flags, render_invoice_fields, require_auth
from src.models.enums import InvoiceDirection, InvoiceStatus

st.set_page_config(page_title="Invoices — Invoice Agent", page_icon="📋", layout="wide")
require_auth()
st.title("📋 All Invoices")
st.caption("Browse, filter and inspect every processed invoice.")

if st.button("🔄 Refresh"):
    st.rerun()

st.divider()

# ── Filters ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("Filters")
    status_filter = st.multiselect(
        "Status",
        options=[s.value for s in InvoiceStatus],
        default=[],
        placeholder="All statuses",
    )
    direction_filter = st.multiselect(
        "Direction",
        options=[d.value for d in InvoiceDirection],
        default=[],
        placeholder="All directions",
    )
    search = st.text_input("Search issuer / invoice #", placeholder="e.g. Acme, INV-2024")

# ── Load invoices ─────────────────────────────────────────────────────────────

try:
    repo = get_repo()
    all_invoices = []
    statuses_to_load = (
        [InvoiceStatus(s) for s in status_filter]
        if status_filter
        else list(InvoiceStatus)
    )
    for status in statuses_to_load:
        all_invoices.extend(repo.get_by_status(status))
except Exception as exc:
    st.error(f"Cannot connect to database: {exc}")
    st.stop()

# Apply direction filter
if direction_filter:
    all_invoices = [i for i in all_invoices if i.direction.value in direction_filter]

# Apply search filter
if search:
    q = search.lower()
    all_invoices = [
        i for i in all_invoices
        if q in (i.issuer_name.value or "").lower()
        or q in (i.invoice_number.value or "").lower()
    ]

# Sort newest first
all_invoices.sort(key=lambda x: x.updated_at, reverse=True)

if not all_invoices:
    st.info("No invoices match the current filters.")
    st.stop()

st.caption(f"Showing **{len(all_invoices)}** invoice(s).")

# ── Summary table ─────────────────────────────────────────────────────────────

rows = []
for inv in all_invoices:
    open_flags = sum(1 for f in inv.flags if not f.resolved)
    rows.append({
        "Status":     inv.status.value,
        "Direction":  inv.direction.value,
        "Issuer":     inv.issuer_name.value or "—",
        "Invoice #":  inv.invoice_number.value or "—",
        "Date":       str(inv.invoice_date.value) if inv.invoice_date.value else "—",
        "TTC":        f"{inv.amount_ttc.value:,.3f}" if inv.amount_ttc.value else "—",
        "Confidence": conf_icon(inv.amount_ttc.confidence),
        "Flags":      open_flags,
        "Method":     inv.extraction_method.value if inv.extraction_method else "—",
        "ID":         str(inv.id),
    })

df = pd.DataFrame(rows)

# Allow selecting a row to inspect details
event = st.dataframe(
    df,
    width="stretch",
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    column_config={
        "ID":         st.column_config.TextColumn(width="small"),
        "Confidence": st.column_config.TextColumn(width="small"),
        "Flags":      st.column_config.NumberColumn(width="small"),
    },
)

# ── Detail panel ──────────────────────────────────────────────────────────────

selected = event.selection.rows if hasattr(event, "selection") else []
if selected:
    idx = selected[0]
    inv = all_invoices[idx]
    st.divider()
    st.subheader(f"Invoice detail — {inv.invoice_number.value or str(inv.id)[:8]}")

    col_meta, col_acct = st.columns(2)
    with col_meta:
        st.metric("Status",    inv.status.value)
        st.metric("Direction", inv.direction.value)
        st.metric("Currency",  inv.currency)
    with col_acct:
        st.metric("Accounting Code",
                  f"{inv.accounting_compte} — {inv.accounting_label}"
                  if inv.accounting_compte else "—")
        st.metric("Method",
                  inv.extraction_method.value if inv.extraction_method else "—")
        st.metric("Retry count", inv.retry_count)

    tab_f, tab_fl, tab_li = st.tabs(["Fields", "Flags", "Line Items"])
    with tab_f:
        render_invoice_fields(inv)
    with tab_fl:
        render_flags(inv)
    with tab_li:
        if inv.line_items:
            st.dataframe(pd.DataFrame([{
                "#": li.line_number, "Description": li.description or "—",
                "Qty": li.quantity, "Unit Price": li.unit_price,
                "Total": li.line_total, "TVA %": li.tva_rate,
            } for li in inv.line_items]), width="stretch", hide_index=True)
        else:
            st.info("No line items.")
