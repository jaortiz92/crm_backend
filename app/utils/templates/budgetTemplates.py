"""
Budget Module - ETL Templates

Processes Excel files from the accounting system and transforms them
into structured data for bulk insertion into the budget module tables.

Supported files:
- CostosFinal.xlsx -> actual_costs
- LibroAuxiliarCECO.xlsx -> actual_expenses
- EstadoCuenta306090.xlsx -> accounts_receivable (with skiprows=3)
- RecibosDePago.xlsx -> payment_ledger

Uses pandas + openpyxl for data cleansing and transformation.
"""

# Python
from io import BytesIO
from typing import Dict, List, Optional, Any, Tuple

# Pandas
import pandas as pd
from pandas.core.frame import DataFrame
import numpy as np

# SQLAlchemy
from sqlalchemy.orm import Session

# App models (for relational mapping)
from app.models.reference import Reference as ReferenceModel
from app.models.brand import Brand as BrandModel
from app.models.budget.costCenter import CostCenter as CostCenterModel
from app.models.invoice import Invoice as InvoiceModel
from app.models.order import Order as OrderModel
from app.models.customerTrip import CustomerTrip as CustomerTripModel
from app.models.customer import Customer as CustomerModel
from app.models.city import City as CityModel
from app.models.department import Department as DepartmentModel

# App CRUD & schemas
import app.crud as crud
from app.models.budget.actualCost import ActualCost as ActualCostModel
from app.schemas.budget import ActualCostCreate


