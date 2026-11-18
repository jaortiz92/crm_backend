"""
Utility seed scripts (fase 3 del despliegue §4.8 de cada spec).

Hasta BE-S11 no existía directorio de seeds: las tablas nuevas se crean
con ``Base.metadata.create_all`` y el catálogo/parámetros se cargan con
scripts idempotentes ejecutables como módulo, p. ej.

    python -m app.utils.seeds.laborCostSeed

Idempotencia por NATURAL KEY (nunca por id): correr el seed dos veces
no duplica filas ni pisa ediciones previas (NFR-03: los parámetros se
editan solo vía PUT /budget/labor-params y el seed jamás hace UPDATE).
"""
