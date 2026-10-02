import argparse
import asyncio

from worker_bot.core import run_worker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True, help="Telegram bot token")
    args = parser.parse_args()

    asyncio.run(run_worker(args.token))


if __name__ == "__main__":
    main()
