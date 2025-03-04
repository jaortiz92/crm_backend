from typing import List
import pandas as pd
from pandas.core.frame import DataFrame
from .constants import Constants
from io import BytesIO


class DetailsInvoice():
    def __init__(self, file: BytesIO) -> None:
        self.file: str = file
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
        self.details: DataFrame = pd.read_excel(
            self.file,
            dtype={
                'Codigo': str,
                'Talla': str,
                'Color': str
            }
        ).rename(
            columns={
                'Codigo': 'REFERENCIA',
                'Color': 'COLOR',
                'Talla': 'TALLA',
                'Cantidad': 'CANTIDAD',
                'Valor Unit': 'PRECIO',
                'Descto': 'DESCUENTO',
                'Venta Neta': 'TOTAL SIN IVA',
                'Total': 'TOTAL'
            }
        )

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
        details: DataFrame = self.details.copy()

        details.dropna(
            subset=['REFERENCIA'],
            inplace=True,
            ignore_index=True
        )
        columns_to_use: List[str] = [
            'REFERENCIA', 'Descripcion', 'Descripcion detallada'
        ]

        details['REFERENCIA COMPLETA'] = details[columns_to_use].apply(
            self.add_name,
            names=columns_to_use,
            axis=1
        )

        details['GENERO'] = details['Genero'].map(
            Constants.GENDERS
        )

        details['MARCA'] = details['Marca'].map(
            Constants.CODE_BRANDS
        )
        self.details: DataFrame = details.copy()

    def add_name(self, x, names: List[str]) -> str:
        '''
            return name to reference

            Parameters
            ----------
            x: List
                0: Reference
                1: Description
                2: Description Cleaned

            Returns
            -------
            str:
                return name to reference
        '''
        if x[names[2]] == Constants.WITHOUT_DEFINE:
            result: str = str(x[names[1]]).replace(x[names[0]], '')
            return result.strip()
        else:
            return x[names[2]]
