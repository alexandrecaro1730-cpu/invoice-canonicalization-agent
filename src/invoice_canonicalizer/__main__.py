"""Business objective: make the project runnable with python -m invoice_canonicalizer.

Technical description: forwards process arguments to the package CLI and returns its exit code.
"""

from invoice_canonicalizer.cli import main

raise SystemExit(main())
