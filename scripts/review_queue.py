"""Interactive terminal UI for human review of flagged invoices.

Usage:
    .venv/bin/python scripts/review_queue.py
    .venv/bin/python scripts/review_queue.py --db sqlite:///./data/invoices.db
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.config_loader import load_config
from src.models.enums import FlagSeverity, InvoiceStatus
from src.models.invoice import ConfidenceField, InvoiceRecord, ValidationFlag
from src.storage.db import build_engine, build_session_factory, init_db
from src.storage.repository import InvoiceRepository
from src.suivi.lifecycle_tracker import LifecycleTracker
from src.validation.anomaly_detector import AnomalyDetector
from src.validation.coherence_checker import CoherenceChecker
from src.validation.duplicate_detector import DuplicateDetector
from src.validation.field_validator import FieldValidator


# ── ANSI colours ─────────────────────────────────────────────────────────────

class C:
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    GREEN  = "\033[92m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RESET  = "\033[0m"


def _conf_color(conf: float) -> str:
    if conf >= 0.85:
        return C.GREEN
    if conf >= 0.60:
        return C.YELLOW
    return C.RED


def _fmt_conf(cf: ConfidenceField) -> str:
    if cf.value is None:
        return f"{C.RED}(missing){C.RESET}"
    pct = f"{cf.confidence:.0%}"
    col = _conf_color(cf.confidence)
    return f"{cf.value}  {col}{pct}{C.RESET}"


# ── Display helpers ────────────────────────────────────────────────────────────

def _print_invoice(inv: InvoiceRecord) -> None:
    sep = "─" * 66
    print(f"\n{C.BOLD}{sep}{C.RESET}")
    print(f"  {C.BOLD}Invoice {inv.id}{C.RESET}")
    print(f"  Status: {C.CYAN}{inv.status.value}{C.RESET}   "
          f"Direction: {inv.direction.value}   "
          f"File: {C.DIM}{inv.raw_file_path}{C.RESET}")
    print(sep)
    fields = [
        ("issuer_name",      "Issuer"),
        ("issuer_tax_id",    "Issuer MF"),
        ("recipient_name",   "Recipient"),
        ("recipient_tax_id", "Recipient MF"),
        ("invoice_number",   "Invoice #"),
        ("invoice_date",     "Date"),
        ("due_date",         "Due date"),
        ("amount_ht",        "HT"),
        ("tva_rate",         "TVA rate"),
        ("tva_amount",       "TVA amount"),
        ("amount_ttc",       "TTC"),
    ]
    for attr, label in fields:
        cf: ConfidenceField = getattr(inv, attr)
        print(f"  {label:<16}: {_fmt_conf(cf)}")
    print(f"  {'Currency':<16}: {inv.currency}")

    if inv.line_items:
        print(f"\n  Line items ({len(inv.line_items)}):")
        for li in inv.line_items:
            print(f"    {li.line_number}. {li.description or '—':<35} "
                  f"qty={li.quantity}  unit={li.unit_price}  total={li.line_total}")

    open_flags = [f for f in inv.flags if not f.resolved]
    if open_flags:
        print(f"\n  {C.BOLD}Flags ({len(open_flags)} open):{C.RESET}")
        for f in open_flags:
            icon = f"{C.RED}✗{C.RESET}" if f.severity == FlagSeverity.ERROR else f"{C.YELLOW}⚠{C.RESET}"
            field_tag = f"  [{f.field_name}]" if f.field_name else ""
            print(f"    {icon} {f.flag_type.value}{field_tag}: {f.message[:80]}")
    else:
        print(f"\n  {C.GREEN}No open flags.{C.RESET}")
    print(C.BOLD + sep + C.RESET)


def _print_menu() -> None:
    print(f"\n  {C.BOLD}Actions:{C.RESET}  "
          f"[{C.GREEN}a{C.RESET}]pprove  "
          f"[{C.YELLOW}c{C.RESET}]orrect  "
          f"[{C.RED}r{C.RESET}]eject  "
          f"[{C.CYAN}e{C.RESET}]scalate  "
          f"[s]kip  "
          f"[q]uit")


# ── Actions ───────────────────────────────────────────────────────────────────

def _do_approve(inv: InvoiceRecord, tracker: LifecycleTracker) -> None:
    reviewer = input("  Reviewer name: ").strip() or "reviewer"
    notes = input("  Notes (optional): ").strip() or None
    tracker.approve_flagged(inv.id, reviewer=reviewer, notes=notes)
    print(f"  {C.GREEN}Approved → VALIDATED{C.RESET}")


def _do_reject(inv: InvoiceRecord, tracker: LifecycleTracker) -> None:
    reviewer = input("  Reviewer name: ").strip() or "reviewer"
    reason = input("  Rejection reason: ").strip()
    if not reason:
        print("  Reason required. Skipping.")
        return
    tracker.reject_invoice(inv.id, reviewer=reviewer, reason=reason)
    print(f"  {C.RED}Rejected.{C.RESET}")


def _do_escalate(inv: InvoiceRecord, repo: InvoiceRepository) -> None:
    note = input("  Escalation note: ").strip()
    inv.status = InvoiceStatus.ESCALATED
    if note:
        from src.models.enums import FlagType
        inv.add_flag(ValidationFlag(
            flag_type=FlagType.ESCALATED,
            severity=FlagSeverity.ERROR,
            message=f"Escalated by reviewer: {note}",
        ))
    repo.save(inv)
    print(f"  {C.CYAN}Escalated.{C.RESET}")


_EDITABLE_FIELDS = [
    ("issuer_name",      "Issuer name",      str),
    ("issuer_tax_id",    "Issuer MF",        str),
    ("recipient_name",   "Recipient name",   str),
    ("recipient_tax_id", "Recipient MF",     str),
    ("invoice_number",   "Invoice #",        str),
    ("invoice_date",     "Invoice date",     date),
    ("due_date",         "Due date",         date),
    ("amount_ht",        "Amount HT",        float),
    ("tva_rate",         "TVA rate (%)",     float),
    ("tva_amount",       "TVA amount",       float),
    ("amount_ttc",       "Amount TTC",       float),
]


def _parse_field(raw: str, field_type: type) -> Any:
    raw = raw.strip()
    if not raw:
        return None
    if field_type is str:
        return raw
    if field_type is float:
        return float(raw.replace(",", "."))
    if field_type is date:
        from src.utils.date_parser import parse_date
        parsed = parse_date(raw)
        if parsed is None:
            raise ValueError(f"Unrecognised date: {raw!r}")
        return parsed
    raise TypeError(f"Unknown type {field_type}")


def _do_correct(
    inv: InvoiceRecord,
    repo: InvoiceRepository,
    validators: tuple,
) -> None:
    print(f"\n  {C.BOLD}Correctable fields:{C.RESET}")
    for i, (attr, label, _) in enumerate(_EDITABLE_FIELDS, 1):
        cf: ConfidenceField = getattr(inv, attr)
        print(f"    {i:>2}. {label:<20}: {_fmt_conf(cf)}")
    print(f"       0. Done\n")

    changed = False
    while True:
        raw = input("  Field number to edit (0 when done): ").strip()
        if raw == "0" or raw == "":
            break
        try:
            idx = int(raw) - 1
            if not (0 <= idx < len(_EDITABLE_FIELDS)):
                raise ValueError
        except ValueError:
            print("  Invalid choice.")
            continue

        attr, label, field_type = _EDITABLE_FIELDS[idx]
        current: ConfidenceField = getattr(inv, attr)
        new_raw = input(f"  New {label} [{current.value}]: ").strip()
        if not new_raw:
            continue
        try:
            new_value = _parse_field(new_raw, field_type)
        except (ValueError, TypeError) as exc:
            print(f"  {C.RED}Parse error: {exc}{C.RESET}")
            continue

        setattr(inv, attr, ConfidenceField(
            value=new_value, confidence=1.0, source="human_correction",
        ))
        print(f"  {C.GREEN}Set {attr} = {new_value}{C.RESET}")
        changed = True

    if not changed:
        print("  No changes made.")
        return

    # Clear old flags and re-validate
    inv.flags = []
    field_validator, coherence_checker, duplicate_detector, anomaly_detector = validators
    inv = field_validator.validate(inv)
    inv = coherence_checker.check(inv)
    inv = duplicate_detector.detect(inv)
    inv = anomaly_detector.detect(inv)

    from datetime import datetime, timezone
    inv.validated_at = datetime.now(timezone.utc)
    inv.status = InvoiceStatus.FLAGGED if inv.has_errors else InvoiceStatus.VALIDATED
    repo.save(inv)

    if inv.status == InvoiceStatus.VALIDATED:
        print(f"  {C.GREEN}All checks passed → VALIDATED{C.RESET}")
    else:
        remaining = [f for f in inv.flags if not f.resolved]
        print(f"  {C.YELLOW}Still {len(remaining)} open flag(s) → FLAGGED{C.RESET}")
        for f in remaining:
            icon = f"{C.RED}✗{C.RESET}" if f.severity == FlagSeverity.ERROR else f"{C.YELLOW}⚠{C.RESET}"
            print(f"    {icon} {f.flag_type.value}: {f.message[:80]}")


# ── Pipeline builders ─────────────────────────────────────────────────────────

def _build_validators(cfg: dict, repo: InvoiceRepository):
    return (
        FieldValidator(confidence_thresholds=cfg["extraction"]["confidence_thresholds"]),
        CoherenceChecker(config=cfg),
        DuplicateDetector(config=cfg, repository=repo),
        AnomalyDetector(config=cfg, repository=repo),
    )


# ── Main loop ─────────────────────────────────────────────────────────────────

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Human review queue for flagged invoices.")
    parser.add_argument("--db", help="SQLAlchemy DB URL (overrides settings.yaml)")
    args = parser.parse_args()

    cfg = load_config()
    db_url = args.db or cfg["storage"]["db_url"]
    engine = build_engine(db_url)
    init_db(engine)
    sf = build_session_factory(engine)

    session = sf()
    repo = InvoiceRepository(session)
    tracker = LifecycleTracker(repository=repo)
    validators = _build_validators(cfg, repo)

    print(f"\n{C.BOLD}=== Invoice Review Queue ==={C.RESET}")

    while True:
        # Re-fetch each iteration so approvals/corrections are reflected
        session.expire_all()
        flagged = repo.get_flagged()
        if not flagged:
            print(f"\n  {C.GREEN}Queue empty — nothing to review.{C.RESET}\n")
            break

        print(f"\n  {C.BOLD}{len(flagged)} invoice(s) awaiting review.{C.RESET}")
        inv = flagged[0]
        _print_invoice(inv)
        _print_menu()

        choice = input("\n  Choice: ").strip().lower()

        if choice == "q":
            print("  Exiting.")
            break
        elif choice == "s":
            print("  Skipped.")
            flagged.pop(0)
            continue
        elif choice == "a":
            try:
                _do_approve(inv, tracker)
            except Exception as exc:
                print(f"  {C.RED}Error: {exc}{C.RESET}")
        elif choice == "r":
            _do_reject(inv, tracker)
        elif choice == "e":
            _do_escalate(inv, repo)
        elif choice == "c":
            _do_correct(inv, repo, validators)
        else:
            print("  Unknown action.")
            continue

    session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
