"""main.py — Convenience launcher for Captura.

Allows the app to be started from the terminal as::

    python main.py

Delegates immediately to :func:`app.main`.
"""

from app import main

if __name__ == "__main__":
    main()
