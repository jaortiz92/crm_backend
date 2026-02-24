from typing import List
import pandas as pd
from pandas.core.frame import DataFrame
from .constants import Constants
from .pricesTemplate import PricesTemplate
from io import BytesIO


class DetailsKyly():
    def __init__(self, file: BytesIO, names: DataFrame, prices_list: DataFrame) -> None:
        self.file: str = file
        self.names: DataFrame = names
        self.prices_list: DataFrame = prices_list
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

        self.prices: PricesTemplate = PricesTemplate(
            self.file, Constants.KYLY
        )

        self.prices_base: DataFrame = self.prices.prices
        self.prices_original: DataFrame = self.prices.prices_original

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

        if not 'MARCA' in details.columns:
            details['MARCA'] = details[
                ['REFERENCIA']
            ].apply(
                self.add_brand,
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

        details = details[
            (~details['CANTIDAD'].isna()) &
            (details['CANTIDAD'] != 0)
        ].reset_index(
            drop=True
        )

        details['MARCA'] = details['MARCA'].map(
            Constants.CODE_BRANDS
        )

        details = pd.merge(
            left=details,
            right=self.prices_base,
            on='ref',
            how='left'
        )

        if details['PRECIO'].isna().count() > 0:
            details['TIPO TALLA'] = details['TALLA'].map(
                Constants.KYLY_SIZES_TYPE
            )

            self.prices_original['TIPO TALLA'] = self.prices_original['TALLA'].map(
                Constants.KYLY_SIZES_TYPE
            )

            self.prices_original.rename(
                columns={'PRECIO': 'PRECIO ESTIMADO'},
                inplace=True
            )

            self.prices_original = self.prices_original.groupby(
                ['REFERENCIA', 'TIPO TALLA'], as_index=False,
            ).agg({'PRECIO ESTIMADO': 'mean'})

            details = pd.merge(
                left=details,
                right=self.prices_original,
                on=['REFERENCIA', 'TIPO TALLA'],
                how='left'
            )

            details['PRECIO'] = details['PRECIO'].fillna(
                details['PRECIO ESTIMADO']
            )

        if details['PRECIO'].isna().count() > 0:
            details: DataFrame = pd.merge(
                left=details,
                right=self.prices_list[['ref', 'PRECIO LISTA']],
                on='ref',
                how='left'
            )

            details['PRECIO'] = details['PRECIO'].fillna(
                details['PRECIO LISTA']
            )

        self.details = details.drop(
            columns=[
                'PRECIO LISTA', 'TIPO TALLA', 'PRECIO ESTIMADO'
            ],
            errors='ignore'
        )

    def add_name(self, x, names: List[str]) -> str:
        '''
            return name to reference

            Parameters
            ----------
            x: List
                0: Reference
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

    def add_brand(self, x, names: List[str]) -> str:
        '''
            return brand to reference

            Parameters
            ----------
            x: List
                0: Reference
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
            collection: str = df_temp.iloc[0, :]['Colección']
            return Constants.KYLY_BRANDS[collection[0]]

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
            return Constants.FEMALE_DAME
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
