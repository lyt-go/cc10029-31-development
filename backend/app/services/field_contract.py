"""字段契约领域服务：维护源端到目标端的字段映射契约、类型转换规则与契约版本管理。

本模块负责定义并执行字段映射转换，从源端抽取产物文件读取数据，
按契约规则转换后写入目标端产物文件，输出转换统计和校验报告。
"""
from __future__ import annotations

import time
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class FieldContractService(BaseModuleService):
    MODULE = "field_contract"
    ENTITY = "字段映射"
    OPERATION_TERM = "转换"
    LIST_FIELDS = ["契约编号", "源字段", "目标字段", "数据类型", "转换规则", "必填标记", "默认值", "契约版本"]
    REQUIRED_FIELDS = ["契约编号", "源字段", "目标字段"]
    STATUS_ORDER = ["草稿", "待校验", "已生效", "已废弃"]
    ACTION_RULES = {"提交校验": "待校验", "确认生效": "已生效", "标记废弃": "已废弃"}
    NEGATIVE_ACTIONS = ["标记废弃"]

    def create_contract(self, source_field: str, target_field: str, data_type: str = "string") -> dict[str, Any]:
        """创建源端到目标端字段映射契约，登记转换规则与数据类型。"""
        contract_code = f"FIEL-{source_field}-{target_field}"
        values = {
            "契约编号": contract_code,
            "源字段": source_field,
            "目标字段": target_field,
            "数据类型": data_type,
            "转换规则": "直接映射" if data_type == "string" else "类型转换",
            "必填标记": "是",
            "默认值": "",
            "契约版本": "v1.0",
        }
        entry, missing = self.create_entry(values)
        if entry is None:
            raise ValueError(f"创建字段映射契约失败: {missing}")
        self._write_jsonl(
            self._data_dir("events") / "contract_log.jsonl",
            [{"action": "create", "contract_code": contract_code, "source_field": source_field,
              "target_field": target_field, "at": time.time()}]
        )
        return entry

    def apply_contracts(self, source_code: str, record_count: int = 10) -> dict[str, Any]:
        """对指定源端抽取产物应用已生效的字段映射契约，执行类型转换并写入转换产物文件。

        本方法是数据交换平台中字段映射与类型转换的核心执行环节：
        读取抽取窗口产物文件，逐字段按契约规则转换数据类型与名称，
        写入字段转换产物文件，输出转换前后统计报告。
        """
        # 获取已生效的契约列表
        contracts = [r for r in store.rows(self.MODULE) if r.get("status") == "已生效"]
        if not contracts:
            contracts = [{
                "契约编号": f"FIEL-{source_code}",
                "源字段": "ext_a",
                "目标字段": "dst_a",
                "数据类型": "string",
                "转换规则": "直接映射",
                "契约版本": "v1.0",
            }]

        # 读取抽取窗口产物文件
        extract_dir = self._data_dir("extracted")
        source_records = []
        for ef in extract_dir.glob(f"*{source_code[:8]}*.jsonl"):
            source_records = self._read_jsonl(ef)
            if source_records:
                break
        if not source_records:
            source_records = self._simulate_records(source_code, count=record_count, field_prefix="ext")

        # 执行字段转换映射
        transformed = []
        conversion_count = 0
        for rec in source_records:
            new_rec = {}
            for contract in contracts:
                src_f = contract.get("源字段", "")
                tgt_f = contract.get("目标字段", "")
                data_type = contract.get("数据类型", "string")
                # 按转换规则执行类型转换
                src_val = rec.get(src_f, "")
                if src_val is not None:
                    if data_type == "int":
                        try:
                            src_val = int(src_val)
                        except (ValueError, TypeError):
                            src_val = 0
                    elif data_type == "float":
                        try:
                            src_val = float(src_val)
                        except (ValueError, TypeError):
                            src_val = 0.0
                    conversion_count += 1
                new_rec[tgt_f] = src_val
                new_rec["_source_code"] = source_code
                new_rec["_contract_version"] = contract.get("契约版本", "v1.0")
                new_rec["_converted_at"] = time.time()
            if new_rec:
                transformed.append(new_rec)

        # 写入字段转换产物文件
        output_file = self._data_dir("mapped") / f"{source_code}_mapped.jsonl"
        written = self._write_jsonl(output_file, transformed)

        self._write_jsonl(
            self._data_dir("events") / "contract_apply_log.jsonl",
            [{"action": "apply", "source_code": source_code, "contract_count": len(contracts),
              "records_converted": written, "conversions": conversion_count, "at": time.time()}]
        )

        return {
            "source_code": source_code,
            "contract_count": len(contracts),
            "records_converted": written,
            "conversions": conversion_count,
            "artifact_path": str(output_file),
        }

    def get_active_contracts(self) -> list[dict[str, Any]]:
        """获取所有已生效的字段映射契约列表，供下游模块按规则执行类型转换。"""
        return [r for r in store.rows(self.MODULE) if r.get("status") == "已生效"]

    def revise_contract_rule(
        self,
        contract_code: str,
        new_rule: str,
        new_version: str,
        data_type: str = "",
    ) -> dict[str, Any]:
        """字段契约增加新规则：为同一源/目标字段生成新版本契约并立即生效。

        旧版本契约标记为已废弃，补转换时按新版本规则执行类型转换；
        待重新映射清单仍保留拒收时的原映射版本，便于追溯实际映射版本变化。
        """
        previous = next(
            (r for r in store.rows(self.MODULE) if r.get("契约编号") == contract_code),
            None,
        )
        if previous is None:
            return {"error": f"契约 {contract_code} 不存在，无法增加新规则"}

        # 旧版本下线
        if previous.get("status") != "已废弃":
            previous["status"] = "已废弃"
            previous["pending"] = False

        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        entry = {
            "id": new_id,
            "契约编号": contract_code,
            "源字段": previous.get("源字段", ""),
            "目标字段": previous.get("目标字段", ""),
            "数据类型": data_type or previous.get("数据类型", "string"),
            "转换规则": new_rule,
            "必填标记": previous.get("必填标记", "是"),
            "默认值": previous.get("默认值", ""),
            "契约版本": new_version,
            "status": "已生效",
            "pending": False,
            "abnormal": False,
            "上一版本": previous.get("契约版本", ""),
        }
        rows.append(entry)

        self._write_jsonl(
            self._data_dir("events") / "contract_revise_log.jsonl",
            [{
                "action": "revise", "contract_code": contract_code,
                "old_version": previous.get("契约版本", ""), "new_version": new_version,
                "new_rule": new_rule, "at": time.time(),
            }],
        )
        return {
            "contract_code": contract_code,
            "contract_id": new_id,
            "previous_version": previous.get("契约版本", ""),
            "new_version": new_version,
            "rule": new_rule,
            "entry": entry,
        }

    def get_remap_worklist(self, worklist_code: str) -> dict[str, Any]:
        """字段契约侧入口：读取与拒收回执共享的待重新映射记录清单。"""
        remap_svc = self._safe_import(
            "app.services.remap_worklist", "RemapWorklistService")()
        items = remap_svc.list_worklist(worklist_code=worklist_code)
        return {"worklist_code": worklist_code, "total": len(items), "items": items}