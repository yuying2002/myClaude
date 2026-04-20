"""
Simple hello world script.
Provides a main function that prints a greeting.
"""

from __future__ import annotations

__all__: list[str] = ["main"]

def main() -> None:
    """Print 'Hello, World!' to the console.

    This function serves as the entry point when the module is executed
    as a script. It has no return value.
    """
    print("Hello, World!")

if __name__ == "__main__":
    main()
