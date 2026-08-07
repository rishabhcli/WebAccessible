"""Entry point so ``python -m backend.app.cli`` runs the memory administration CLI."""

from __future__ import annotations

import sys

from backend.app.cli.memory import main

if __name__ == "__main__":
    sys.exit(main())
