"""待重新映射记录清单领域服务：连接拒收回执与字段契约的共享补转换工作台。

校验/对账环节拒收的记录会在此按拒收原因筛选并关联字段契约的字段映射明细，
生成一份可领用的待重新映射记录清单。源端补发的更正记录按记录主键回填，
操作员领用一个范围后执行补转换：

- 同一条记录补转成功后，转换键进入已转换索引，再次领用/补转不会多写一行；
- 补转换产物按领用范围写出成功记录，剩余未修正的拒收数据单独列出，
  供源端继续处理。

清单状态保存在内存 store 表 ``remap_worklist`` 中，转换键索引与各类产物
以 jsonl 文件持久化到 data 目录，保证跨进程仍可核对转换键。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 清单条目状态流转：待重新映射 → 已领用 → 已补转；源端未补发更正的条目保持待重新映射
STATUS_PENDING = "待重新映射"
STATUS_CLAIMED = "已领用"
STATUS_CONVERTED = "已补转"
WORKLIST_STATUS_ORDER = [STATUS_PENDING, STATUS_CLAIMED, STATUS_CONVERTED]


def build_conversion_key(record_key: str, contract_code: str, contract_version: str) -> str:
    """生成补转换幂等键：记录主键 + 实际字段契约编号 + 实际映射版本。"""
    return f"{record_key}|{contract_code}|{contract_version}"


class RemapWorklistService(BaseModuleService):
    """待重新映射记录清单服务，由拒收回执与字段契约两个模块共享。"""

    MODULE = "remap_worklist"
    ENTITY = "待重新映射记录"
    LIST_FIELDS = [
        "清单编号", "拒收编号", "批次编号", "记录主键", "拒收原因", "拒收环节",
        "契约编号", "源字段", "目标字段", "映射版本", "转换键", "清单状态",
    ]
    REQUIRED_FIELDS = ["清单编号", "拒收编号", "记录主键", "拒收原因"]
    STATUS_ORDER = WORKLIST_STATUS_ORDER

    def __init__(self) -> None:
        # 已转换键索引：进程内集合，启动时从持久化索引文件回填
        self._converted_keys: set[str] = set()
        self._index_loaded = False

    # -- 持久化索引 --

    def _index_file(self) -> Path:
        return self._data_dir("remap") / "converted_keys.jsonl"

    def _write_jsonl_snapshot(self, filepath: Path, records: list[dict[str, Any]]) -> int:
        """以覆盖方式写出 jsonl 快照，用于剩余拒收等每次执行都应反映当前状态的产物。"""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return len(records)

    def _load_converted_index(self) -> None:
        """从磁盘回填已转换键索引，保证跨进程的幂等判定仍然生效。"""
        if self._index_loaded:
            return
        for row in self._read_jsonl(self._index_file()):
            key = row.get("conversion_key")
            if key:
                self._converted_keys.add(key)
        self._index_loaded = True

    def is_converted(self, conversion_key: str) -> bool:
        """判断转换键是否已经成功补转。"""
        self._load_converted_index()
        return conversion_key in self._converted_keys

    # -- 清单构建与查询 --

    def build_worklist(
        self,
        reason: str,
        batch_code: str = "",
        *,
        contract_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """按拒收原因筛选待处置拒收回执，关联字段映射明细，生成待重新映射清单。

        筛选结果同时保留原拒收原因和产生拒收时实际使用的映射版本，
        一条拒收记录对应一条清单项，转换键在构建时即按原映射版本固化。
        """
        reject_rows = [
            row for row in store.rows("reject_record")
            if row.get("status") == "待处置"
            and reason.casefold() in str(row.get("拒收原因", "")).casefold()
            and (not batch_code or batch_code in str(row.get("批次编号", "")))
        ]
        if not reject_rows:
            return {
                "worklist_code": "",
                "reason": reason,
                "matched": 0,
                "items": [],
                "message": "未筛选到匹配该原因的待处置拒收记录",
            }

        contracts = store.rows("field_contract")
        worklist_code = f"REMAP-{int(time.time() * 1000)}"
        rows = store.rows(self.MODULE)
        next_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        items: list[dict[str, Any]] = []

        for reject in reject_rows:
            record_key = str(reject.get("记录主键", ""))
            contract = self._match_contract(contracts, reject, contract_overrides or {})
            contract_code = str(contract.get("契约编号", ""))
            contract_version = str(contract.get("契约版本", "v1.0"))
            conversion_key = build_conversion_key(record_key, contract_code, contract_version)
            entry = {
                "id": next_id,
                "清单编号": worklist_code,
                "拒收编号": reject.get("拒收编号", ""),
                "批次编号": reject.get("批次编号", ""),
                "记录主键": record_key,
                "拒收原因": reject.get("拒收原因", ""),
                "拒收环节": reject.get("拒收环节", ""),
                "契约编号": contract_code,
                "源字段": contract.get("源字段", ""),
                "目标字段": contract.get("目标字段", ""),
                "映射版本": contract_version,
                "转换键": conversion_key,
                "清单状态": STATUS_PENDING,
                "补发数据": None,
                "领用批次": "",
                "补转版本": "",
                "status": STATUS_PENDING,
                "pending": True,
                "abnormal": False,
            }
            rows.append(entry)
            items.append(dict(entry))
            next_id += 1

        self._write_jsonl(
            self._data_dir("remap") / "worklist_log.jsonl",
            [{
                "action": "build", "worklist_code": worklist_code, "reason": reason,
                "batch_code": batch_code, "matched": len(items), "at": time.time(),
            }],
        )
        return {
            "worklist_code": worklist_code,
            "reason": reason,
            "matched": len(items),
            "items": items,
        }

    def _match_contract(
        self,
        contracts: list[dict[str, Any]],
        reject: dict[str, Any],
        overrides: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """为拒收记录匹配字段契约：优先取显式覆盖，其次按拒收原因中的字段名匹配源字段。"""
        record_key = str(reject.get("记录主键", ""))
        if record_key in overrides:
            return overrides[record_key]
        reason = str(reject.get("拒收原因", ""))
        for contract in contracts:
            src = str(contract.get("源字段", ""))
            if src and src in reason:
                return contract
        # 退而求其次：取第一条已生效契约，仍无则给出空壳占位
        for contract in contracts:
            if contract.get("status") == "已生效":
                return contract
        return contracts[0] if contracts else {
            "契约编号": "", "源字段": "", "目标字段": "", "契约版本": "v1.0",
        }

    def list_worklist(
        self,
        worklist_code: str = "",
        item_status: str = "",
        only_remaining: bool = False,
    ) -> list[dict[str, Any]]:
        """查询待重新映射清单，可按清单批次、条目状态过滤，并支持只看剩余拒收项。"""
        rows = list(store.rows(self.MODULE))
        if worklist_code:
            rows = [r for r in rows if r.get("清单编号") == worklist_code]
        if item_status:
            rows = [r for r in rows if r.get("清单状态") == item_status]
        if only_remaining:
            # 剩余拒收 = 源端尚未补发更正、无法补转的条目
            rows = [r for r in rows if not r.get("补发数据")]
        return rows

    def get_worklist_item(self, item_id: int) -> dict[str, Any] | None:
        return store.find(self.MODULE, item_id)

    # -- 源端补发更正 --

    def receive_corrections(
        self,
        worklist_code: str,
        corrections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """接收源端补发的更正记录，按记录主键回填到清单条目。

        每条更正至少携带记录主键；补正字段取值放在 ``values`` 中。
        未补发的条目保持原状，后续作为剩余拒收数据返回给源端。
        """
        by_key = {str(c.get("记录主键")): c for c in corrections if c.get("记录主键") is not None}
        updated: list[str] = []
        missed: list[str] = []
        for row in store.rows(self.MODULE):
            if row.get("清单编号") != worklist_code:
                continue
            record_key = str(row.get("记录主键", ""))
            correction = by_key.get(record_key)
            if correction is None:
                missed.append(record_key)
                continue
            row["补发数据"] = correction.get("values", correction)
            row["补发时间"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time()))
            updated.append(record_key)

        self._write_jsonl(
            self._data_dir("remap") / "correction_log.jsonl",
            [{
                "action": "correct", "worklist_code": worklist_code,
                "corrected_keys": updated, "remaining_keys": missed, "at": time.time(),
            }],
        )
        return {
            "worklist_code": worklist_code,
            "corrected": len(updated),
            "corrected_keys": updated,
            "remaining": len(missed),
            "remaining_keys": missed,
        }

    # -- 领用与补转换 --

    def claim_scope(self, worklist_code: str, record_keys: list[str] | None = None) -> dict[str, Any]:
        """领用清单范围内的可补转条目。

        只有待重新映射、且源端已补发更正、且转换键尚未补转成功的条目可被领用。
        已经补转成功的条目不会再次进入领用范围，保证同一条记录不能被重复转换。
        """
        self._load_converted_index()
        wanted = {str(k) for k in (record_keys or [])}
        claimed: list[dict[str, Any]] = []
        skipped_converted: list[str] = []
        skipped_waiting: list[str] = []

        for row in store.rows(self.MODULE):
            if row.get("清单编号") != worklist_code:
                continue
            record_key = str(row.get("记录主键", ""))
            if wanted and record_key not in wanted:
                continue
            conversion_key = str(row.get("转换键", ""))
            if row.get("清单状态") == STATUS_CONVERTED or self.is_converted(conversion_key):
                skipped_converted.append(record_key)
                continue
            if not row.get("补发数据"):
                skipped_waiting.append(record_key)
                continue
            if row.get("清单状态") != STATUS_CLAIMED:
                row["清单状态"] = STATUS_CLAIMED
                row["status"] = STATUS_CLAIMED
            row["领用批次"] = f"CLAIM-{worklist_code}-{int(time.time())}"
            claimed.append(dict(row))

        self._write_jsonl(
            self._data_dir("remap") / "claim_log.jsonl",
            [{
                "action": "claim", "worklist_code": worklist_code,
                "claimed_keys": [r["记录主键"] for r in claimed],
                "skipped_converted_keys": skipped_converted,
                "skipped_waiting_keys": skipped_waiting,
                "at": time.time(),
            }],
        )
        return {
            "worklist_code": worklist_code,
            "claimed": len(claimed),
            "claimed_items": claimed,
            "skipped_converted": skipped_converted,
            "skipped_waiting_correction": skipped_waiting,
        }

    def run_reconversion(
        self,
        worklist_code: str,
        *,
        target_contract_version: str = "",
        record_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        """对领用范围执行补转换，按实际生效的字段契约版本写出补转换产物。

        幂等保证：转换键（记录主键+契约编号+实际映射版本）已在索引中的记录
        直接跳过，不会向产物文件多写一行。补转成功的条目标记为已补转，
        未补发更正的条目保留在剩余拒收数据中。
        """
        self._load_converted_index()
        wanted = {str(k) for k in (record_keys or [])}
        # 取当前已生效契约作为补转换使用的新规则；可由调用方显式指定版本
        active_contracts = [r for r in store.rows("field_contract") if r.get("status") == "已生效"]
        converted_rows: list[dict[str, Any]] = []
        converted_keys_now: list[str] = []
        duplicate_keys: list[str] = []
        remaining: list[dict[str, Any]] = []

        for row in store.rows(self.MODULE):
            if row.get("清单编号") != worklist_code:
                continue
            record_key = str(row.get("记录主键", ""))
            if wanted and record_key not in wanted:
                continue

            if not row.get("补发数据"):
                remaining.append(self._remaining_view(row))
                continue

            applied_version = target_contract_version or self._resolve_version(
                active_contracts, str(row.get("契约编号", "")), str(row.get("映射版本", "v1.0"))
            )
            applied_contract = str(row.get("契约编号", ""))
            conversion_key = build_conversion_key(record_key, applied_contract, applied_version)

            if self.is_converted(conversion_key) or row.get("清单状态") == STATUS_CONVERTED:
                duplicate_keys.append(str(row.get("转换键", "")))
                continue

            output_record = self._convert_row(row, active_contracts, applied_version)
            converted_rows.append(output_record)
            converted_keys_now.append(conversion_key)

            row["清单状态"] = STATUS_CONVERTED
            row["status"] = STATUS_CONVERTED
            row["pending"] = False
            row["补转版本"] = applied_version
            row["实际转换键"] = conversion_key
            row["补转时间"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time()))
            self._converted_keys.add(conversion_key)

        # 补转换产物按领用范围写出（追加写，重复键不会产生新行）
        output_file = self._data_dir("remap") / f"{worklist_code}_reconverted.jsonl"
        written = self._write_jsonl(output_file, converted_rows)
        if converted_keys_now:
            self._write_jsonl(
                self._index_file(),
                [{"conversion_key": key, "worklist_code": worklist_code, "at": time.time()}
                 for key in converted_keys_now],
            )

        # 剩余拒收数据是当前快照，覆盖写避免重复执行时累积重复行
        remaining_file = self._data_dir("remap") / f"{worklist_code}_remaining.jsonl"
        remaining_written = self._write_jsonl_snapshot(remaining_file, remaining)

        self._write_jsonl(
            self._data_dir("remap") / "reconvert_log.jsonl",
            [{
                "action": "reconvert", "worklist_code": worklist_code,
                "converted": len(converted_rows), "duplicates_skipped": len(duplicate_keys),
                "remaining": len(remaining), "at": time.time(),
            }],
        )
        return {
            "worklist_code": worklist_code,
            "converted": len(converted_rows),
            "converted_keys": converted_keys_now,
            "duplicates_skipped": len(duplicate_keys),
            "duplicate_keys": duplicate_keys,
            "remaining_rejected": len(remaining),
            "remaining_items": remaining,
            "artifact_path": str(output_file),
            "remaining_path": str(remaining_file),
            "artifact_written_lines": written,
            "remaining_written_lines": remaining_written,
        }

    def _resolve_version(
        self, active_contracts: list[dict[str, Any]], contract_code: str, fallback: str
    ) -> str:
        """确定补转换实际使用的契约版本：优先同契约编号的已生效新版本。"""
        for contract in active_contracts:
            if str(contract.get("契约编号", "")) == contract_code:
                return str(contract.get("契约版本", fallback))
        return active_contracts[0].get("契约版本", fallback) if active_contracts else fallback

    def _convert_row(
        self,
        row: dict[str, Any],
        active_contracts: list[dict[str, Any]],
        applied_version: str,
    ) -> dict[str, Any]:
        """按字段契约把补发更正数据转换为目标字段记录，并固化转换键与版本。"""
        source_values = row.get("补发数据") or {}
        target: dict[str, Any] = {}
        for contract in active_contracts:
            src = str(contract.get("源字段", ""))
            tgt = str(contract.get("目标字段", ""))
            if not src or not tgt:
                continue
            value = source_values.get(src, "")
            data_type = str(contract.get("数据类型", "string"))
            if data_type == "int":
                try:
                    value = int(value)
                except (ValueError, TypeError):
                    value = 0
            elif data_type == "float":
                try:
                    value = float(value)
                except (ValueError, TypeError):
                    value = 0.0
            target[tgt] = value
        record_key = str(row.get("记录主键", ""))
        contract_code = str(row.get("契约编号", ""))
        conversion_key = build_conversion_key(record_key, contract_code, applied_version)
        target.update({
            "_record_key": record_key,
            "_reject_code": row.get("拒收编号", ""),
            "_contract_code": contract_code,
            "_contract_version": applied_version,
            "_conversion_key": conversion_key,
            "_reconverted_at": time.time(),
        })
        return target

    def _remaining_view(self, row: dict[str, Any]) -> dict[str, Any]:
        """剩余拒收视图：保留原拒收原因与映射信息，退回源端继续修正。"""
        return {
            "记录主键": row.get("记录主键", ""),
            "拒收编号": row.get("拒收编号", ""),
            "批次编号": row.get("批次编号", ""),
            "拒收原因": row.get("拒收原因", ""),
            "契约编号": row.get("契约编号", ""),
            "映射版本": row.get("映射版本", ""),
            "清单状态": row.get("清单状态", ""),
        }

    def remaining_rejections(self, worklist_code: str) -> dict[str, Any]:
        """按领用范围汇总剩余拒收数据（源端尚未补发更正的条目）。"""
        rows = [
            self._remaining_view(row)
            for row in store.rows(self.MODULE)
            if row.get("清单编号") == worklist_code and not row.get("补发数据")
        ]
        return {"worklist_code": worklist_code, "remaining": len(rows), "items": rows}

    def converted_index(self, worklist_code: str = "") -> list[dict[str, Any]]:
        """查询已成功补转的转换键索引，供核对实际转换键与版本。"""
        self._load_converted_index()
        rows = self._read_jsonl(self._index_file())
        if worklist_code:
            rows = [r for r in rows if r.get("worklist_code") == worklist_code]
        return rows
