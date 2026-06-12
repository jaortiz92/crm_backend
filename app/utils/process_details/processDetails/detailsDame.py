from typing import List
import pandas as pd
from pandas.core.frame import DataFrame
from .constants import Constants
from .pricesTemplate import PricesTemplate
from io import BytesIO


class DetailsDame():
    def __init__(self, file: BytesIO, names: DataFrame) -> None:
        self.file: str = file
        self.names: DataFrame = names
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
        target_col: str = 'TOTAL'
        df: DataFrame = pd.read_excel(
            self.file,
            sheet_name=Constants.SHEET_TO_JOB,
            header=5,
            dtype={
                'REFERENCIA': str,
                'COLOR': str,
                'TOTAL': str
            }
        )

        if target_col not in df.columns:
            raise ValueError(
                f"La columna '{target_col}' no existe en el archivo."
            )

        target_idx = df.columns.get_loc(target_col)
        self.details: DataFrame = df.iloc[:, :target_idx + 1]

        self.prices: DataFrame = PricesTemplate(
            self.file, Constants.DAME
        ).prices

    def clean_file(self) -> None:
        '''
        This function clean details file

        Parameters
        ----------
        None

        Returns
        -------
        None
        '''
        details: DataFrame = self.details[
            (~self.details['REFERENCIA'].isna()) &
            (~self.details['TOTAL'].isna())
        ]
        details.columns = [
            str(column) for column in list(details.columns)
        ]

        details = details[details['TOTAL'].str.isnumeric()]
        details['REFERENCIA'] = details['REFERENCIA'].str.upper()
        details = details.iloc[:, :list(details.columns).index('TOTAL')]
        details['COLOR'] = details['COLOR'].str.upper().str.strip()

        details = pd.merge(
            left=details,
            right=self.prices,
            on='REFERENCIA',
            how='left'
        )

        details = pd.merge(
            left=details,
            right=self.names[
                ['MODELO', 'DESCRIPCIÓN', 'MARCA', 'PRECIO POR MAYOR']
            ],
            left_on='REFERENCIA',
            right_on='MODELO',
            how='left'
        ).rename(columns=Constants.COLUMNS_NAMES_DAME)

        details['PRECIO'] = details['PRECIO'].fillna(
            details['PRECIO LISTA']
        )

        details.drop(columns=['MODELO', 'PRECIO LISTA'], inplace=True)

        details['GENERO'] = Constants.FEMALE_DAME

        details = details.melt(
            [
                'REFERENCIA', 'COLOR',
                'MARCA', 'REFERENCIA COMPLETA',
                'GENERO', 'PRECIO'
            ],
            value_name='CANTIDAD',
            var_name='TALLA',
            ignore_index=True
        ).dropna(
            subset=['CANTIDAD'],
            ignore_index=True
        )

        details['CANTIDAD'] = pd.to_numeric(
            details['CANTIDAD'], errors='coerce'
        )

        details.sort_values(
            ['REFERENCIA', 'COLOR', 'TALLA'],
            inplace=True
        )

        details['MARCA'] = details['MARCA'].map(
            Constants.CODE_BRANDS
        )

        self.details: DataFrame = details.copy()
