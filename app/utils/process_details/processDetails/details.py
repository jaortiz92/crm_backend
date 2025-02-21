from typing import List
import pandas as pd
from pandas.core.frame import DataFrame
from .constants import Constants
from io import BytesIO


class Details():
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
        usecols: List[str] = ['A:Z', 'A:U', 'A:Y', 'B:Z']
        flag = False
        i = 0
        while not flag:
            self.details: DataFrame = pd.read_excel(
                self.file,
                sheet_name=Constants.SHEET_TO_JOB,
                header=5,
                usecols=usecols[i],
                dtype={
                    'REFERENCIA': str,
                    'COLOR': str,
                    'TOTAL': str
                }
            )
            if 'TOTAL' in self.details.columns:
                flag = True
            else:
                i += 1

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
        details['COLOR'] = details['COLOR'].str.strip()

        details['REFERENCIA COMPLETA'] = details[
            ['REFERENCIA']
        ].apply(
            self.add_name,
            names=['REFERENCIA',],
            axis=1
        )

        details['GENERO'] = details[
            ['MARCA', 'REFERENCIA COMPLETA']
        ].apply(
            self.add_gender,
            names=['MARCA', 'REFERENCIA COMPLETA'],
            axis=1
        )

        details = details.melt(
            ['REFERENCIA', 'COLOR', 'MARCA', 'REFERENCIA COMPLETA', 'GENERO'],
            value_name='CANTIDAD',
            var_name='TALLA',
            ignore_index=True
        )

        details['CANTIDAD'] = pd.to_numeric(
            details['CANTIDAD'], errors='coerce'
        )

        details['ref'] = details['REFERENCIA'] + '-' + details['TALLA']
        details.sort_values(
            ['REFERENCIA', 'COLOR', 'TALLA'],
            inplace=True
        )

        self.details: DataFrame = details[~details['CANTIDAD'].isna()].reset_index(
            drop=True
        )

        self.details['MARCA'] = self.details['MARCA'].map(
            Constants.CODE_BRANDS
        )

    def add_name(self, x, names: List[str]) -> str:
        '''
            return name to reference

            Parameters
            ----------
            x: List
                0: Refernce
                1: Size

            Returns
            -------
            str:
                return name to reference
        '''
        df_temp: DataFrame = self.names[(
            self.names['Producto'] == x[names[0]])]
        if df_temp.shape[0] == 0:
            return x[0]
        else:
            return df_temp.iloc[0, :]['Descripción']

    def add_gender(self, x, names: List[str]) -> str:
        '''
            return gerder to reference

            Parameters
            ----------
            x: List
                0: Brand
                1: Description
            names: List
                0: Brand name
                1: Description name

            Returns
            -------
            str:
                return gerder to reference
        '''
        brand = x[names[0]]
        description = x[names[1]]

        if brand in Constants.DAME_BRANDS:
            return Constants.DAME
        else:
            if (
                'MASCULINO' in description or 'MASCULINA' in description or
                'NIÑO' in description or 'MUSCULOSA' in description or
                'CAMISETA SIN MANGAS' in description or
                'CASACO' in description
            ):
                return Constants.MALE_CHILD
            elif 'UNISEX' in description:
                return Constants.UNISEX
            else:
                return Constants.FEMALE_CHILD
