import pathlib
import os


class Paths:
    PATH = (
        pathlib.Path().joinpath('app').joinpath('utils')
        .joinpath('process_details').joinpath('data')
    )
    # IN
    PATH_INTERIM = PATH.joinpath('interim')

    FILE_NAMES_CHILD: str = PATH_INTERIM.joinpath(
        'Consolidado_Nombres_Kyly.xlsx'
    ).resolve()

    FILE_NAMES_AND_PRICES_DAME: str = PATH_INTERIM.joinpath(
        'Consolidado_Nombres_y_Precios_Dama.xlsx'
    ).resolve()

    FILE_PRICES: str = PATH_INTERIM.joinpath(
        'Precios_Kyly.xlsx'
    ).resolve()
