"""APScheduler nightly jobs for AI automation."""
from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job_scan_roadmap_risks() -> None:
    try:
        from api.deps import get_session_ctx, get_components
        from src.ai_agents.risk_agent import RiskAgent
        with get_session_ctx() as db:
            result = RiskAgent().run({"task": "scan_roadmap", "db": db})
            logger.info("nightly_risk_scan: %s", result.output)
    except Exception as exc:
        logger.error("nightly_risk_scan_error: %s", exc)


def _job_recalculate_installments() -> None:
    try:
        from datetime import date
        from sqlalchemy import select, text
        from api.deps import get_session_ctx

        today = date.today()
        with get_session_ctx() as db:
            from src.storage.orm_models_payments import PaymentInstallmentORM
            pending = db.execute(
                select(PaymentInstallmentORM).where(
                    PaymentInstallmentORM.due_date < today,
                    PaymentInstallmentORM.status.in_(["PENDING", "LATE"]),
                )
            ).scalars().all()

            rate = float(os.getenv("LATE_PAYMENT_PENALTY_RATE", "0.10"))
            for inst in pending:
                days_overdue = (today - inst.due_date).days
                late_periods = days_overdue // 30
                if late_periods > inst.late_periods:
                    inst.current_amount = round(inst.base_amount * ((1 + rate) ** late_periods), 3)
                    inst.late_periods = late_periods
                    inst.status = "LATE"
            db.commit()
            logger.info("installment_recalc: updated %d late installments", len(pending))
    except Exception as exc:
        logger.error("installment_recalc_error: %s", exc)


def _job_accounting_consistency() -> None:
    try:
        from api.deps import get_session_ctx, get_components
        from src.ai_agents.accounting_agent import AccountingAgent
        with get_session_ctx() as db:
            components = get_components()
            try:
                agent = AccountingAgent(
                    components.entry_generator,
                    components.journal_repository,
                    components.cost_catalog,
                )
                report = agent.check_consistency(db)
                logger.info("weekly_consistency_check: score=%.3f issues=%d",
                            report.get("consistency_score", 1.0), len(report.get("issues", [])))
            finally:
                components.close()
    except Exception as exc:
        logger.error("weekly_consistency_check_error: %s", exc)


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
