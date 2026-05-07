"""
Entry point. Run this file to start the agent.

Scheduling options (pick one):
  A) Python schedule library  — runs in the foreground, good for testing
  B) Windows Task Scheduler   — production-grade, no process to keep alive
  C) Run once                 — python scheduler.py --once

Usage:
  pip install schedule   # only needed for option A
  python scheduler.py          # option A (loop, fires at 09:00 daily)
  python scheduler.py --once   # option C (run now and exit)
"""

import argparse
import logging
import sys
from dotenv import load_dotenv
from config import Config
from agent import JiraRiskDetectorAgent


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_once() -> None:
    load_dotenv()
    config = Config.from_env()
    setup_logging(config.log_level)
    agent = JiraRiskDetectorAgent(config)
    agent.run()


def run_scheduled() -> None:
    try:
        import schedule
        import time
    except ImportError:
        print("Install the schedule library first:  pip install schedule")
        sys.exit(1)

    load_dotenv()
    config = Config.from_env()
    setup_logging(config.log_level)
    logger = logging.getLogger(__name__)

    agent = JiraRiskDetectorAgent(config)

    # Fire once immediately on startup so you can verify it works
    logger.info("Running initial scan on startup...")
    agent.run()

    schedule.every().day.at("09:00").do(agent.run)
    logger.info("Scheduler active. Fires daily at 09:00. Press Ctrl+C to stop.")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jira Risk Detector Agent")
    parser.add_argument(
        "--once", action="store_true", help="Run once and exit (no scheduler)"
    )
    args = parser.parse_args()

    if args.once:
        run_once()
    else:
        run_scheduled()