class BudgetTemplates:
    """
    ETL processor for budget-related Excel files.

    Each method handles a specific file type, applying the necessary
    data cleansing rules (header omission, column renaming, type casting)
    and returning a structured DataFrame ready for bulk insertion.
    """

    def __init__(self, file: BytesIO) -> None:
        self.file: BytesIO = file
        self.df: Optional[DataFrame] = None

    # ──────────────────────────────────────────────
    # CostosFinal.xlsx -> Actual Costs
    # ──────────────────────────────────────────────

    def process_cost(self) -> DataFrame:
        """
        Process CostosFinal.xlsx for actual cost records.

        Steps:
        1. Read Excel with header=3, skipfooter=1
        2. Rename columns to standard names
        3. Clean document numbers (FV->FVFE, PND->NDCL, etc.)
        4. Extract product code from description
        5. Cast numeric and date columns
        6. Calculate amount = quantity * unit_cost

        Returns:
            DataFrame with cleaned and transformed data
        """
        self.df = pd.read_excel(
            self.file,
            engine="openpyxl",
            header=3,
            skipfooter=1
        ).rename(columns={
            'Doc': 'document_number',
            'CódigoInventario': 'description',
            'Unidades': 'quantity',
            'Costo Unitario': 'unit_cost',
            'Fecha': 'cost_date'
        })

        # Drop rows without document
        self.df.dropna(subset=['document_number'], inplace=True)

        # Clean document numbers
        self.df['document_number'] = self.df['document_number'].apply(
            self._clean_document
        )

        # Extract reference code from description (first word before space)
        self.df['reference_code'] = self.df['description'].apply(
            self._extract_reference_code
        )

        # Cast types
        self.df['quantity'] = pd.to_numeric(
            self.df['quantity'], errors='coerce'
        ).fillna(0).astype(int)
        self.df['unit_cost'] = pd.to_numeric(
            self.df['unit_cost'], errors='coerce'
        ).fillna(0.0)
        self.df['cost_date'] = pd.to_datetime(
            self.df['cost_date'], errors='coerce'
        ).dt.date
        self.df['amount'] = self.df['quantity'] * self.df['unit_cost']

        # Standardize text
        self.df['document_number'] = (
            self.df['document_number'].astype(str).str.strip()
        )
        self.df['reference_code'] = (
            self.df['reference_code'].astype(str).str.strip()
        )

        # Description is used only to extract reference_code, not persisted in bulk uploads
        self.df['description'] = None

        return self.df

    @staticmethod
    def _clean_document(x: str) -> str:
        """
        Clean document number following business rules:
        - FV + not FE -> FVFE + suffix
        - DMCDMC -> remove prefix
        - PND -> NDCL + suffix
        - PNC -> NCCL + suffix
        - M- -> remove prefix
        """
        value = str(x).replace(' ', '')
        if 'FV' in value and 'FE' not in value:
            value = 'FVFE' + value[2:]
        elif 'DMCDMC' in value:
            value = value[3:]
        elif 'PND' in value:
            value = 'NDCL{}'.format(value[7:])
        elif 'PNC' in value:
            value = 'NCCL{}'.format(value[7:])
        elif 'M-' in value:
            value = value[2:]
        return value

    @staticmethod
    def _extract_reference_code(description: str) -> str:
        """
        Extract product code from description field.
        Takes first word before space.
        Example: "REF123 Zapatilla Nike" -> "REF123"
        """
        if not description or pd.isna(description):
            return ""
        return str(description).split(' ')[0].strip()

    def _map_relational_data(self, db: Session) -> DataFrame:
        """
        Map Excel data to foreign keys:
        1. reference_code -> id_reference (from product_references)
        2. document_number -> id_zone (via invoice -> order -> customer_trip
           -> customer -> city -> department -> zone)
        3. id_zone + id_line + cost_center_code LIKE '00%' -> id_cost_center

        Returns:
            DataFrame with id_reference, id_cost_center added
        """
        # 1. Load reference map into memory: reference_code -> id_reference
        references_map = {
            ref.reference: ref.id_reference
            for ref in db.query(ReferenceModel).all()
        }

        # 2. Load invoice_number -> id_zone mapping into memory
        invoice_zone_map = self._load_invoice_zone_mapping(db)

        # 3. Load (id_zone, id_line) -> id_cost_center mapping
        cost_center_map = self._load_cost_center_mapping(db)

        # 4. Build a map: id_reference -> id_line (via brand)
        #    Batch approach: only query brands for references in our data
        needed_ref_ids = set(
            references_map[code]
            for code in self.df['reference_code'].unique()
            if code in references_map
        )
        ref_line_map = {}
        if needed_ref_ids:
            ref_brand_rows = db.query(
                ReferenceModel.id_reference,
                ReferenceModel.id_brand
            ).filter(
                ReferenceModel.id_reference.in_(needed_ref_ids)
            ).all()

            needed_brand_ids = set(
                r.id_brand for r in ref_brand_rows if r.id_brand
            )
            brand_line_map = {}
            if needed_brand_ids:
                brand_rows = db.query(
                    BrandModel.id_brand,
                    BrandModel.id_line
                ).filter(
                    BrandModel.id_brand.in_(needed_brand_ids)
                ).all()
                brand_line_map = {
                    b.id_brand: b.id_line for b in brand_rows
                }

            ref_line_map = {
                r.id_reference: brand_line_map.get(r.id_brand)
                for r in ref_brand_rows
            }

        # 5. Apply mappings to DataFrame
        self.df['id_reference'] = self.df['reference_code'].map(references_map)
        self.df['id_zone'] = self.df['document_number'].map(invoice_zone_map)
        self.df['id_line'] = self.df['id_reference'].map(ref_line_map)
        self.df['id_cost_center'] = self.df.apply(
            lambda row: self._find_cost_center(
                cost_center_map,
                row.get('id_zone'),
                row.get('id_line')
            ),
            axis=1
        )

        return self.df

    def _load_invoice_zone_mapping(self, db: Session) -> Dict[str, int]:
        """
        Load invoice_number -> id_zone mapping into memory.
        Query path: invoice -> order -> customer_trip -> customer
                    -> city -> department -> zone
        Only loads mappings for invoice_numbers present in the DataFrame.
        """
        doc_numbers = self.df['document_number'].unique().tolist()

        rows = db.query(
            InvoiceModel.invoice_number,
            DepartmentModel.id_zone
        ).join(
            OrderModel,
            OrderModel.id_order == InvoiceModel.id_order
        ).join(
            CustomerTripModel,
            CustomerTripModel.id_customer_trip == OrderModel.id_customer_trip
        ).join(
            CustomerModel,
            CustomerModel.id_customer == CustomerTripModel.id_customer
        ).join(
            CityModel,
            CityModel.id_city == CustomerModel.id_city
        ).join(
            DepartmentModel,
            DepartmentModel.id_department == CityModel.id_department
        ).filter(
            InvoiceModel.invoice_number.in_(doc_numbers)
        ).all()

        return {row.invoice_number: row.id_zone for row in rows}

    def _load_cost_center_mapping(self, db: Session) -> Dict[Tuple[int, int], int]:
        """
        Load (id_zone, id_line) -> id_cost_center mapping.
        Only includes active cost centers where code starts with '00'.
        """
        rows = db.query(CostCenterModel).filter(
            CostCenterModel.cost_center_code.like('00%'),
            CostCenterModel.is_active == True
        ).all()

        return {
            (cc.id_zone, cc.id_line): cc.id_cost_center
            for cc in rows
            if cc.id_zone is not None and cc.id_line is not None
        }

    @staticmethod
    def _find_cost_center(
        cost_center_map: Dict[Tuple[int, int], int],
        id_zone: Optional[int],
        id_line: Optional[int]
    ) -> Optional[int]:
        """Find cost center by (id_zone, id_line) combination."""
        if id_zone is None or id_line is None:
            return None
        if pd.isna(id_zone) or pd.isna(id_line):
            return None
        return cost_center_map.get((int(id_zone), int(id_line)))

    def _validate_data_integrity(
        self, db: Session, excel_total_cost: float
    ) -> None:
        """
        Validate data integrity before insertion:
        1. Check all references exist in catalog
        2. Check all cost centers were resolved
        3. Validate SUM(amount) matches Excel Total Cost (tolerance: 100)
        """
        from fastapi import HTTPException, status as http_status

        # 1. Missing references
        missing_refs = self.df[
            self.df['id_reference'].isna()
            & self.df['reference_code'].notna()
            & (self.df['reference_code'] != "")
            & (self.df['reference_code'] != "nan")
        ]['reference_code'].unique().tolist()

        if missing_refs:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"References not found in catalog: {missing_refs}"
            )

        # 2. Missing cost centers
        missing_cc = self.df[self.df['id_cost_center'].isna()]
        if not missing_cc.empty:
            error_details = []
            for _, row in missing_cc.head(10).iterrows():
                error_details.append({
                    "document_number": str(row['document_number']),
                    "reference_code": str(row['reference_code']),
                    "id_zone": row.get('id_zone'),
                    "id_line": row.get('id_line'),
                    "reason": (
                        "Cost center not found with filters: "
                        "id_zone + id_line + code LIKE '00%'"
                    )
                })
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": (
                        f"Could not resolve cost center for "
                        f"{len(missing_cc)} records"
                    ),
                    "examples": error_details[:10]
                }
            )

        # 3. Total amount validation (tolerance: 100)
        calculated_total = float(self.df['amount'].sum())
        if abs(calculated_total - excel_total_cost) > 100:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Total amount validation failed",
                    "excel_total": excel_total_cost,
                    "calculated_total": calculated_total,
                    "difference": abs(calculated_total - excel_total_cost),
                    "tolerance": 100
                }
            )

    def _handle_duplicate_documents(self, db: Session) -> int:
        """
        Detect if any document_number in the new file already exists in DB.
        If duplicates found, delete all existing records with those document_numbers.

        This deletion runs within the same transaction as the subsequent bulk insert.
        If the bulk insert fails, a rollback will restore the deleted records.

        Returns:
            Number of records deleted (0 if no duplicates)
        """
        new_document_numbers = self.df['document_number'].unique().tolist()

        existing_count = db.query(ActualCostModel).filter(
            ActualCostModel.document_number.in_(new_document_numbers)
        ).count()

        if existing_count == 0:
            return 0

        deleted_count = db.query(ActualCostModel).filter(
            ActualCostModel.document_number.in_(new_document_numbers)
        ).delete(synchronize_session=False)

        return deleted_count

    def _bulk_insert(
        self, db: Session, source_filename: str
    ) -> list:
        """
        Convert DataFrame to ActualCostCreate records and perform bulk insert.
        Transaction is atomic (all-or-nothing).
        """
        records = []
        for _, row in self.df.iterrows():
            id_ref = row.get('id_reference')
            if pd.isna(id_ref):
                id_ref = None
            else:
                id_ref = int(id_ref)

            cost_date = row['cost_date']
            if hasattr(cost_date, 'isoformat'):
                cost_date = cost_date.isoformat()

            records.append(ActualCostCreate(
                id_cost_center=int(row['id_cost_center']),
                document_number=str(row['document_number']),
                id_reference=id_ref,
                quantity=int(row['quantity']),
                unit_cost=float(row['unit_cost']),
                cost_date=cost_date,
                cost_type='invoice',
                amount=float(row['amount']),
                description=None,
                source_file=source_filename,
            ))

        return crud.create_actual_costs_bulk(db, records)

    # ──────────────────────────────────────────────
    # LibroAuxiliarCECO.xlsx -> Actual Expenses
    # ──────────────────────────────────────────────

    def process_actual_expenses(self) -> DataFrame:
        """
        Process LibroAuxiliarCECO.xlsx for actual expense records.

        Steps:
        1. Read Excel with header=3
        2. Drop rows without NumDoc
        3. Exclude rows with "Total" in CuentaContable
        4. Filter only expenses (CuentaContable starts with "5")
        5. Calculate amount = Débitos - Créditos
        6. Cast numeric and date columns

        Returns:
            DataFrame with cleaned and transformed data
        """
        self.df = pd.read_excel(
            self.file,
            engine="openpyxl",
            header=3,
        )
        self.total_rows_raw = len(self.df)

        # Drop rows without document number
        self.df.dropna(subset=['NumDoc'], inplace=True)
        self.df = self.df[self.df['NumDoc'].astype(str).str.strip() != '']

        # Exclude "Total" rows
        self.df = self.df[
            ~self.df['CuentaContable'].astype(str).str.contains('Total', case=False, na=False)
        ]

        # Filter only expenses (CuentaContable starts with "5")
        self.df = self.df[
            self.df['CuentaContable'].astype(str).str.startswith('5')
        ]

        # Calculate net amount
        self.df['amount'] = (
            pd.to_numeric(self.df['Débitos'], errors='coerce').fillna(0)
            - pd.to_numeric(self.df['Créditos'], errors='coerce').fillna(0)
        )

        # Extract accounting_account and expense_type from CuentaContable
        cuenta_split = self.df['CuentaContable'].astype(str).str.split(' ', n=1)
        self.df['accounting_account'] = cuenta_split.str[0].str.strip()
        self.df['expense_type'] = cuenta_split.str[1].fillna('').str.strip()

        # Cast dates
        self.df['expense_date'] = pd.to_datetime(
            self.df['Fecha'], errors='coerce'
        ).dt.date

        # Standardize text fields
        self.df['document_number'] = self.df['NumDoc'].astype(str).str.strip().str.replace(' ', '', regex=False)
        self.df['description'] = self.df['Notas'].where(
            self.df['Notas'].notna(), None
        )
        self.df['third_party_account'] = self.df['Cuenta Tercero'].where(
            self.df['Cuenta Tercero'].notna(), None
        )
        self.df['centro_costos_raw'] = self.df['CentroCostos'].astype(str).str.strip()

        return self.df

    def _map_actual_expenses_relational_data(self, db: Session) -> DataFrame:
        """
        Map CentroCostos names to id_cost_center FK.
        Excel contains cost center names (not codes).
        Applies fallback rules for empty CentroCostos using code-based lookup.
        """
        cost_centers = db.query(CostCenterModel).all()
        name_to_id = {cc.cost_center_name.strip(): cc.id_cost_center for cc in cost_centers}
        code_to_id = {cc.cost_center_code: cc.id_cost_center for cc in cost_centers}

        aliases = {
            'Comercial': 'Comercial General',
        }

        fallback_map = {
            '51': '410100',
            '52': '210700',
            '53': '510100',
            '54': '999100',
        }

        def resolve_cost_center(row):
            cc_raw = row['centro_costos_raw']
            if cc_raw == '' or cc_raw == 'nan' or pd.isna(row['CentroCostos']):
                prefix = row['accounting_account'][:2]
                fallback_code = fallback_map.get(prefix)
                if fallback_code:
                    return code_to_id.get(fallback_code)
                return None
            resolved = name_to_id.get(cc_raw)
            if resolved is None and cc_raw in aliases:
                resolved = name_to_id.get(aliases[cc_raw])
            return resolved

        self.df['cost_center_lookup'] = self.df.apply(resolve_cost_center, axis=1)
        self.df['id_cost_center'] = self.df['cost_center_lookup']

        return self.df

    def _validate_actual_expenses_integrity(self, db: Session) -> None:
        """
        Validate data integrity before insertion:
        1. Check all cost center codes exist in catalog
        2. Validate dates and amounts
        """
        from fastapi import HTTPException, status as http_status

        # 1. Missing cost centers
        missing_cc = self.df[self.df['id_cost_center'].isna()]
        if not missing_cc.empty:
            invalid_names = missing_cc['centro_costos_raw'].unique().tolist()
            error_details = []
            for name in invalid_names:
                affected_docs = (
                    missing_cc[missing_cc['centro_costos_raw'] == name]['document_number']
                    .unique().tolist()
                )
                error_details.append({
                    "cost_center_name": name,
                    "affected_documents": affected_docs[:10],
                    "total_affected": len(affected_docs),
                })
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": f"Cost centers not found in catalog: {invalid_names}",
                    "invalid_cost_centers": error_details,
                }
            )

        # 2. Invalid dates
        invalid_dates = self.df[self.df['expense_date'].isna()]
        if not invalid_dates.empty:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"{len(invalid_dates)} records have invalid dates"
            )

    def _handle_actual_expense_duplicates(self, db: Session) -> int:
        """
        Detect if any document_number in the new file already exists in DB.
        If duplicates found, delete all existing records with those document_numbers.

        This deletion runs within the same transaction as the subsequent bulk insert.
        If the bulk insert fails, a rollback will restore the deleted records.

        Returns:
            Number of records deleted (0 if no duplicates)
        """
        from app.models.budget.actualExpense import ActualExpense as ActualExpenseModel

        new_document_numbers = self.df['document_number'].unique().tolist()

        existing_count = db.query(ActualExpenseModel).filter(
            ActualExpenseModel.document_number.in_(new_document_numbers)
        ).count()

        if existing_count == 0:
            return 0

        deleted_count = db.query(ActualExpenseModel).filter(
            ActualExpenseModel.document_number.in_(new_document_numbers)
        ).delete(synchronize_session=False)

        return deleted_count

    def _bulk_insert_actual_expenses(self, db: Session, source_filename: str) -> list:
        """
        Convert DataFrame to ActualExpenseCreate records and perform bulk insert.
        Transaction is atomic (all-or-nothing).
        """
        from app.schemas.budget import ActualExpenseCreate

        records = []
        for _, row in self.df.iterrows():
            records.append(ActualExpenseCreate(
                id_cost_center=int(row['id_cost_center']),
                accounting_account=str(row['accounting_account']),
                expense_type=str(row['expense_type']),
                description=row.get('description'),
                amount=float(row['amount']),
                document_number=str(row['document_number']),
                expense_date=row['expense_date'],
                third_party_account=row.get('third_party_account'),
                source_file=source_filename,
            ))

        return crud.create_actual_expenses_bulk(db, records)

    # ──────────────────────────────────────────────
    # EstadoCuenta306090.xlsx -> Accounts Receivable
    # ──────────────────────────────────────────────

    def process_estado_cuenta(self) -> DataFrame:
        """
        Process EstadoCuenta306090.xlsx for accounts receivable.

        Applies skiprows=3 to omit header rows and correctly structure
        the DataFrame. Maps customer documents and aging buckets.

        Returns:
            DataFrame with columns: document_number, due_date, total_amount,
            paid_amount, balance, aging_bucket, id_customer
        """
        self.df = pd.read_excel(
            self.file,
            engine="openpyxl",
            skiprows=3,
        )
        self._clean_column_names()
        self._cast_numeric_columns(["total_amount", "paid_amount", "balance"])
        self._cast_date_columns(["due_date"])
        self._compute_aging_buckets()
        return self.df

    # ──────────────────────────────────────────────
    # RecibosDePago.xlsx -> Payment Ledger
    # ──────────────────────────────────────────────

    def process_recibos_de_pago(self) -> DataFrame:
        """
        Process RecibosDePago.xlsx for payment ledger records.

        Reads the Excel file, maps payment references to account
        receivables and collections.

        Returns:
            DataFrame with columns: document_number, payment_date,
            payment_amount, payment_method, reference_number, id_invoice
        """
        self.df = pd.read_excel(
            self.file,
            engine="openpyxl",
        )
        self._clean_column_names()
        self._cast_numeric_columns(["payment_amount"])
        self._cast_date_columns(["payment_date"])
        return self.df

    # ──────────────────────────────────────────────
    # Cost Centers Catalog
    # ──────────────────────────────────────────────

    def process_cost_centers(self) -> DataFrame:
        """
        Process a cost centers catalog Excel file.

        Returns:
            DataFrame with columns: cost_center_code, cost_center_name,
            id_department, id_line, description
        """
        self.df = pd.read_excel(
            self.file,
            engine="openpyxl",
        )
        self._clean_column_names()
        return self.df

    # ──────────────────────────────────────────────
    # Budget Plan Income (Formato Solicitud Presupuesto Ingresos.xlsx)
    # ──────────────────────────────────────────────

    def process_budget_plan_income(self) -> DataFrame:
        """
        Process income budget plan Excel template.

        Reads the Excel file with skiprows=7, maps cost center codes,
        collection short names, and computes payment_date from payment rules.

        Returns:
            DataFrame with columns: id_cost_center, budget_date, id_collection,
            projected_amount, description, line_type, behavior_type
        """
        self.df = pd.read_excel(
            self.file,
            engine="openpyxl",
            skiprows=7,
        )

        self._clean_column_names()  

        self.df["id_cost_center_code"] = (
            self.df["centro_de_costo"]
            .astype(str)
            .str.strip()
            .str.split()
            .str[0]
        )

        self.df["budget_date"] = pd.to_datetime(
            self.df["fecha_de_la_facturacion__proyectada_"], errors="coerce"
        ).dt.date

        self.df["short_collection_name"] = (
            self.df["temporada"]
            .astype(str)
            .str.strip()
        )

        self.df["projected_amount"] = pd.to_numeric(
            self.df["monto"], errors="coerce"
        ).fillna(0.0)

        self.df["description"] = self.df["observaciones_adicionales"].astype(str)

        self.df["line_type"] = "income"
        self.df["behavior_type"] = "fixed"


        return self.df

    # ──────────────────────────────────────────────
    # Budget Plan Expense (Formato Solicitud Presupuesto Gastos.xlsx)
    # ──────────────────────────────────────────────

    def process_budget_plan_expense(self) -> DataFrame:
        """
        Process expense budget plan Excel template.

        Reads the Excel file with skiprows=7, maps cost center codes,
        collection short names, translates behavior types, and applies
        conditional amount logic.

        Returns:
            DataFrame with columns: id_cost_center, budget_date, payment_date,
            description, id_collection, behavior_type, projected_amount,
            variable_rate, line_type
        """
        self.df = pd.read_excel(
            self.file,
            engine="openpyxl",
            skiprows=7,
        )
        self._clean_column_names()

        self.df["id_cost_center_code"] = (
            self.df["centro_de_costo"]
            .astype(str)
            .str.strip()
            .str.split()
            .str[0]
        )

        self.df["budget_date"] = pd.to_datetime(
            self.df["fecha_del_gasto__proyectada_"], errors="coerce"
        ).dt.date

        self.df["payment_date"] = pd.to_datetime(
            self.df["fecha_de_pago__proyectada_"], errors="coerce"
        ).dt.date

        self.df["description"] = self.df["concepto_del_gasto"].astype(str)

        self.df["short_collection_name"] = (
            self.df["temporada"]
            .astype(str)
            .str.strip()
        )

        behavior_map = {
            "Fijo": "fixed",
            "Variable por Facturación": "variable_sales",
            "Variable por Recaudo": "variable_receivables",
        }
        self.df["behavior_type"] = (
            self.df["comportamiento"]
            .astype(str)
            .str.strip()
            .map(behavior_map)
        )

        raw_amount = pd.to_numeric(
            self.df["monto_o_tasa_solicitado"], errors="coerce"
        ).fillna(0.0)

        self.df["projected_amount"] = raw_amount.where(
            self.df["behavior_type"] == "fixed", 0.0
        )
        self.df["variable_rate"] = raw_amount.where(
            self.df["behavior_type"] != "fixed", None
        )

        self.df["line_type"] = "expense"

        return self.df

    # ──────────────────────────────────────────────
    # Private Helper Methods
    # ──────────────────────────────────────────────

    def _clean_column_names(self) -> None:
        """
        Normalize column names: strip whitespace, convert to lowercase,
        replace spaces with underscores.
        """
        if self.df is not None:
            self.df.columns = (
                self.df.columns.str.strip()
                .str.lower()
                .str.replace(" ", "_")
                .str.replace("-", "_")
                .str.replace("(", "_")
                .str.replace(")", "_")
            )

    def _cast_numeric_columns(self, columns: List[str]) -> None:
        """Cast specified columns to numeric types, coercing errors to NaN."""
        if self.df is not None:
            for col in columns:
                if col in self.df.columns:
                    self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

    def _cast_date_columns(self, columns: List[str]) -> None:
        """Cast specified columns to datetime types."""
        if self.df is not None:
            for col in columns:
                if col in self.df.columns:
                    self.df[col] = pd.to_datetime(self.df[col], errors="coerce")

    def _compute_aging_buckets(self) -> None:
        """
        Compute aging buckets based on due_date vs current date.
        Creates an 'aging_bucket' column with values: current, 30, 60, 90+
        """
        if self.df is not None and "due_date" in self.df.columns:
            today = pd.Timestamp.today().normalize()
            days_overdue = (today - self.df["due_date"]).dt.days

            conditions = [
                days_overdue <= 0,
                (days_overdue > 0) & (days_overdue <= 30),
                (days_overdue > 30) & (days_overdue <= 60),
                (days_overdue > 60) & (days_overdue <= 90),
                days_overdue > 90,
            ]
            choices = ["current", "30", "60", "90", "90+"]
            self.df["aging_bucket"] = np.select(conditions, choices, default="unknown")

    def dataframe_to_records(self) -> List[Dict[str, Any]]:
        """
        Convert the current DataFrame to a list of dictionaries,
        replacing NaN/NaT values with None for database insertion.
        """
        if self.df is None:
            return []
        return self.df.replace({np.nan: None}).to_dict(orient="records")
