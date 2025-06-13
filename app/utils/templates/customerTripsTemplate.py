import pandas as pd
from pandas.core.frame import DataFrame
import numpy as np
from .constants import Constants
from io import BytesIO


class CustomerTripsTemplate:
    def __init__(
        self, file: BytesIO,
        create: bool
    ) -> None:
        self.file: BytesIO = file
        self.create: bool = create
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
        self.customers: DataFrame = pd.read_excel(
            BytesIO(self.file),
            usecols="A:I",
            sheet_name="Plantilla",
            dtype={
                "Documento": int,
                "Vendedor": str,
                "Coleccion": str
            })

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
        self.customers.rename(
            columns=Constants.COLUMNS_CUSTOMER_TRIPS,
            inplace=True
        )

        if self.create:
            self.customers.dropna(
                subset="id_customer",
                inplace=True, ignore_index=True
            )

            self.customers["id_customer_trip"] = np.nan
        else:
            self.customers.dropna(
                subset="id_customer_trip",
                inplace=True, ignore_index=True
            )

        string_columns = [
            "id_seller",
        ]
        for col in string_columns:
            self.customers[col] = self.customers[col].astype("string")

        self.customers["id_seller"] = self.customers["id_seller"].str.lower()
