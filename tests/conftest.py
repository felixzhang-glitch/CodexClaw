import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_LIB = ROOT / "lib" / "python"
if str(PYTHON_LIB) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIB))
