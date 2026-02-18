import pandas as pd
from pandas.core.frame import DataFrame
from .constants import Constants
from .prices import Prices
from .names import Names
from .detailsKyly import DetailsKyly
from .detailsDame import DetailsDame
from .detailsPampili import DetailsPampili
from io import BytesIO


class ProcessDetailsOrders():
    def __init__(
        self, file_details: BytesIO,
        id: int,
        type_format: str,
    ) -> None:
        self.file_details: BytesIO = file_details
        self.id: int = id
        self.type_format: str = type_format.upper()
        self.open_files()
        self.fit()

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
        self.names: DataFrame = Names(self.type_format).names
        if self.type_format == Constants.KYLY:
            self.details: DataFrame = DetailsKyly(
                self.file_details, self.names,
                Prices().prices
            ).details

        elif self.type_format == Constants.DAME:
            self.details: DataFrame = DetailsDame(
                self.file_details, self.names
            ).details
        elif self.type_format == Constants.PAMPILI:
            self.details: DataFrame = DetailsPampili(
                self.file_details, self.names
            ).details

    def fit(self) -> None:
        '''
            Join tables to generate final inform

            Parameters
            ----------
            None

            Returns
            -------
            None
        '''
        self.initial_report: DataFrame = self.details.copy()
        self.initial_report['PRECIO'] = self.initial_report['PRECIO'].fillna(
            0)

        final_details: DataFrame = self.initial_report.groupby(
            [
                'REFERENCIA', 'REFERENCIA COMPLETA',
                'MARCA', 'GENERO', 'COLOR', 'TALLA', 'PRECIO'
            ]
        ).sum().reset_index()

        final_details['TOTAL SIN IVA'] = final_details['PRECIO'] * \
            final_details['CANTIDAD']

        final_details['TOTAL'] = final_details['TOTAL SIN IVA'] * 1.19

        final_details['CANTIDAD'] = final_details['CANTIDAD'].astype(int)

        final_details['id_order'] = self.id

        self.final_details = final_details.rename(
            columns=Constants.COLUMNS_NAMES
        )[Constants.COLUMNS_ORDER]
