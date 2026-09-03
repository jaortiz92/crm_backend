"""
Budget Module - ETL Templates

Processes Excel files from the accounting system and transforms them
into structured data for bulk insertion into the budget module tables.

Supported files:
- CostosFinal.xlsx -> actual_costs
- LibroAuxiliarCECO.xlsx -> actual_expenses
- EstadoCuenta306090.xlsx -> accounts_receivable (snapshot ETL, header=3)
- Recibos.xlsx -> payment_ledger (SIIGO auxiliares: cash-flow & adjustments)

Uses pandas + openpyxl for data cleansing and transformation.
"""

# Python
import re
from datetime import date
from io import BytesIO
from typing import Dict, List, Optional, Any, Tuple

# Pandas
import pandas as pd
from pandas.core.frame import DataFrame
import numpy as np

# SQLAlchemy
from sqlalchemy import func
from sqlalchemy.orm import Session

# App models (for relational mapping)
from app.models.reference import Reference as ReferenceModel
from app.models.brand import Brand as BrandModel
from app.models.budget.costCenter import CostCenter as CostCenterModel
from app.models.invoice import Invoice as InvoiceModel
from app.models.order import Order as OrderModel
from app.models.customerTrip import CustomerTrip as CustomerTripModel
from app.models.customer import Customer as CustomerModel
from app.models.contact import Contact as ContactModel
from app.models.city import City as CityModel
from app.models.department import Department as DepartmentModel

# App CRUD & schemas
import app.crud as crud
from app.models.budget.actualCost import ActualCost as ActualCostModel
from app.models.budget.accountReceivable import (
    AccountReceivable as AccountReceivableModel,
    ReceivableStatusEnum,
)
from app.models.budget.paymentLedger import PaymentLedger as PaymentLedgerModel
from app.schemas.budget import ActualCostCreate


