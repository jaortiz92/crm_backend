from typing import Dict, List


class Constants():

    COLUMNS_CUSTOMERS: Dict[str, str] = {
        "Compañía": "company_name",
        "Documento": "document",
        "Correo": "email",
        "Telefono": "phone",
        "TipoDeTienda": "id_store_type",
        "Direccion": "address",
        "Vendedor": "id_seller",
        "Ciudad": "id_city",
        "Tiendas": "stores",
        "LimiteDeCredito": "credit_limit",
        "ConDocumentos": "with_documents",
        "Activo": "active",
        "Detalles": "relevant_details",
        "RedesSociales": "social_media",
    }

    COLUMNS_CUSTOMER_TRIPS: Dict[str, str] = {
        "id": "id_customer_trip",
        "Documento": "id_customer",
        "Vendedor": "id_seller",
        "Coleccion": "id_collection",
        "ConPresupuesto": "with_budget",
        "PresupuestoValor": "budget",
        "PresupuestoCantidad": "budget_quantities",
        "ViajeCerrado": "closed",
        "Comentario": "comment",
    }
