"""APScheduler nightly jobs for AI automation."""
from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job_scan_roadmap_risks() -> None:
    try:
        from src.ai_agents.risk_agent import RiskAgent
        result = RiskAgent().run({"task": "scan_roadmap"})
        logger.info("nightly_risk_scan: %s", result.output)
    except Exception as exc:
        logger.error("nightly_risk_scan_error: %s", exc)


def _job_recalculate_installments() -> None:
    try:
        from src.storage.sync_mongo_repository import recalculate_late_installments_sync

        rate = float(os.getenv("LATE_PAYMENT_PENALTY_RATE", "0.10"))
        updated = recalculate_late_installments_sync(rate)
        logger.info("installment_recalc: updated %d late installments", updated)
    except Exception as exc:
        logger.error("installment_recalc_error: %s", exc)


def _job_accounting_consistency() -> None:
    try:
        from api.deps import get_components
        from src.ai_agents.accounting_agent import AccountingAgent
        components = get_components()
        try:
            agent = AccountingAgent(
                components.entry_generator,
                components.journal_repository,
                components.cost_catalog,
            )
            report = agent.check_consistency()
            logger.info("weekly_consistency_check: score=%.3f issues=%d",
                        report.get("consistency_score", 1.0), len(report.get("issues", [])))
        finally:
            components.close()
    except Exception as exc:
        logger.error("weekly_consistency_check_error: %s", exc)


_ML_RETRAIN_MIN_INVOICES = int(os.getenv("ML_RETRAIN_MIN_INVOICES", "50"))


def _job_retrain_classifier() -> None:
    """Réentraîne le modèle ML si ≥ ML_RETRAIN_MIN_INVOICES nouvelles factures VALIDATED/EXPORTED.

    Reads invoice data from Mongo (SyncMongoInvoiceRepository), not the SQLAlchemy
    repository — invoices uploaded through the real API path (AIOrchestrator) only
    ever land in Mongo, so counting/training against SQLite silently ignored all of
    them. components.repository (SQLAlchemy) is still used nowhere here; only
    components.coder.ml_classifier is needed, to retrain+persist the live model.
    """
    try:
        from api.deps import get_components
        from src.models.enums import InvoiceStatus
        from src.storage.sync_mongo_repository import SyncMongoInvoiceRepository

        components = get_components()
        try:
            mongo_repo = SyncMongoInvoiceRepository()
            counts = mongo_repo.count_by_status()
            n_labelled = (
                counts.get(InvoiceStatus.VALIDATED.value, 0)
                + counts.get(InvoiceStatus.EXPORTED.value, 0)
                + counts.get(InvoiceStatus.PAID.value, 0)
                + counts.get(InvoiceStatus.JOURNALED.value, 0)
            )
            if n_labelled >= _ML_RETRAIN_MIN_INVOICES:
                components.coder.ml_classifier.retrain_from_repo(mongo_repo)
                logger.info("ml_weekly_retrain: trained on %d invoices", n_labelled)
            else:
                logger.info("ml_weekly_retrain: skipped (only %d labelled invoices, need %d)",
                            n_labelled, _ML_RETRAIN_MIN_INVOICES)
        finally:
            components.close()
    except Exception as exc:
        logger.error("ml_weekly_retrain_error: %s", exc)


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    enabled_scan = os.getenv("AI_RISK_SCAN_ENABLED", "true").lower() == "true"

    _scheduler = BackgroundScheduler(timezone="Africa/Tunis")

    if enabled_scan:
        _scheduler.add_job(
            _job_scan_roadmap_risks,
            "cron", hour=8, minute=0,
            id="nightly_risk_scan",
            replace_existing=True,
            misfire_grace_time=3600,
        )

    _scheduler.add_job(
        _job_recalculate_installments,
        "cron", hour=0, minute=1,
        id="installment_recalc",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    _scheduler.add_job(
        _job_accounting_consistency,
        "cron", day_of_week="mon", hour=6, minute=0,
        id="weekly_consistency",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    _scheduler.add_job(
        _job_retrain_classifier,
        "cron", day_of_week="sun", hour=3, minute=0,
        id="weekly_ml_retrain",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    _scheduler.start()
    logger.info("scheduler_started jobs=%d", len(_scheduler.get_jobs()))
    return _scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler
