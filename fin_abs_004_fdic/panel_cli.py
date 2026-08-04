from __future__ import annotations

from . import panel
from .serialization import install_panel_serialization


def main() -> None:
    install_panel_serialization(panel)
    panel.main()


if __name__ == "__main__":
    main()
