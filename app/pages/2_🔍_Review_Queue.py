"""Review Queue — human-in-the-loop approval of flagged and escalated invoices."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app._backend import get_config, get_ml_classifier, get_repo, get_tracker, render_flags, render_invoice_fields, require_auth
from src.models.enums import FlagSeverity, FlagType, InvoiceStatus
from src.models.invoice import InvoiceRecord

require_auth()
st.title("🔍 Review Queue")
st.caption("Flagged and escalated invoices awaiting human review.")

if st.button("🔄 Refresh"):
    st.rerun()

st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────

try:
    repo      = get_repo()
    tracker   = get_tracker()
    flagged   = repo.get_flagged()
    escalated = repo.get_by_status(InvoiceStatus.ESCALATED)
    error_invoices = repo.get_by_status(InvoiceStatus.ERROR)
except Exception as exc:
    st.error(f"Cannot connect to database: {exc}")
    st.stop()

# ── Rejected non-invoice files ────────────────────────────────────────────────

rejected = [
    inv for inv in error_invoices
    if any(f.flag_type == FlagType.NOT_AN_INVOICE for f in inv.flags)
]

if rejected:
    st.error(
        f"🚫 **{len(rejected)} fichier(s) rejeté(s)** — "
        "non reconnu(s) comme facture"
    )
    for inv in rejected:
        flag = next(
            f for f in inv.flags if f.flag_type == FlagType.NOT_AN_INVOICE
        )
        file_label = Path(inv.raw_file_path).name if inv.raw_file_path else str(inv.id)[:8]
        st.markdown(f"- `{file_label}` — {flag.message}")
    st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_flag, tab_esc = st.tabs([
    f"🟠 Flagged ({len(flagged)})",
    f"⬆️ Escalated ({len(escalated)})",
])


# ── Shared invoice renderer ───────────────────────────────────────────────────

def _render_invoice(inv: InvoiceRecord, allow_escalate: bool = True) -> None:
    open_errors   = sum(1 for f in inv.flags if not f.resolved and f.severity == FlagSeverity.ERROR)
    open_warnings = sum(1 for f in inv.flags if not f.resolved and f.severity == FlagSeverity.WARNING)
    issuer  = inv.issuer_name.value or "Unknown issuer"
    inv_num = inv.invoice_number.value or str(inv.id)[:8]
    ttc     = f"{inv.amount_ttc.value:,.3f} {inv.currency}" if inv.amount_ttc.value else "—"

    label = (f"🔴 {open_errors} error(s)" if open_errors else "") + \
            (f"  🟡 {open_warnings} warning(s)" if open_warnings else "")

    with st.expander(f"**{issuer}** — {inv_num} — {ttc}   {label}", expanded=False):
        tab_fields, tab_flags = st.tabs(["Extracted Fields", "Flags"])

        with tab_fields:
            render_invoice_fields(inv)
            if inv.line_items:
                st.dataframe(pd.DataFrame([{
                    "#": li.line_number, "Description": li.description or "—",
                    "Qty": li.quantity, "Unit Price": li.unit_price,
                    "Total": li.line_total, "TVA %": li.tva_rate,
                } for li in inv.line_items]), width="stretch", hide_index=True)

        with tab_flags:
            render_flags(inv)

        st.divider()

        with st.form(key=f"action_{inv.id}"):
            reviewer = st.text_input("Reviewer name", placeholder="Your name")
            notes    = st.text_area("Notes / reason", placeholder="Optional notes")

            if allow_escalate:
                col1, col2, col3 = st.columns(3)
                approved  = col1.form_submit_button("✅ Approve",   width="stretch", type="primary")
                rejected  = col2.form_submit_button("❌ Reject",    width="stretch")
                escalated_btn = col3.form_submit_button("⬆️ Escalate", width="stretch")
            else:
                col1, col2, col3 = st.columns(3)
                approved      = col1.form_submit_button("✅ Approve",     width="stretch", type="primary")
                rejected      = col2.form_submit_button("❌ Reject",      width="stretch")
                de_escalated  = col3.form_submit_button("↩️ De-escalate", width="stretch")
                escalated_btn = False

        if approved:
            if not reviewer.strip():
                st.error("Reviewer name is required.")
            else:
                try:
                    # Temporarily set FLAGGED so approve_flagged() accepts it
                    if inv.status == InvoiceStatus.ESCALATED:
                        inv.status = InvoiceStatus.FLAGGED
                        repo.save(inv)
                    tracker.approve_flagged(inv.id, reviewer=reviewer.strip(), notes=notes or None)
                    st.success(f"✅ Invoice {inv_num} approved by {reviewer}.")
                    # Trigger ML retraining if configured
                    cfg = get_config()
                    if cfg.get("ml", {}).get("auto_retrain_on_approval", True):
                        with st.spinner("Retraining classifier…"):
                            try:
                                clf = get_ml_classifier()
                                clf.retrain_from_repo(get_repo())
                            except Exception:
                                pass  # retraining failure must not block the approval flow
                    st.rerun()
                except Exception as exc:
                    st.error(f"Error: {exc}")

        elif rejected:
            reason = notes.strip() or "Rejected by reviewer"
            if not reviewer.strip():
                st.error("Reviewer name is required.")
            else:
                try:
                    tracker.reject_invoice(inv.id, reviewer=reviewer.strip(), reason=reason)
                    st.error(f"❌ Invoice {inv_num} rejected.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Error: {exc}")

        elif escalated_btn:
            if not reviewer.strip():
                st.error("Reviewer name is required.")
            else:
                try:
                    inv.status = InvoiceStatus.ESCALATED
                    inv.reviewed_by = reviewer.strip()
                    inv.human_review_notes = notes or None
                    repo.save(inv)
                    st.warning(f"⬆️ Invoice {inv_num} escalated.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Error: {exc}")

        elif not allow_escalate and de_escalated:
            if not reviewer.strip():
                st.error("Reviewer name is required.")
            else:
                try:
                    inv.status = InvoiceStatus.FLAGGED
                    inv.reviewed_by = reviewer.strip()
                    inv.human_review_notes = notes or None
                    repo.save(inv)
                    st.info(f"↩️ Invoice {inv_num} returned to review queue.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Error: {exc}")


# ── Tab 1: Flagged ────────────────────────────────────────────────────────────

with tab_flag:
    if not flagged:
        st.success("✅ Queue is empty — nothing to review!")
    else:
        st.info(f"**{len(flagged)}** invoice(s) awaiting review.")
        for inv in flagged:
            _render_invoice(inv, allow_escalate=True)


# ── Tab 2: Escalated ─────────────────────────────────────────────────────────

with tab_esc:
    if not escalated:
        st.success("No escalated invoices.")
    else:
        st.warning(f"**{len(escalated)}** escalated invoice(s) — senior review required.")
        for inv in escalated:
            _render_invoice(inv, allow_escalate=False)
