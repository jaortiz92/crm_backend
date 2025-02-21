import pathlib
import os


class Paths:
    PATH = (
        pathlib.Path().joinpath('app').joinpath('utils')
        .joinpath('process_details').joinpath('data')
    )
    # IN
    PATH_INTERIM = PATH.joinpath('interim')

    FILE_NAMES: str = PATH_INTERIM.joinpath(
        'Consolidado_precios.xlsx'
    ).resolve()

    FILE_PRICES: str = PATH_INTERIM.joinpath(
        'Precios.xlsx'
    ).resolve()
