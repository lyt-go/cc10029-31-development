"""待重新映射补转换专用路由：拒收回执与字段契约共享清单的查询、补发、领用与补转换入口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.field_contract import FieldContractService
from app.services.reject_record import RejectRecordService
from app.services.remap_worklist import RemapWorklistService

router = APIRouter(prefix="/api", tags=["待重新映射补转换"])


class WorklistBuildPayload(BaseModel):
    reason: str
    batch_code: str = ""


class ContractRevisePayload(BaseModel):
    contract_code: str
    new_rule: str
    new_version: str
    data_type: str = ""


class CorrectionPayload(BaseModel):
    worklist_code: str
    corrections: list[dict[str, Any]] = Field(default_factory=list)


class ClaimPayload(BaseModel):
    worklist_code: str
    record_keys: list[str] | None = None


class ReconversionPayload(BaseModel):
    worklist_code: str
    target_contract_version: str = ""
    record_keys: list[str] | None = None


# -- 拒收回执侧入口：按原因查询回执与字段映射明细 --

@router.get("/reject_record/rejections/by-reason")
def query_rejections_by_reason(reason: str, batch_code: str = "") -> dict[str, Any]:
    """按拒收原因筛选待处置回执，并返回关联的字段映射明细与实际映射版本。"""
    return RejectRecordService().query_rejections_with_mapping(reason, batch_code)


@router.post("/reject_record/remap-worklist")
def build_worklist_from_rejection(payload: WorklistBuildPayload) -> dict[str, Any]:
    """拒收回执侧生成待重新映射记录清单。"""
    return RejectRecordService().create_remap_worklist(payload.reason, payload.batch_code)


# -- 字段契约侧入口：共享同一份清单 --

@router.post("/field_contract/revise")
def revise_contract_rule(payload: ContractRevisePayload) -> dict[str, Any]:
    """字段契约增加新规则版本，旧版本废弃，补转换按新版本执行。"""
    return FieldContractService().revise_contract_rule(
        payload.contract_code, payload.new_rule, payload.new_version, payload.data_type)


@router.get("/field_contract/remap-worklist")
def get_worklist_from_contract(worklist_code: str) -> dict[str, Any]:
    """字段契约侧读取共享的待重新映射记录清单。"""
    return FieldContractService().get_remap_worklist(worklist_code)


# -- 共享清单：查询、补发、领用、补转换、剩余拒收 --

@router.get("/remap_worklist")
def list_worklist(
    worklist_code: str = "",
    status: str = "",
    remaining: bool = False,
) -> dict[str, Any]:
    """查询待重新映射记录清单，可按清单批次、状态过滤，remaining=true 只看剩余拒收项。"""
    svc = RemapWorklistService()
    items = svc.list_worklist(
        worklist_code=worklist_code, item_status=status, only_remaining=remaining)
    return {"worklist_code": worklist_code, "total": len(items), "items": items}


@router.post("/remap_worklist/corrections")
def receive_corrections(payload: CorrectionPayload) -> dict[str, Any]:
    """接收源端补发的更正记录，按记录主键回填清单。"""
    return RemapWorklistService().receive_corrections(
        payload.worklist_code, payload.corrections)


@router.post("/remap_worklist/claim")
def claim_scope(payload: ClaimPayload) -> dict[str, Any]:
    """领用清单范围内可补转的条目；已补转记录不会被重复领用。"""
    return RemapWorklistService().claim_scope(payload.worklist_code, payload.record_keys)


@router.post("/remap_worklist/reconvert")
def run_reconversion(payload: ReconversionPayload) -> dict[str, Any]:
    """按领用范围执行补转换，写出补转换产物与剩余拒收数据。"""
    return RemapWorklistService().run_reconversion(
        payload.worklist_code,
        target_contract_version=payload.target_contract_version,
        record_keys=payload.record_keys,
    )


@router.get("/remap_worklist/remaining")
def get_remaining(worklist_code: str) -> dict[str, Any]:
    """查询剩余拒收数据（源端尚未补发更正的条目），供源端继续处理。"""
    return RemapWorklistService().remaining_rejections(worklist_code)


@router.get("/remap_worklist/converted-keys")
def get_converted_keys(worklist_code: str = "") -> dict[str, Any]:
    """查询已成功补转的转换键索引，核对实际转换键与映射版本。"""
    rows = RemapWorklistService().converted_index(worklist_code)
    return {"worklist_code": worklist_code, "total": len(rows), "items": rows}
