# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Point d'entrée du programme Windows.

PyInstaller a besoin d'un SCRIPT à lancer : c'est celui-ci. Il ne fait qu'appeler la même fonction `main()` que la commande
`scrinium` d'une installation Python ordinaire (voir `[project.scripts]` dans pyproject.toml). Rien d'autre ne doit être mis ici."""
import multiprocessing

from scrinium.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()     # nécessaire sous Windows pour qu'un programme « gelé » puisse lancer des sous-processus
    raise SystemExit(main())
