import pandas as pd
from pandas.core.frame import DataFrame
from pandas.core.series import Series
from .utils import Utils
from .constants import Constants
from io import BytesIO


class PricesTemplate():
    def __init__(self, file: BytesIO, type_format: str) -> None:
        self.file: str = file
        self.type_format: str = type_format
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
        if self.type_format == Constants.CHILD:
            usecols: str = 'I:L'
        elif self.type_format == Constants.DAME:
            usecols: str = 'A:C'

        self.prices: DataFrame = pd.read_excel(
            self.file,
            sheet_name='BASE PRECIOS',
            usecols=usecols
        ).rename(
            columns={
                'REFERENCIA.1': 'REFERENCIA',
                'PRECIO.1': 'PRECIO'
            }
        ).dropna(
            subset=['REFERENCIA', 'PRECIO']
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
        if self.type_format == Constants.CHILD:
            self.prices = self.prices.drop_duplicates(
                ['LLAVE'],
            ).rename(
                columns={'LLAVE': 'ref'},
            ).drop(
                columns=['REFERENCIA', 'TALLA']
            )
        elif self.type_format == Constants.DAME:
            self.prices = self.prices.drop_duplicates(
                ['REFERENCIA'],
            ).drop(
                columns=['COLOR']
            )
