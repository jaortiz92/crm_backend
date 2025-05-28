import numpy as np
import pandas as pd


def convert_numpy_types(value):
    """Convierte tipos numpy a tipos nativos de Python"""
    if pd.isna(value):
        return None
    if isinstance(value, (np.int64, np.int32)):
        return int(value)
    if isinstance(value, (np.float64, np.float32)):
        return float(value)
    return value
