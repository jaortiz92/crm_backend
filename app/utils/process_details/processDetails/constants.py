from typing import Dict, List


class Constants():
    OTHERS_FILES: List[str] = ['Original.xlsx']
    SHEET_TO_JOB: str = 'PEDIDO'

    # Gender
    FEMALE_CHILD: int = 2  # 'F'
    MALE_CHILD: int = 1  # 'M'
    FEMALE_DAME: int = 2  # 'F'
    UNISEX: int = 0  # 'U'

    CHILD: str = 'child'
    DAME: str = 'dame'

    NANAI: str = 'NANAI'
    KYLY: str = 'KYLY'
    LEMON: str = 'LEMON'
    AMORA: str = 'AMORA'
    MILON: str = 'MILON'
    BAGORAZ: str = 'BAGORAZ'
    KALISSON: str = 'KALISSON'
    LE_CABESTAN: str = 'LE CABESTAN'
    TINTA_BRAND: str = 'TINTA'
    BARILOCHE: str = 'BARILOCHE'

    DAME_BRANDS: List[str] = [
        BAGORAZ, KALISSON, LE_CABESTAN, TINTA_BRAND, BARILOCHE
    ]

    CHILD_BRANDS: List[str] = [
        NANAI, KYLY, LEMON, AMORA, MILON,
    ]

    CODE_BRANDS: Dict[str, int] = {
        KYLY: 1,
        MILON: 2,
        LEMON: 3,
        AMORA: 4,
        NANAI: 5,
        TINTA_BRAND: 6,
        BARILOCHE: 7,
        BAGORAZ: 8,
        KALISSON: 9,
    }

    COLUMNS_NAMES_DAME: List[str] = {
        'DESCRIPCIÓN': 'REFERENCIA COMPLETA',
        'PRECIO POR MAYOR': 'PRECIO'
    }

    COLUMNS_NAMES: List[str] = {
        'REFERENCIA': 'product',
        'REFERENCIA COMPLETA': 'description',
        'MARCA': 'id_brand',
        'GENERO': 'gender',
        'COLOR': 'color',
        'TALLA': 'size',
        'PRECIO': 'unit_value',
        'CANTIDAD': 'quantity',
        'DESCUENTO': 'discount',
        'TOTAL SIN IVA': 'value_without_tax',
        'TOTAL': 'value_with_tax',
    }

    COLUMNS_ORDER: List[str] = [
        'id_order',
        'product',
        'description',
        'id_brand',
        'gender',
        'color',
        'size',
        'unit_value',
        'quantity',
        'value_without_tax',
        'value_with_tax',
    ]

    COLUMNS_INVOICE: List[str] = [
        'product',
        'description',
        'id_brand',
        'gender',
        'color',
        'size',
        'unit_value',
        'quantity',
        'discount',
        'value_without_tax',
        'value_with_tax',
    ]
