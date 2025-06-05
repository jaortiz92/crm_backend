import pandas as pd
from pandas.core.frame import DataFrame
from .constants import Constants
from io import BytesIO


class CustomersTemplate:
    def __init__(
        self, file: BytesIO,
    ) -> None:
        self.file: BytesIO = file
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
            usecols="A:N",
            sheet_name="Plantilla",
            dtype={
                "Telefono": str,
                "Direccion": str,
                "Documento": int,
                "Ciudad": str,
                "Vendedor": str,
                "TipoDeTienda": str
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
            columns=Constants.COLUMNS_CUSTOMERS,
            inplace=True
        )

        self.customers.dropna(
            subset="company_name",
            inplace=True, ignore_index=True
        )

        string_columns = [
            "company_name", "email", "id_seller",
            "id_store_type", "id_city", "address"
        ]
        for col in string_columns:
            self.customers[col] = self.customers[col].astype("string")

        self.customers["company_name"] = self.customers["company_name"].str.upper()
        self.customers["email"] = self.customers["email"].str.lower()
        self.customers["id_seller"] = self.customers["id_seller"].str.lower()
        self.customers["id_store_type"] = self.customers["id_store_type"].str.title()
        self.customers["id_city"] = self.customers["id_city"].str.upper()
        self.customers["address"] = self.customers["address"].str.upper()
