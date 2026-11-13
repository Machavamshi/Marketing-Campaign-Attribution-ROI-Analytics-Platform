"""Module entry point kept separate from the Flask application."""

from generate import SEED, SCALE, generate_dataset, main

__all__ = ["SEED", "SCALE", "generate_dataset", "main"]


if __name__ == "__main__":
    main()
