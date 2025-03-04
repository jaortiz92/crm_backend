from pandas.core.frame import DataFrame
from .constants import Constants
from .detailsInvoice import DetailsInvoice
from io import BytesIO


class ProcessDetailsInvoice():
    def __init__(
        self, file_details: BytesIO,
        id: int,
    ) -> None:
        self.file_details: BytesIO = file_details
        self.id: int = id
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
        self.details: DataFrame = DetailsInvoice(
            self.file_details
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
        final_details: DataFrame = self.details.copy()

        final_details['id_invoice'] = self.id

        self.final_details = final_details.rename(
            columns=Constants.COLUMNS_NAMES
        )[Constants.COLUMNS_INVOICE]
