"""Array type used by the numerical models."""

from typing import Any

import numpy as np
from numpy.typing import NDArray

type Array = NDArray[np.floating[Any]]
