import pandas as pd
from pandas.core.frame import DataFrame
from .constants import Constants
from .path import Paths


class Names():
    def __init__(self) -> None:
        self.open_files()

    def open_files(self) -> None:
        '''
            Open files to use

            Parameters
            ----------
            None

            Returns
            -------
            None
        '''
        self.names: DataFrame = pd.read_excel(
            Paths.FILE_NAMES,
            dtype={
                'Producto': str,
                'Talla': str
            }
        )
