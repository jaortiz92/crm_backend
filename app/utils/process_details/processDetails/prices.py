import pandas as pd
from pandas.core.frame import DataFrame
from pandas.core.series import Series
from .utils import Utils
from .constants import Constants
from .path import Paths


class Prices():
    def __init__(self) -> None:
        self.open_files()
        self.clean_file()

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
        self.prices: DataFrame = pd.read_excel(
            Paths.FILE_PRICES,
            usecols='A:B',
            dtype={
                'ref': str,
                'Precio_Venta': int,
            }
        ).rename(
            columns={
                'Precio_Venta': 'PRECIO'
            }
        )

    def clean_file(self) -> None:
        '''
        This function clean prices file

        Parameters
        ----------
        None

        Returns
        -------
        None
        '''
        reference, size = Utils.separate_ref(
            self.prices['ref']
        )

        self.prices['Referencia'] = reference
        self.prices['Talla'] = size

        self.prices.drop_duplicates(
            ['ref'],
            inplace=True,
            keep='first'
        )
