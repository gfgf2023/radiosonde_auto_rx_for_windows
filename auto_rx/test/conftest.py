from pathlib import Path
import sys


AUTO_RX_ROOT = Path(__file__).resolve().parents[1]

if str(AUTO_RX_ROOT) not in sys.path:
    sys.path.insert(0, str(AUTO_RX_ROOT))
