"""Public console entrypoint; terminal behavior belongs to the CLI interface."""

from app.interfaces.cli import main as main

if __name__ == "__main__":
    raise SystemExit(main())
