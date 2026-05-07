from flask import Blueprint, jsonify, request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.finance_service import (
    get_finance_pending as get_finance_pending_service,
    get_finance_summary as get_finance_summary_service,
)
from utils.decorators import admin_required
from utils.validation import validate_payload


admin_finance_bp = Blueprint("admin_finance", __name__)


class FinancePendingQuerySchema(BaseModel):
    """GET query schema：保留向下相容，未提供 limit 時不限制筆數。"""

    model_config = ConfigDict(extra="ignore")

    limit: int | None = Field(default=None, ge=1, le=5000)

    @field_validator("limit", mode="before")
    @classmethod
    def empty_limit_as_none(cls, value):
        if value == "":
            return None
        return value


class FinanceSummaryQuerySchema(BaseModel):
    """目前 summary 無查詢參數，保留 Schema 讓 Controller 結構一致。"""

    model_config = ConfigDict(extra="ignore")


@admin_finance_bp.route("/api/admin/finance/pending")
@admin_required(roles=["super_admin", "finance"])
def get_finance_pending():
    """Controller 只負責驗證 request、呼叫 Service、回傳 response。"""
    query = validate_payload(FinancePendingQuerySchema, request.args.to_dict(flat=True))
    results = get_finance_pending_service(limit=query.limit)
    return jsonify(results)


@admin_finance_bp.route("/api/admin/finance/summary")
@admin_required(roles=["super_admin", "finance"])
def get_finance_summary():
    """Controller 只負責 API 邊界，不直接寫 aggregation。"""
    validate_payload(FinanceSummaryQuerySchema, request.args.to_dict(flat=True))
    summary = get_finance_summary_service()
    return jsonify(summary)
