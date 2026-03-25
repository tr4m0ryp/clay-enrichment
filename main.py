import argparse
import os

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def main():
    """
    Entry point for the Avelero lead discovery and outreach pipeline.
    Supports running the full pipeline, individual layers, email sender,
    or Notion database setup.
    """
    parser = argparse.ArgumentParser(description="Avelero Lead Discovery Pipeline")
    parser.add_argument(
        "--send-emails",
        action="store_true",
        help="Run only the email sender (polls Notion for approved emails)"
    )
    parser.add_argument(
        "--layer",
        choices=["discovery", "enrichment", "people", "email"],
        help="Run a single layer for testing"
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Run Notion database setup"
    )
    args = parser.parse_args()

    if args.setup:
        from setup_notion import setup_databases
        setup_databases()
    elif args.send_emails:
        from src.email.sender import run_email_sender
        run_email_sender()
    elif args.layer:
        from src.orchestrator import run_single_layer
        run_single_layer(args.layer)
    else:
        from src.orchestrator import start_pipeline
        start_pipeline()


if __name__ == "__main__":
    main()
