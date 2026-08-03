from __future__ import annotations

import runpy


def main() -> None:
    try:
        runpy.run_module("fin_rvi_002_stage1.run_stage1", run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (None, 0, 2):
            raise
        if exc.code == 2:
            print("Diagnostic evidence published: no strict holdout under the current grammar.")


if __name__ == "__main__":
    main()
