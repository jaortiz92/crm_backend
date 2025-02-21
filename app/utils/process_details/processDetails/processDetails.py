import logging
from typing import List
import pandas as pd
from pandas.core.frame import DataFrame
from pandas.core.series import Series
from .constants import Constants
from .utils import Utils
from .prices import Prices
from .names import Names
from .details import Details
from io import BytesIO
import pathlib


class ProcessDetails():
    def __init__(
        self, file_details: BytesIO,
        id: int,
        type_table: str
    ) -> None:
        self.file_details: BytesIO = file_details
        self.id: int = id
        self.type_table: str = type_table
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
        self.names: DataFrame = Names().names
        self.details: DataFrame = Details(
            self.file_details, self.names).details
        self.prices: DataFrame = Prices().prices

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
        self.initial_report: DataFrame = pd.merge(
            left=self.details,
            right=self.prices[['ref', 'PRECIO']],
            on='ref',
            how='left'
        )

        self.initial_report['PRECIO'] = self.initial_report['PRECIO'].fillna(0)

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

        final_details['id_' + self.type_table] = self.id

        if self.type_table == 'order':
            self.final_details = final_details.rename(
                columns=Constants.COLUMNS_NAMES
            )[Constants.COLUMNS_ORDER]