class BudgetTemplates:
    """
    ETL processor for budget-related Excel files.

    Each method handles a specific file type, applying the necessary
    data cleansing rules (header omission, column renaming, type casting)
    and returning a structured DataFrame ready for bulk insertion.
    """

    # Payment ledger (Recibos.xlsx) nature classification (§6.4)
    CASH_PREFIXES = {"RC", "CE"}
    NON_CASH_PREFIXES = {"NC", "NO", "DMC"}
    INITIAL_BALANCE_PREFIXES = {"SI"}
    # Ordered by precedence: first candidate that resolves wins (§3.2a)
    DOC_CANDIDATE_PATTERNS = [
        r"VENTA\s+(\d{3,7})",
        r"\bFV\s+(\d{3,7})",
        r"\bFE\s+(\d{3,7})",
        r"\bDSC\s+(\d{3,7})",
        r"\bDMC\s+(\d{3,7})",
        r"\bNC\s+(\d{3,7})",
    ]

    # Accounts receivable snapshot aging: ordered cascade over Excel range
    # columns (BR-6); first bucket != 0 wins, all-zero -> NULL. The accented
    # name 'Más De 90' is the literal header (never 'Mas De 90').
    AR_AGING_BUCKETS = [
        ('Por Vencer', 'current'),
        ('1 A 30', '1_to_30'),
        ('31 A 60', '31_to_60'),
        ('61 A 90', '61_to_90'),
        ('Más De 90', 'over_90'),
    ]

    def __init__(self, file: BytesIO) -> None:
        self.file: BytesIO = file
        self.df: Optional[DataFrame] = None
        # Payment ledger ETL detail counters
        self.total_rows_raw: int = 0
        self.rows_excluded_totals: int = 0
        self.rows_excluded_documents: int = 0
        self.rows_excluded_initial_balances: int = 0
        self.rows_skipped_null: int = 0
        self.rows_non_numeric_movement: int = 0
        self.rows_with_document_candidate: int = 0
        self.invoices_imputed: int = 0
        self.documents_not_imputed: int = 0
        self.payment_ledger_replacement_receipts: List[str] = []
        # Accounts receivable (Estado de Cuenta) ETL counters
        self.ar_rows_excluded_subtotals: int = 0
        self.ar_contact_fallback_resolved: int = 0   # rows resolved via contacts (D-4)
        self.ar_legacy_debt_records: int = 0         # rows with id_invoice NULL (A-5)
        self.ar_rows_closed: int = 0                 # rows marked PAID (D-2)
        self.ar_statement_date: Optional[date] = None  # parsed cutoff (guard + response)
        self.ar_forced: bool = False                 # stale-cutoff guard bypassed via force

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
    # (snapshot ETL: reemplazo atómico por documento +
    #  cierre por marcaje PAID de deuda desaparecida)
    # ──────────────────────────────────────────────

    def _parse_statement_cutoff(self) -> date:
        """
        Parse the statement cutoff date embedded in row 2 of the Excel
        ("... fecha de corte DD/MM/YYYY"). Requires a light header=None
        read; the BytesIO is rewound afterwards for the main read.

        Raises:
            HTTPException 400 when no cutoff can be parsed (BR-8).
        """
        from fastapi import HTTPException, status as http_status

        raw = pd.read_excel(self.file, engine='openpyxl', header=None, nrows=3)
        self.file.seek(0)

        match = re.search(
            r'fecha de corte\s+(\d{1,2}/\d{1,2}/\d{4})',
            str(raw.iloc[1, 0]),
            re.IGNORECASE,
        )
        if not match:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No statement cutoff date found in file (expected "
                    "'... fecha de corte DD/MM/YYYY' in row 2)"
                ),
            )
        return pd.to_datetime(match.group(1), format='%d/%m/%Y').date()

    def process_accounts_receivable(self) -> DataFrame:
        """
        Fase A: process EstadoCuenta306090.xlsx (limpieza, sin DB).

        Steps:
        1. Parse cutoff date from row 2 (BR-8) -> self.ar_statement_date
        2. Read Excel with header=3
        3. Drop subtotal rows without Doc (BR-1)
        4. Build document_number = Doc + Num without spaces, UPPERCASE (BR-2)
        5. Extract numeric identification root (BR-3)
        6. Cast dates and numeric columns (Valor Total keeps negatives, A-2)

        Returns:
            DataFrame with cleaned detail rows ready for relational mapping
        """
        from fastapi import HTTPException, status as http_status

        self.ar_statement_date = self._parse_statement_cutoff()

        self.df = pd.read_excel(
            self.file,
            engine="openpyxl",
            header=3,
        )
        self.total_rows_raw = len(self.df)

        # BR-1: subtotal rows (per customer/branch) carry no Doc
        doc_text = self.df['Doc'].astype(str).str.strip()
        subtotal_mask = self.df['Doc'].isna() | doc_text.isin(['', 'nan'])
        self.ar_rows_excluded_subtotals = int(subtotal_mask.sum())
        self.df = self.df[~subtotal_mask].copy()

        # BR-2: "FV" + "FE 1544" -> "FVFE1544" (null Num -> Doc only), stored
        # uppercase per stakeholder rule (e.g. "rc2468" -> "RC2468")
        doc = self.df['Doc'].astype(str).str.strip()
        num = self.df['Num'].astype(str).str.strip()
        self.df['document_number'] = (
            (doc + ' ' + num).where(num != 'nan', doc)
            .str.replace(r'\s+', '', regex=True)
            .str.upper()
        )

        # BR-3: first digit run drops the NIT/CC prefix and check digit
        self.df['identification_root'] = (
            self.df['Identificacion'].astype(str).str.extract(r'(\d+)')[0]
        )

        # Type casts ('Más De 90' referenced with its exact accented name)
        self.df['Fecha Vence'] = pd.to_datetime(
            self.df['Fecha Vence'], errors='coerce'
        ).dt.date
        self.df['Valor Total'] = pd.to_numeric(
            self.df['Valor Total'], errors='coerce'
        )
        for bucket_col, _ in self.AR_AGING_BUCKETS:
            self.df[bucket_col] = pd.to_numeric(self.df[bucket_col], errors='coerce')

        if self.df.empty:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No valid detail rows found (all rows were subtotals "
                    "or the file structure changed)"
                ),
            )

        return self.df

    def _map_accounts_receivable_relational_data(self, db: Session) -> DataFrame:
        """
        Fase B: map foreign keys and derived columns (batch queries only).

        - id_customer: customers.document first, fallback contacts.document
          assigning contact.id_customer, never id_contact (BR-4/D-4);
          contact resolution never filters by active.
        - id_invoice: exact invoice_number match; multi-installment keeps the
          lowest key (BR-5/A-3); miss -> NULL (legacy debt, A-5).
        - aging_bucket: ordered cascade over the Excel range columns (BR-6).
        - customer_document / identification_original: traceability for every
          row regardless of resolution (D-1).
        """
        # Step 1: batch customers.document lookup (roots as float)
        roots = {
            float(r) for r in self.df['identification_root'].dropna().unique()
        }
        customer_map: Dict[float, int] = {}
        if roots:
            customer_map = {
                document: id_customer
                for id_customer, document in db.query(
                    CustomerModel.id_customer, CustomerModel.document
                ).filter(CustomerModel.document.in_(list(roots))).all()
            }

        # Step 2: fallback contacts.document for roots missing in customers
        contact_map: Dict[float, int] = {}
        missing_roots = list(roots - set(customer_map))
        if missing_roots:
            contact_map = {
                document: id_customer
                for id_customer, document in db.query(
                    ContactModel.id_customer, ContactModel.document
                ).filter(ContactModel.document.in_(missing_roots)).all()
                if id_customer is not None
            }

        def resolve_customer(root) -> Tuple[Optional[int], bool]:
            if root is None or (isinstance(root, float) and pd.isna(root)):
                return None, False
            key = float(root)
            if key in customer_map:
                return customer_map[key], False
            if key in contact_map:
                return contact_map[key], True
            return None, False

        resolved = [resolve_customer(r) for r in self.df['identification_root']]
        self.df['id_customer'] = [pair[0] for pair in resolved]
        self.ar_contact_fallback_resolved = sum(1 for pair in resolved if pair[1])

        # Step 3: invoices by normalized document_number (min key per number)
        docs = self.df['document_number'].unique().tolist()
        invoice_form_map: Dict[str, Tuple[int, int]] = {}
        if docs:
            rows = db.query(
                InvoiceModel.invoice_number,
                InvoiceModel.key,
                InvoiceModel.id_invoice,
            ).filter(InvoiceModel.invoice_number.in_(docs)).all()
            for row in rows:
                previous = invoice_form_map.get(row.invoice_number)
                if previous is None or row.key < previous[0]:
                    invoice_form_map[row.invoice_number] = (row.key, row.id_invoice)

        self.df['id_invoice'] = self.df['document_number'].map(
            lambda d: invoice_form_map[d][1] if d in invoice_form_map else None
        )
        self.ar_legacy_debt_records = int(self.df['id_invoice'].isna().sum())

        # Step 4: aging cascade over the Excel snapshot columns (BR-6)
        masks = [self.df[col].fillna(0) != 0 for col, _ in self.AR_AGING_BUCKETS]
        choices = [bucket for _, bucket in self.AR_AGING_BUCKETS]
        self.df['aging_bucket'] = np.select(masks, choices, default=None)

        # Step 5: snapshot traceability (D-1)
        self.df['customer_document'] = self.df['identification_root'].astype(float)
        ident = self.df['Identificacion']
        self.df['identification_original'] = (
            ident.astype(str).str.strip().where(ident.notna(), None)
        )

        return self.df

    def _validate_accounts_receivable_integrity(
        self, db: Session, force: bool = False
    ) -> None:
        """
        Fase C1: blocking validations before any write (A-10).

        V1: rows without id_customer -> 400 with structured listing (BR-10)
        V2: invalid Fecha Vence -> 400
        V4: non-numeric Valor Total -> 400
        V3: stale-cutoff guard (BR-9/D-3): file cutoff older than stored
            MAX(statement_date) -> 400 unless force=true (sets self.ar_forced).
        Equal or newer cutoff is always allowed (reload idempotency).
        """
        from fastapi import HTTPException, status as http_status

        # V1: unresolvable customers abort the whole upload
        missing = self.df[self.df['id_customer'].isna()]
        if not missing.empty:
            missing_identifications: List[str] = []
            examples: List[Dict[str, Any]] = []
            for root in missing['identification_root'].unique():
                label = str(root) if pd.notna(root) else 'identificacion sin digitos'
                missing_identifications.append(label)
                group = (
                    missing[missing['identification_root'].isna()]
                    if pd.isna(root)
                    else missing[missing['identification_root'] == root]
                )
                examples.append({
                    "identification": label,
                    "customer_name": str(group['Nombres'].iloc[0]),
                    "documents": group['document_number'].unique().tolist(),
                })
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": (
                        "Customers not found in catalog (checked "
                        "customers.document and contacts.document)"
                    ),
                    "missing_count": len(missing),
                    "missing_identifications": missing_identifications,
                    "examples": examples[:20],
                },
            )

        # V2: unparseable due dates
        invalid_dates = self.df[self.df['Fecha Vence'].isna()]
        if not invalid_dates.empty:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"{len(invalid_dates)} records have invalid dates",
            )

        # V4: non-numeric amounts
        invalid_amounts = self.df[self.df['Valor Total'].isna()]
        if not invalid_amounts.empty:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"{len(invalid_amounts)} records have non-numeric amounts",
            )

        # V3: stale statement guard (before any write happens)
        stored_cutoff = db.query(
            func.max(AccountReceivableModel.statement_date)
        ).scalar()
        if self.ar_statement_date and stored_cutoff:
            if self.ar_statement_date < stored_cutoff:
                if not force:
                    raise HTTPException(
                        status_code=http_status.HTTP_400_BAD_REQUEST,
                        detail={
                            "message": (
                                f"Stale statement file: cutoff "
                                f"{self.ar_statement_date.isoformat()} is "
                                f"older than stored cutoff "
                                f"{stored_cutoff.isoformat()}. Marking "
                                f"documents as paid would produce false "
                                f"closures. Re-send with force=true to "
                                f"override."
                            ),
                            "file_cutoff": self.ar_statement_date.isoformat(),
                            "stored_cutoff": stored_cutoff.isoformat(),
                        },
                    )
                self.ar_forced = True

    def _handle_accounts_receivable_duplicates(self, db: Session) -> int:
        """
        Fase C2: atomic replace by document_number. Existing rows (OPEN and
        PAID) for the documents found in the file are deleted within the same
        transaction as the subsequent bulk insert (no commit here); their
        payment_ledger pointers are nullified by the CRUD helper (FK has no
        ondelete).

        Returns:
            Number of records deleted (rows, not documents; 0 if no duplicates)
        """
        docs = self.df['document_number'].unique().tolist()
        return crud.delete_accounts_receivable_by_documents(db, docs)

    def _close_settled_accounts_receivable(
        self, db: Session, document_numbers: List[str]
    ) -> int:
        """
        Fase C3: snapshot-sync closures (D-2). OPEN documents absent from the
        newest statement are marked PAID with their balance consumed
        (paid_amount = previous balance, balance = 0). PAID/PARTIAL rows and
        aging_bucket/statement_date are preserved for audit. No commit here.

        Returns:
            Number of rows closed
        """
        closed = crud.close_accounts_receivable_not_in(db, document_numbers)
        self.ar_rows_closed = closed
        return closed

    def _bulk_insert_accounts_receivable(
        self, db: Session, source_filename: str
    ) -> list:
        """
        Fase D: convert DataFrame rows to AccountReceivableCreate records and
        perform the bulk insert (BR-7). This is the only commit of the
        request; any later exception triggers db.rollback() in the endpoint.
        """
        from app.schemas.budget import AccountReceivableCreate

        def optional_int(value: Any) -> Optional[int]:
            if value is None or pd.isna(value):
                return None
            return int(value)

        def optional_float(value: Any) -> Optional[float]:
            if value is None or pd.isna(value):
                return None
            return float(value)

        def optional_text(value: Any) -> Optional[str]:
            if value is None or pd.isna(value):
                return None
            return str(value)

        records = []
        for _, row in self.df.iterrows():
            total_amount = float(row['Valor Total'])
            records.append(AccountReceivableCreate(
                id_customer=optional_int(row['id_customer']),
                id_invoice=optional_int(row['id_invoice']),
                document_number=str(row['document_number']),
                due_date=row['Fecha Vence'],
                total_amount=total_amount,
                paid_amount=0,
                balance=total_amount,
                status='OPEN',
                aging_bucket=optional_text(row['aging_bucket']),
                source_file=source_filename,
                customer_document=optional_float(row['customer_document']),
                identification_original=optional_text(row['identification_original']),
                statement_date=self.ar_statement_date,
            ))

        return crud.create_accounts_receivable_bulk(db, records)

    # ──────────────────────────────────────────────
    # Recibos.xlsx -> Payment Ledger (cash-flow ETL)
    # ──────────────────────────────────────────────

    def process_payment_ledger(
        self, include_initial_balances: bool = False
    ) -> DataFrame:
        """
        Process Recibos.xlsx (SIIGO auxiliares export) for payment ledger rows.

        Phase A (data cleansing):
        1. Read Excel (sheet 0) and ffill hierarchy columns
        2. Normalize receipt_number and derive document prefix
        3. Filter by transaction nature (RC/CE -> CASH, NC/NO/DMC -> NON_CASH,
           SI -> only if include_initial_balances; FV/FC/otros excluded)
        4. payment_amount = Movimiento * -1 (bank's perspective) for all rows
        5. cash_flow direction only for CASH rows (NULL for NON_CASH or 0)
        6. Drop kept rows with null Movimiento/Fecha (rows_skipped_null)

        Returns:
            DataFrame with cleaned payment ledger columns
        """
        self.df = pd.read_excel(
            self.file,
            engine="openpyxl",
            sheet_name=0,
        )
        self.total_rows_raw = len(self.df)

        # Flatten hierarchy: carry third-party context to every detail row
        for col in ('Nombres', 'Empresa', 'Tipo de Cuenta'):
            self.df[col] = self.df[col].ffill()

        # Normalize receipt number: strip + collapse inner whitespace, derive
        # the prefix from the first token, then remove every non-alphanumeric
        # char for storage ("RC  - 3017" -> "RC3017").
        receipt = (
            self.df['IdCuentaContableDocumento'].astype(str).str.strip()
            .str.replace(r'\s+', ' ', regex=True)
        )
        receipt = receipt.where(receipt != 'nan', '')
        self.df['prefix'] = receipt.str.split(' ').str[0].fillna('')
        self.df['receipt_number'] = receipt.str.replace(
            r'[^0-9A-Za-z]', '', regex=True
        )

        cash_mask = self.df['prefix'].isin(self.CASH_PREFIXES)
        non_cash_mask = self.df['prefix'].isin(self.NON_CASH_PREFIXES)
        si_mask = self.df['prefix'].isin(self.INITIAL_BALANCE_PREFIXES)
        empty_mask = receipt == ''
        keep_mask = cash_mask | non_cash_mask | (si_mask & include_initial_balances)

        # Atomic replacement scope (D10): every ledger-related receipt found
        # in the file (CASH/NON_CASH/SI prefixes), regardless of the flag.
        # The file "owns" SI receipts even when include_initial_balances is
        # False, so re-uploading without the flag reverts previously
        # included saldo-initial rows instead of leaving them orphaned.
        ledger_related_mask = cash_mask | non_cash_mask | si_mask
        self.payment_ledger_replacement_receipts = (
            self.df.loc[ledger_related_mask, 'receipt_number'].unique().tolist()
        )

        # Exclusion counters (for upload response details)
        self.rows_excluded_totals = int(empty_mask.sum())
        self.rows_excluded_initial_balances = int((si_mask & ~keep_mask).sum())
        self.rows_excluded_documents = int(
            (~empty_mask & ~si_mask & ~keep_mask).sum()
        )

        self.df = self.df[keep_mask].copy()

        # Nature from prefix only (never from Tipo de Cuenta, D9)
        self.df['transaction_nature'] = np.where(
            self.df['prefix'].isin(self.CASH_PREFIXES),
            'CASH',
            'NON_CASH_ADJUSTMENT',
        )

        # Skip kept rows with null Movimiento/Fecha; flag non-numeric ones
        raw_movement = self.df['Movimiento']
        movement_num = pd.to_numeric(raw_movement, errors='coerce')
        null_movement = raw_movement.isna() | (
            raw_movement.astype(str).str.strip().isin(['', 'nan'])
        )
        null_date = self.df['Fecha'].isna()
        skip_mask = null_movement | null_date
        self.rows_skipped_null = int(skip_mask.sum())
        self.df = self.df[~skip_mask].copy()

        # Signed bank-view amount (D4/D5): inversion applies to every row
        self.df['payment_amount'] = pd.to_numeric(
            self.df['Movimiento'], errors='coerce'
        ) * -1.0
        self.rows_non_numeric_movement = int(self.df['payment_amount'].isna().sum())

        # Direction only for CASH rows; 0-amount CASH rows stay NULL
        is_cash = self.df['transaction_nature'] == 'CASH'
        amount = self.df['payment_amount']
        self.df['cash_flow'] = np.select(
            [is_cash & (amount > 0), is_cash & (amount < 0)],
            ['in', 'out'],
            default=None,
        )

        self.df['payment_date'] = pd.to_datetime(
            self.df['Fecha'], errors='coerce'
        ).dt.date

        # accounting_account: first token of Cuenta (same rule as actual expenses)
        cuenta = self.df['Cuenta'].astype(str).str.split(' ', n=1).str[0].str.strip()
        self.df['accounting_account'] = cuenta.where(cuenta != 'nan', '')

        self.df['description'] = self.df['Concepto'].where(
            self.df['Concepto'].notna(), None
        )
        self.df['third_party'] = self.df['Nombres'].where(
            self.df['Nombres'].notna(), None
        )

        return self.df

    @staticmethod
    def _extract_doc_candidates(description: Any) -> List[str]:
        """
        Extract affected-document candidates from a Concepto text (D6/D7).

        A number is a candidate only when it immediately follows a marker
        (VENTA, FV, FE, DSC, DMC, NC). Months/years without marker are
        never candidates. Candidates are returned in pattern-precedence
        order, deduplicated by first occurrence.
        """
        if description is None or (isinstance(description, float) and pd.isna(description)):
            return []
        text = str(description).upper()
        candidates: List[str] = []
        for pattern in BudgetTemplates.DOC_CANDIDATE_PATTERNS:
            for match in re.finditer(pattern, text):
                number = match.group(1)
                if number not in candidates:
                    candidates.append(number)
        return candidates

    def _map_payment_ledger_relational_data(self, db: Session) -> DataFrame:
        """
        Phase B: impute affected document (id_invoice) and optional customer.

        - Candidates extracted from description with ordered marker regexes.
        - Validated in batch against invoices using normalized forms
          {str(n), "FVFE"+n} (same convention as the cost ETL's
          _clean_document). First candidate that resolves wins; when an
          invoice_number has multiple installment rows, link the lowest key.
        - id_customer: only for RC rows, exact upper/trim match against
          Customer.company_name. Never blocks.
        - id_account_receivable stays NULL (left to manual CRUD).
        """
        self.df['_candidates'] = self.df['description'].apply(
            self._extract_doc_candidates
        )
        self.rows_with_document_candidate = int(
            (self.df['_candidates'].str.len() > 0).sum()
        )

        # Batch validation against invoices (no per-row queries)
        all_forms = set()
        for candidates in self.df['_candidates']:
            for number in candidates:
                all_forms.add(number)
                all_forms.add(f"FVFE{number}")

        invoice_form_map: Dict[str, Tuple[int, int]] = {}
        if all_forms:
            rows = db.query(
                InvoiceModel.invoice_number,
                InvoiceModel.key,
                InvoiceModel.id_invoice,
            ).filter(
                InvoiceModel.invoice_number.in_(list(all_forms))
            ).all()
            for row in rows:
                previous = invoice_form_map.get(row.invoice_number)
                if previous is None or row.key < previous[0]:
                    invoice_form_map[row.invoice_number] = (row.key, row.id_invoice)

        def resolve_invoice(candidates: List[str]) -> Optional[int]:
            for number in candidates:
                hits = [
                    invoice_form_map[form]
                    for form in (number, f"FVFE{number}")
                    if form in invoice_form_map
                ]
                if hits:
                    return min(hits)[1]
            return None

        self.df['id_invoice'] = self.df['_candidates'].apply(resolve_invoice)
        self.invoices_imputed = int(self.df['id_invoice'].notna().sum())
        self.documents_not_imputed = (
            self.rows_with_document_candidate - self.invoices_imputed
        )

        # Optional non-blocking customer link, RC rows only (D11)
        self.df['id_account_receivable'] = None
        self.df['id_customer'] = None
        rc_mask = self.df['prefix'] == 'RC'
        if rc_mask.any():
            customer_map: Dict[str, int] = {}
            for id_customer, company_name in db.query(
                CustomerModel.id_customer, CustomerModel.company_name
            ).all():
                name_key = str(company_name or '').strip().upper()
                if name_key and name_key not in customer_map:
                    customer_map[name_key] = id_customer

            def match_customer(third_party: Any) -> Optional[int]:
                if third_party is None or pd.isna(third_party):
                    return None
                return customer_map.get(str(third_party).strip().upper())

            self.df.loc[rc_mask, 'id_customer'] = self.df.loc[
                rc_mask, 'third_party'
            ].apply(match_customer)

        return self.df

    def _validate_payment_ledger_integrity(self, db: Session) -> None:
        """
        Phase C: blocking validations for the payment ledger ETL.

        1. Empty receipt_number -> 400 (whole rejection)
        2. Invalid payment_date -> 400 "N records have invalid dates"
        3. Non-numeric Movimiento -> 400 (whole rejection)

        Non-blocking issues (candidates without invoice, third_party
        without customer) are only reported via counters.
        """
        from fastapi import HTTPException, status as http_status

        empty_receipts = self.df[
            self.df['receipt_number'].isna() | (self.df['receipt_number'] == '')
        ]
        if not empty_receipts.empty:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"{len(empty_receipts)} records have empty receipt_number",
            )

        invalid_dates = self.df[self.df['payment_date'].isna()]
        if not invalid_dates.empty:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=f"{len(invalid_dates)} records have invalid dates",
            )

        if self.rows_non_numeric_movement > 0:
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{self.rows_non_numeric_movement} records have "
                    f"non-numeric Movimiento"
                ),
            )

    def _handle_payment_ledger_duplicates(self, db: Session) -> int:
        """
        Atomic replace by receipt_number (D10): delete existing rows whose
        receipt_number appears in the file, within the same transaction as
        the subsequent bulk insert (no commit here, caller controls it).
        If the insert fails, a rollback restores the deleted records.

        The deletion scope is the set of ledger-related receipts found in
        the raw file (computed in process_payment_ledger), independent of
        include_initial_balances, so an upload without the flag also
        purges SI rows previously ingested with it.

        Returns:
            Number of records deleted (0 if no duplicates)
        """
        receipts = self.payment_ledger_replacement_receipts
        if not receipts:
            receipts = self.df['receipt_number'].unique().tolist()
        if not receipts:
            return 0

        return crud.delete_payment_ledger_by_receipts(db, receipts)

    def _bulk_insert_payment_ledger(self, db: Session, source_filename: str) -> list:
        """
        Phase D: convert DataFrame rows to PaymentLedgerCreate records and
        perform the bulk insert. Transaction is atomic (all-or-nothing).
        """
        from app.schemas.budget import PaymentLedgerCreate

        def optional_text(value: Any) -> Optional[str]:
            if value is None or pd.isna(value):
                return None
            return str(value)

        def optional_int(value: Any) -> Optional[int]:
            if value is None or pd.isna(value):
                return None
            return int(value)

        records = []
        for _, row in self.df.iterrows():
            records.append(PaymentLedgerCreate(
                receipt_number=str(row['receipt_number']),
                transaction_nature=str(row['transaction_nature']),
                cash_flow=optional_text(row['cash_flow']),
                payment_date=row['payment_date'],
                payment_amount=float(row['payment_amount']),
                accounting_account=str(row['accounting_account']),
                description=optional_text(row['description']),
                third_party=optional_text(row['third_party']),
                id_account_receivable=optional_int(row['id_account_receivable']),
                id_customer=optional_int(row['id_customer']),
                id_invoice=optional_int(row['id_invoice']),
                source_file=source_filename,
            ))

        return crud.create_payment_ledger_bulk(db, records)

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
        DEPRECATED: sin uso desde el ETL de accounts_receivable (spec 02_08).
        Sus valores (current/30/60/90+) no corresponden al vocabulario de
        snapshot; el aging ahora se declara via AR_AGING_BUCKETS (BR-6).

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
