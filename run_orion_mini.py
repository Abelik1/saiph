# SPDX-License-Identifier: AGPL-3.0-or-later
if __name__ == "__main__":
    try:
        from orion_mini.app import main
        raise SystemExit(main())
    except Exception:
        import os
        import traceback
        from pathlib import Path
        root = Path(os.environ.get("ORION_MINI_DATA_DIR") or Path(os.environ["LOCALAPPDATA"]) / "OrionMini")
        root.mkdir(parents=True, exist_ok=True)
        with (root / "startup-error.log").open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        raise
