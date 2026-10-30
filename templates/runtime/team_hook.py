"""Bootstrap проектного hook: исполняется только после доверия runtime к его определению."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai_ops_kit.cli.project_session import main

if __name__ == "__main__":
    raise SystemExit(main())
