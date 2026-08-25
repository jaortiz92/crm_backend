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
from typing import Dict, List, Optional, Any

# Pandas
import pandas as pd
from pandas.core.frame import DataFrame
import numpy as np


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

    def process_costos_final(self) -> DataFrame:
        """
        Process CostosFinal.xlsx for actual cost records.

        Reads the Excel file, cleans column names, maps codigo_ceco
        to cost center references, and returns a structured DataFrame.

        Returns:
            DataFrame with columns: codigo_ceco, cost_date, cost_type,
            description, amount
        """
        self.df = pd.read_excel(
            BytesIO(self.file),
            engine="openpyxl",
        )
        self._clean_column_names()
        self._cast_numeric_columns(["amount"])
        self._cast_date_columns(["cost_date"])
        return self.df

    # ──────────────────────────────────────────────
    # LibroAuxiliarCECO.xlsx -> Actual Expenses
    # ──────────────────────────────────────────────

    def process_libro_auxiliar_ceco(self) -> DataFrame:
        """
        Process LibroAuxiliarCECO.xlsx for actual expense records.

        Reads the Excel file, maps codigo_ceco to cost center references,
        and returns a structured DataFrame.

        Returns:
            DataFrame with columns: codigo_ceco, expense_date, expense_type,
            description, amount
        """
        self.df = pd.read_excel(
            BytesIO(self.file),
            engine="openpyxl",
        )
        self._clean_column_names()
        self._cast_numeric_columns(["amount"])
        self._cast_date_columns(["expense_date"])
        return self.df

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
            BytesIO(self.file),
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
            BytesIO(self.file),
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
            BytesIO(self.file),
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
            BytesIO(self.file),
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
            BytesIO(self.file),
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
