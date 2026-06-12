import signal
import sys
from pathlib import Path

# Make src importable when running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent.config_loader import build_agent
from src.utils.logging import configure_logging, get_logger


def main() -> None:
    configure_logging()
    logger = get_logger("run_agent")

    agent = build_agent()

    def _shutdown(sig, frame):
        logger.info("shutdown_signal_received")
        agent.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("starting_invoice_agent")
    agent.start()


if __name__ == "__main__":
    main()
