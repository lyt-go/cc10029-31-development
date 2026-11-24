"""领域服务注册表：通用资源路由按模块 key 分派到独立业务服务。"""
from __future__ import annotations

from app.services.base import BaseModuleService
from app.services.source_register import SourceRegisterService
from app.services.target_register import TargetRegisterService
from app.services.field_contract import FieldContractService
from app.services.extract_window import ExtractWindowService
from app.services.transfer_batch import TransferBatchService
from app.services.staging_area import StagingAreaService
from app.services.checksum_verify import ChecksumVerifyService
from app.services.arrival_reconcile import ArrivalReconcileService
from app.services.conflict_resolve import ConflictResolveService
from app.services.resume_point import ResumePointService
from app.services.speed_control import SpeedControlService
from app.services.reject_record import RejectRecordService
from app.services.remap_worklist import RemapWorklistService
from app.services.format_adapt import FormatAdaptService
from app.services.transfer_lineage import TransferLineageService
from app.services.history_archive import HistoryArchiveService
from app.services.exchange_replay import ExchangeReplayService
from app.services.sla_monitor import SlaMonitorService
from app.services.channel_config import ChannelConfigService

SERVICES: dict[str, BaseModuleService] = {
    "source_register": SourceRegisterService(),
    "target_register": TargetRegisterService(),
    "field_contract": FieldContractService(),
    "extract_window": ExtractWindowService(),
    "transfer_batch": TransferBatchService(),
    "staging_area": StagingAreaService(),
    "checksum_verify": ChecksumVerifyService(),
    "arrival_reconcile": ArrivalReconcileService(),
    "conflict_resolve": ConflictResolveService(),
    "resume_point": ResumePointService(),
    "speed_control": SpeedControlService(),
    "reject_record": RejectRecordService(),
    "remap_worklist": RemapWorklistService(),
    "format_adapt": FormatAdaptService(),
    "transfer_lineage": TransferLineageService(),
    "history_archive": HistoryArchiveService(),
    "exchange_replay": ExchangeReplayService(),
    "sla_monitor": SlaMonitorService(),
    "channel_config": ChannelConfigService(),
}


def service_for(module: str) -> BaseModuleService | None:
    return SERVICES.get(module)
