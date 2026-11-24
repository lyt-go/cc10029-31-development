"""拒收回执领域服务：维护校验与对账环节被拒收记录的拒收原因归档与退回回执。

本模块在校验核对发现差异或在冲突裁决后对不满足质量要求的记录进行拒收处置，
创建拒收记录、归档拒收原因、生成退回回执并记录处置时间。
"""
from __future__ import annotations

import time
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class RejectRecordService(BaseModuleService):
    MODULE = "reject_record"
    ENTITY = "拒收记录"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["拒收编号", "批次编号", "记录主键", "拒收环节", "拒收原因", "回执编号", "退回目标", "处置时间"]
    REQUIRED_FIELDS = ["拒收编号", "批次编号", "记录主键"]
    STATUS_ORDER = ["草稿", "待处置", "已退回", "已丢弃"]
    ACTION_RULES = {"提交处置": "待处置", "确认退回": "已退回", "标记丢弃": "已丢弃"}
    NEGATIVE_ACTIONS = ["标记丢弃"]

    def create_rejection(
        self,
        batch_code: str,
        stage: str,
        reason: str,
        record_key: str = "",
    ) -> dict[str, Any]:
        """创建拒收记录：在校验或对账环节对不满足质量要求的批次创建拒收，归档原因与回执。"""
        reject_code = f"REJE-{batch_code}-{int(time.time() * 1000)}-{len(store.rows(self.MODULE))}"
        values = {
            "拒收编号": reject_code,
            "批次编号": batch_code,
            "记录主键": record_key or f"PK_REJ_{batch_code}",
            "拒收环节": stage,
            "拒收原因": reason,
            "回执编号": f"RC-{reject_code}",
            "退回目标": f"SOURCE_{batch_code}",
            "处置时间": time.strftime("%Y-%m-%d", time.localtime(time.time())),
        }
        entry, missing = self.create_entry(values)
        if entry is None:
            raise ValueError(f"创建拒收记录失败: {missing}")
        # 写入拒收日志
        self._write_jsonl(
            self._data_dir("events") / "reject_log.jsonl",
            [{"action": "reject", "reject_code": reject_code, "batch_code": batch_code,
              "stage": stage, "reason": reason, "at": time.time()}]
        )
        return {"reject_code": reject_code, "reject_id": entry["id"], "batch_code": batch_code,
                "stage": stage, "reason": reason}

    def process_rejection(self, reject_id: int, decision: str = "return") -> dict[str, Any]:
        """处置拒收记录：按退回或丢弃决定处理不满足质量要求的条目并写入处置产物。

        本方法实现数据交换平台的质量防线：对不合格数据执行退回（返回源端修复）
        或丢弃（标记废弃），并生成处置产物文件供下游追溯。
        """
        reject_entry = self.get_entry(reject_id)
        if reject_entry is None:
            return {"error": f"拒收记录 {reject_id} 不存在"}

        entry, msg = self.run_action(reject_id, "提交处置")
        if entry is None:
            return {"error": msg, "reject_id": reject_id}

        reject_code = reject_entry["拒收编号"]
        if decision == "return":
            entry["处置时间"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time()))
            final_entry, _ = self.run_action(reject_id, "确认退回")
            result_action = "已退回"
        else:
            final_entry, _ = self.run_action(reject_id, "标记丢弃")
            result_action = "已丢弃"

        # 写入处置产物文件
        disposition_file = self._data_dir("dispositions") / f"{reject_code}_disposition.jsonl"
        self._write_jsonl(disposition_file, [{
            "reject_code": reject_code,
            "batch_code": reject_entry["批次编号"],
            "decision": decision,
            "stage": reject_entry["拒收环节"],
            "result": result_action,
            "processed_at": time.time(),
        }])

        return {
            "reject_code": reject_code,
            "decision": decision,
            "result": result_action,
        }

    def get_pending_rejections(self, batch_code: str = "") -> list[dict[str, Any]]:
        """获取待处置的拒收记录列表，支持按批次过滤。"""
        rows = [r for r in store.rows(self.MODULE) if r.get("status") == "待处置"]
        if batch_code:
            rows = [r for r in rows if batch_code in r.get("批次编号", "")]
        return rows

    def query_rejections_with_mapping(self, reason: str, batch_code: str = "") -> dict[str, Any]:
        """按拒收原因查询待处置拒收回执，并关联字段契约的字段映射明细。

        一份筛选结果同时带回原拒收原因和产生拒收时实际使用的映射版本，
        作为补转换筛选入口，供操作员核对后生成待重新映射记录清单。
        """
        remap_svc = self._safe_import(
            "app.services.remap_worklist", "RemapWorklistService")()
        reject_rows = [
            row for row in store.rows(self.MODULE)
            if row.get("status") == "待处置"
            and reason.casefold() in str(row.get("拒收原因", "")).casefold()
            and (not batch_code or batch_code in str(row.get("批次编号", "")))
        ]
        contracts = store.rows("field_contract")
        items = []
        for row in reject_rows:
            contract = remap_svc._match_contract(contracts, row, {})
            items.append({
                "拒收编号": row.get("拒收编号", ""),
                "批次编号": row.get("批次编号", ""),
                "记录主键": row.get("记录主键", ""),
                "拒收环节": row.get("拒收环节", ""),
                "拒收原因": row.get("拒收原因", ""),
                "回执编号": row.get("回执编号", ""),
                "契约编号": contract.get("契约编号", ""),
                "源字段": contract.get("源字段", ""),
                "目标字段": contract.get("目标字段", ""),
                "数据类型": contract.get("数据类型", ""),
                "转换规则": contract.get("转换规则", ""),
                "映射版本": contract.get("契约版本", "v1.0"),
            })
        return {"reason": reason, "total": len(items), "items": items}

    def create_remap_worklist(self, reason: str, batch_code: str = "") -> dict[str, Any]:
        """拒收回执侧入口：按原因筛选并生成待重新映射记录清单（与字段契约共享）。"""
        remap_svc = self._safe_import(
            "app.services.remap_worklist", "RemapWorklistService")()
        return remap_svc.build_worklist(reason, batch_code)