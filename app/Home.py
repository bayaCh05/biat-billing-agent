"""Upload & Process — main page of the Invoice Processing Agent demo."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from app._backend import (
    get_pipeline_components,
    render_flags,
    render_invoice_fields,
    require_auth,
    status_badge,
)
from src.agent.pipeline import extract, classify, validate, export_file, post_journal
from src.models.enums import FlagType, InvoiceStatus
from src.models.invoice import InvoiceRecord
from src.utils.file_utils import sha256

st.set_page_config(
    page_title="Invoice Agent — BIAT IT",
    page_icon="🧾",
    layout="wide",
)

require_auth()

st.title("🧾 Invoice Processing Agent")
st.caption("Intelligent invoice extraction, classification, validation and auto-correction.")
st.divider()

# ── Sidebar controls ──────────────────────────────────────────────────────────

with st.sidebar:
    st.header("⚙️ Settings")
    live_mode = st.toggle("Use live Ollama LLM", value=True,
                          help="Off = fast mock response (no Ollama needed)")
    st.caption("Auto-correction: math pass runs locally on every invoice.")
    st.divider()
    st.markdown("**Pages**")

# ── Upload area ───────────────────────────────────────────────────────────────

col_upload, col_result = st.columns([1, 1], gap="large")

with col_upload:
    st.subheader("📤 Upload Invoice")
    st.info(
        "📎 Importez uniquement des factures fournisseurs (PDF). "
        "Les relevés bancaires, contrats, et autres documents "
        "seront automatiquement rejetés."
    )
    uploaded = st.file_uploader(
        "Drop a PDF or image invoice here",
        type=["pdf", "png", "jpg", "jpeg", "tiff"],
        label_visibility="collapsed",
    )

    if uploaded:
        st.caption(f"File: `{uploaded.name}` ({uploaded.size:,} bytes)")
        process_btn = st.button("▶ Process Invoice", type="primary", width="stretch")
    else:
        st.info("Upload an invoice file to get started.")
        process_btn = False

# ── Pipeline execution ────────────────────────────────────────────────────────

if uploaded and process_btn:
    with col_result:
        suffix = Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name

        try:
            components, repo = get_pipeline_components(live=live_mode)
        except Exception as exc:
            st.error(f"Failed to build pipeline: {exc}")
            st.stop()

        file_hash = sha256(tmp_path)
        existing = repo.get_by_hash(file_hash)
        if existing:
            existing.status = InvoiceStatus.RECEIVED
            existing.retry_count = 0
            existing.last_error = None
            existing.flags = []
            existing.raw_file_path = tmp_path
            repo.save(existing)
            invoice = existing
        else:
            invoice = InvoiceRecord(
                file_hash=file_hash,
                raw_file_path=tmp_path,
                status=InvoiceStatus.RECEIVED,
            )
            repo.save(invoice)

        try:
            with st.status("Running pipeline…", expanded=True) as pipeline_status:
                st.write("🔍 Extracting fields…")
                invoice = extract(invoice, components)
                _is_extraction_error = (
                    invoice.last_error
                    or invoice.status in {InvoiceStatus.EXTRACTION_FAILED,
                                          InvoiceStatus.ERROR}
                )
                if _is_extraction_error:
                    # Check for categorical rejection first
                    _not_invoice_flag = next(
                        (f for f in invoice.flags
                         if f.flag_type == FlagType.NOT_AN_INVOICE),
                        None,
                    )
                    if _not_invoice_flag:
                        pipeline_status.update(label="Fichier rejeté", state="error")
                        st.error(
                            "🚫 **Ce fichier n'est pas une facture.**\n\n"
                            f"{_not_invoice_flag.message}"
                        )
                    else:
                        pipeline_status.update(label="Extraction failed", state="error")
                        err = invoice.last_error or ""
                        if "tesseract" in err.lower():
                            st.error("**Tesseract OCR not installed.** "
                                     "Install it with `brew install tesseract` or upload a native PDF instead.")
                        elif "connection refused" in err.lower() or "ollama" in err.lower():
                            st.error("**Ollama is not running.** Toggle off 'Use live Ollama LLM' in the "
                                     "sidebar to use mock extraction, or start Ollama with `ollama serve`.")
                        else:
                            st.error(err or "Extraction failed — check the terminal for details.")
                    st.stop()

                st.write("🏷️ Classifying & coding…")
                invoice = classify(invoice, components)

                st.write("✅ Validating…")
                invoice = validate(invoice, components)

                if invoice.status == InvoiceStatus.VALIDATED:
                    st.write("📤 Exporting…")
                    invoice = export_file(invoice, components)
                if invoice.status == InvoiceStatus.EXPORTED:
                    st.write("📒 Posting journal entry…")
                    invoice = post_journal(invoice, components)
                if invoice.status == InvoiceStatus.JOURNALED:
                    pipeline_status.update(label="Pipeline complete!", state="complete")
                elif invoice.status == InvoiceStatus.EXPORTED:
                    pipeline_status.update(label="Exported — journal entry pending review", state="error")
                else:
                    pipeline_status.update(label="Invoice flagged for review", state="error")
        finally:
            Path(tmp_path).unlink(missing_ok=True)
            components.close()

        # ── Results ───────────────────────────────────────────────────────────
        st.subheader("📋 Result")
        st.markdown(f"### {status_badge(invoice.status)}")

        tab_fields, tab_flags, tab_items = st.tabs(["Extracted Fields", "Flags", "Line Items"])

        with tab_fields:
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("Direction", invoice.direction.value)
                st.metric("Accounting Code",
                          f"{invoice.accounting_compte} — {invoice.accounting_label}"
                          if invoice.accounting_compte else "—")
                st.metric("Currency", invoice.currency)
            with col_b:
                st.metric("Extraction Method",
                          invoice.extraction_method.value if invoice.extraction_method else "—")
                st.metric("Amount TTC",
                          f"{invoice.amount_ttc.value:,.3f} {invoice.currency}"
                          if invoice.amount_ttc.value else "—")
                st.metric("Auto-corrected",
                          "Yes" if any(f.source in ("ai_correction", "math_correction")
                                       for f in [invoice.amount_ht, invoice.tva_amount,
                                                 invoice.amount_ttc]) else "No")
            st.divider()
            render_invoice_fields(invoice)

        with tab_flags:
            render_flags(invoice)

        with tab_items:
            if invoice.line_items:
                rows = [
                    {
                        "#": li.line_number,
                        "Description": li.description or "—",
                        "Qty": li.quantity,
                        "Unit Price": li.unit_price,
                        "Total": li.line_total,
                        "TVA %": li.tva_rate,
                    }
                    for li in invoice.line_items
                ]
                st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
            else:
                st.info("No line items extracted.")

elif not uploaded:
    with col_result:
        st.subheader("Result")
        st.markdown("""
        **What this agent does:**
        1. 🔍 **Extracts** all fields from the invoice using OCR + LLM
        2. 🏷️ **Classifies** supplier vs client and assigns accounting codes
        3. ✅ **Validates** amounts, dates, duplicates, anomalies
        4. 🤖 **Auto-corrects** math errors locally (deterministic)
        5. 📤 **Exports** validated invoices to JSON
        """)
