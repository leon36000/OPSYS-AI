import os
import sys

_BRAND_SRC = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "src", "brand")
)
if _BRAND_SRC not in sys.path:
    sys.path.insert(0, _BRAND_SRC)
