"""
UploadStatus Schemas
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class DatasetUploadStatus(BaseModel):
    last_upload: Optional[datetime] = None


class UploadStatusResponse(BaseModel):
    actual_costs: DatasetUploadStatus
    actual_expenses: DatasetUploadStatus
    payment_ledger: DatasetUploadStatus
    accounts_receivable: DatasetUploadStatus
