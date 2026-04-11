"""CLI package."""


def main():
    from .cli import main as cli_main

    return cli_main()

__all__ = ["main"]
