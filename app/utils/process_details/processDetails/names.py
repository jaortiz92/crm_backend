import pandas as pd
from pandas.core.frame import DataFrame
from .constants import Constants
from .path import Paths


class Names():
    def __init__(self, type_format: str) -> None:
        self.type_format: str = type_format
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
        if Constants.KYLY == self.type_format:
            self.names: DataFrame = pd.read_excel(
                Paths.FILE_NAMES_KYLY,
                dtype={
                    'Producto': str,
                    'Talla': str
                }
            )
        elif Constants.DAME == self.type_format:
            self.names: DataFrame = pd.read_excel(
                Paths.FILE_NAMES_AND_PRICES_DAME,
                dtype={
                    'MODELO': str,
                    'DESCRIPCIÓN': str
                }
            )

            self.names.drop_duplicates(
                subset=['MODELO'],
                keep='first',
                inplace=True
            )
        elif Constants.PAMPILI == self.type_format:
            self.names: DataFrame = pd.read_excel(
                Paths.FILE_NAMES_AND_PRICES_PAMPILI,
                dtype={
                    'REFERENCIA': str,
                }
            )

            self.names.drop_duplicates(
                subset=['REFERENCIA'],
                keep='first',
                inplace=True
            )
