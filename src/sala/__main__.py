"""Allow PYTHONPATH=src python -m sala ... without installation."""

from .cli import main

raise SystemExit(main())
