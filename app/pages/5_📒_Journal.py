"""Journal comptable — écritures générées automatiquement."""
from __future__ import annotations

import streamlit as st
import pandas as pd
from datetime import date

from app._backend import require_auth, get_journal_repo, get_repo, format_tnd

require_auth()

st.title("📒 Journal Comptable")
st.caption("Écritures comptables générées lors de l'export des factures.")

journal_repo = get_journal_repo()

# ── Filters ───────────────────────────────────────────────────────────────────

col1, col2, col3 = st.columns([2, 2, 3])
with col1:
    date_from = st.date_input("Du", value=date(date.today().year, 1, 1))
with col2:
    date_to = st.date_input("Au", value=date.today())
with col3:
    compte_filter = st.text_input("Filtrer par compte (ex: 401, 6112)", value="")

entries = journal_repo.get_by_date_range(date_from, date_to)

if compte_filter.strip():
    entries = [
        e for e in entries
        if any(line.compte.startswith(compte_filter.strip()) for line in e.lines)
    ]

if not entries:
    st.info("Aucune écriture comptable pour cette période.")
    st.stop()

_count = len(entries)
_label = "écriture trouvée" if _count == 1 else "écritures trouvées"
st.markdown(f"**{_count}** {_label}")

# ── Balance summary ───────────────────────────────────────────────────────────

with st.expander("Soldes par compte", expanded=False):
    compte_totals: dict[str, dict[str, float]] = {}
    for entry in entries:
        for line in entry.lines:
            bucket = compte_totals.setdefault(line.compte, {"débit": 0.0, "crédit": 0.0})
            bucket["débit"]  += line.debit  or 0.0
            bucket["crédit"] += line.credit or 0.0

    rows = []
    for compte, totals in sorted(compte_totals.items()):
        solde = totals["débit"] - totals["crédit"]
        rows.append({
            "Compte":       compte,
            "Total Débit":  f"{totals['débit']:,.2f}",
            "Total Crédit": f"{totals['crédit']:,.2f}",
            "Solde":        f"{solde:,.2f}",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# ── Entry list ────────────────────────────────────────────────────────────────

for entry in sorted(entries, key=lambda e: e.date_ecriture, reverse=True):
    total_debit = sum(l.debit or 0 for l in entry.lines)
    header = (
        f"**{entry.date_ecriture}**  ·  {entry.reference}  ·  "
        f"{entry.description}  ·  {format_tnd(total_debit)}"
    )
    with st.expander(header, expanded=False):
        if entry.source_invoice_id:
            st.caption(f"Facture source: `{entry.source_invoice_id}`")

        lines_data = []
        for line in entry.lines:
            lines_data.append({
                "Compte":  line.compte,
                "Libellé": line.libelle,
                "Débit":   f"{line.debit:,.2f}" if line.debit else "—",
                "Crédit":  f"{line.credit:,.2f}" if line.credit else "—",
            })

        df = pd.DataFrame(lines_data)
        st.dataframe(df, hide_index=True, width="stretch")

        debit_sum  = sum(l.debit  or 0 for l in entry.lines)
        credit_sum = sum(l.credit or 0 for l in entry.lines)
        st.caption(
            f"Total débit : **{debit_sum:,.2f}**  |  "
            f"Total crédit : **{credit_sum:,.2f}**  |  "
            f"Équilibre : {'✅' if abs(debit_sum - credit_sum) < 0.005 else '❌'}"
        )
