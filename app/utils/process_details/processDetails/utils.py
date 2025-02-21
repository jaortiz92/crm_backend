import logging
import os
import re
from typing import List
from .constants import Constants
from re import Match
import pandas as pd
from pandas.core.frame import DataFrame
from pandas.core.series import Series
from datetime import date


class Utils():

    @classmethod
    def read_file_orders(cls, logger: logging.Logger) -> List[str]:
        '''
        This function read files in path to job and return a list with file names

        Parameters
        ----------
        logger: logging.Logger
            Logger instance to show errors

        Returns
        -------
        List:
            List with file names to job
        '''
        files_in: List[str] = os.listdir(Constants.IN)
        files_to_job: List[str] = []

        for file in files_in:
            if (
                (re.match('.*xlsx', file) or re.match('.*xlsm', file)) and
                not re.match('.*\$.*', file) and
                file not in [
                    Constants.PRICES,
                    Constants.NAMES
                ] + Constants.OTHERS_FILES
            ):
                if Constants.SHEET_TO_JOB in pd.ExcelFile(Constants.IN + file).sheet_names:
                    files_to_job.append(file)
                else:
                    logger.warning('Archivo no contiene la hoja (' +
                                   Constants.SHEET_TO_JOB + '): "' + file + '"')

        return files_to_job

    @classmethod
    def separate_ref(cls, x: Series) -> List[List[str]]:
        '''
        This function takes string and return list with reference ans size

        Parameters
        ----------
        x: Series
            Series with reference and preces united

        Returns
        -------
        List[List[str]]:
            List with reference ans size
        '''
        reference: List = []
        size: List = []
        for value in x.values:
            match: Match = re.match('(.*)-(.*)', value)
            reference.append(match.group(1))
            size.append(match.group(2))
        return reference, size

    @classmethod
    def to_excel(cls, dfs: List[DataFrame], name_sheets: List[str], name_file: str) -> None:
        '''
        Save tables in excel

        Parameters
        ----------
        dfs: List[DataFrame]
            Tables to save
        name_sheets: List[str]
            Names of table's sheets 
        name_file: str
            Name for the file

        Returns
        -------
        None
        '''
        writer = pd.ExcelWriter(
            '{}{}'.format(
                Constants.OUT, name_file), datetime_format='dd-mm-yy'
        )
        for df, sheet in zip(dfs, name_sheets):
            df.to_excel(
                writer,
                sheet_name=sheet,
                index=False
            )
        writer.close()

    @classmethod
    def generate_a_new_name(cls, name: str) -> str:
        '''
        Generate a new name to save tebles

        Parameters
        ----------
        name: str
            old file name

        Returns
        -------
        str:
            New name to save tables
        '''
        match: Match = re.match('(.*)(\.xlsx)', name)
        if not match:
            match: Match = re.match('(.*)(\.xlsm)', name)
        return match.group(1) + ' CON FACTURA ' + date.today().strftime('%y%m%d') + '.xlsx'

    @classmethod
    def to_excel_report_stock(cls, df: DataFrame) -> None:
        '''
        Save tables in excel

        Parameters
        ----------
        df: DataFrame
            Table to save

        Returns
        -------
        None
        '''
        writer = pd.ExcelWriter(
            Constants.REPORT_STOCK
        )

        df.to_excel(
            writer,
            index=False
        )
        writer.close()
