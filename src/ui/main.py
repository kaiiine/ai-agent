#!/usr/bin/env python3
from __future__ import annotations
from src.ui.app import run_cli
from dotenv import load_dotenv

load_dotenv()


def main():
    run_cli()


if __name__ == "__main__":
    main()
