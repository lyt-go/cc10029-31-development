"""待重新映射补转换端到端测试。

剧本：准备三条不同原因的拒收 → 按原因筛选（关联字段映射明细）→
源端补发两条更正 → 字段契约增加新规则版本 → 领用并启动补转换 →
核对实际转换键、映射版本和待处置项 → 再次领用确认合法记录没有被重复转换。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.field_contract import FieldContractService
from app.services.reject_record import RejectRecordService
from app.services.remap_worklist import (
    RemapWorklistService,
    build_conversion_key,
)
from app.store import store

BATCH = "BATCH-REMAP-01"
REASON_AMOUNT = "字段amount数值错误：金额无法转换为数值类型"
REASON_QTY = "字段amount数值错误：数量字段取值越界"
REASON_MISSING = "必填字段缺失：源端未提供order_no主键"


@pytest.fixture(autouse=True)
def reset_store():
    """每个测试前重置内存表并清空转换键索引，保证拒收与清单数据隔离。

    转换键索引持久化在 data/remap/converted_keys.jsonl，会跨用例累积，
    因此每个用例开始前截断索引文件并重置服务进程内缓存。
    """
    from app.seed import SEED_ROWS
    store._tables = {
        name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
    }
    svc = RemapWorklistService()
    index_file = svc._index_file()
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text("", encoding="utf-8")
    svc._converted_keys.clear()
    svc._index_loaded = True
    yield


def _prepare_contracts() -> tuple[FieldContractService, dict, dict]:
    """准备金额、数量两个字段契约（v1.0），并置为已生效。"""
    fc = FieldContractService()
    amount = fc.create_contract("amount", "amount_yuan", "float")
    amount["转换规则"] = "浮点转换"
    fc.run_action(amount["id"], "确认生效")
    qty = fc.create_contract("qty", "quantity", "int")
    qty["转换规则"] = "整数转换"
    fc.run_action(qty["id"], "确认生效")
    return fc, amount, qty


def _prepare_three_rejections(rr: RejectRecordService) -> list[dict]:
    """准备三条不同原因的拒收，并全部提交到待处置。"""
    cases = [
        ("PK-R01", REASON_AMOUNT),
        ("PK-R02", REASON_QTY),
        ("PK-R03", REASON_MISSING),
    ]
    created = []
    for key, reason in cases:
        result = rr.create_rejection(BATCH, "校验", reason, record_key=key)
        rr.run_action(result["reject_id"], "提交处置")
        created.append(result)
    return created


class TestRemapWorklistFlow:
    """补转换全流程：筛选、补发、新规则、领用、补转、幂等。"""

    def test_full_remap_flow(self):
        rr = RejectRecordService()
        fc, amount_contract, qty_contract = _prepare_contracts()
        _prepare_three_rejections(rr)

        # 1. 按原因查询拒收回执 + 字段映射明细，能查回原拒收原因和实际映射版本
        queried = rr.query_rejections_with_mapping("数值错误")
        assert queried["total"] == 2
        reasons = {item["拒收原因"] for item in queried["items"]}
        assert REASON_AMOUNT in reasons and REASON_QTY in reasons
        for item in queried["items"]:
            assert item["映射版本"] == "v1.0"
            assert item["契约编号"]
            assert item["源字段"] == "amount"

        # 2. 生成待重新映射记录清单：只含两条数值错误拒收
        built = rr.create_remap_worklist("数值错误", BATCH)
        worklist_code = built["worklist_code"]
        assert built["matched"] == 2
        record_keys = {item["记录主键"] for item in built["items"]}
        assert record_keys == {"PK-R01", "PK-R02"}
        # 筛选结果固化原拒收原因与原映射版本，并预生成转换键
        for item in built["items"]:
            assert item["拒收原因"]
            assert item["映射版本"] == "v1.0"
            assert item["转换键"] == build_conversion_key(
                item["记录主键"], item["契约编号"], "v1.0")

        # 字段契约侧共享同一份清单
        shared = fc.get_remap_worklist(worklist_code)
        assert shared["total"] == 2

        # 3. 字段契约增加新规则版本 v2.0，旧版本废弃
        revise = fc.revise_contract_rule(
            amount_contract["契约编号"], "金额分转元并做浮点归一", "v2.0", "float")
        assert "error" not in revise
        assert revise["new_version"] == "v2.0"
        active = fc.get_active_contracts()
        active_amount = next(
            c for c in active
            if c["契约编号"] == amount_contract["契约编号"] and c["源字段"] == "amount"
        )
        assert active_amount["契约版本"] == "v2.0"
        # 旧版本已废弃，仍可追溯
        old = next(
            c for c in store.rows("field_contract")
            if c["契约编号"] == amount_contract["契约编号"] and c["契约版本"] == "v1.0"
        )
        assert old["status"] == "已废弃"

        # 4. 源端补发两条更正
        remap = RemapWorklistService()
        correction = remap.receive_corrections(worklist_code, [
            {"记录主键": "PK-R01", "values": {"amount": "88.50", "qty": "3"}},
            {"记录主键": "PK-R02", "values": {"amount": "120.00", "qty": "6"}},
        ])
        assert correction["corrected"] == 2
        assert correction["remaining"] == 0  # 清单内两条均已补发；第三条不在清单内

        # 5. 领用清单范围
        claim = remap.claim_scope(worklist_code)
        assert claim["claimed"] == 2
        assert not claim["skipped_converted"]
        claimed_keys = {item["记录主键"] for item in claim["claimed_items"]}
        assert claimed_keys == {"PK-R01", "PK-R02"}

        # 6. 启动补转换，按新规则版本 v2.0 写出产物
        result = remap.run_reconversion(worklist_code)
        assert result["converted"] == 2
        assert result["duplicates_skipped"] == 0
        assert result["artifact_written_lines"] == 2

        # 核对实际转换键与实际映射版本
        index = remap.converted_index(worklist_code)
        assert len(index) == 2
        for row in index:
            assert row["conversion_key"].endswith("|v2.0")
        converted_items = [
            item for item in remap.list_worklist(worklist_code)
            if item["清单状态"] == "已补转"
        ]
        assert len(converted_items) == 2
        for item in converted_items:
            assert item["补转版本"] == "v2.0"
            assert item["映射版本"] == "v1.0"  # 原映射版本仍保留可追溯
            assert item["实际转换键"] == build_conversion_key(
                item["记录主键"], item["契约编号"], "v2.0")

        # 补转换产物内容：目标字段按契约转换，携带转换键与版本
        artifact_rows = remap._read_jsonl(Path(result["artifact_path"]))
        assert len(artifact_rows) == 2
        for row in artifact_rows:
            assert row["_contract_version"] == "v2.0"
            assert row["_conversion_key"]
            assert isinstance(row["amount_yuan"], float)
            assert isinstance(row["quantity"], int)

    def test_second_claim_does_not_reconvert(self):
        """同一条记录补转成功后，再次领用同一批不能多写一行。"""
        rr = RejectRecordService()
        _prepare_contracts()
        _prepare_three_rejections(rr)
        remap = RemapWorklistService()

        built = remap.build_worklist("数值错误", BATCH)
        worklist_code = built["worklist_code"]
        remap.receive_corrections(worklist_code, [
            {"记录主键": "PK-R01", "values": {"amount": "88.50", "qty": "3"}},
            {"记录主键": "PK-R02", "values": {"amount": "120.00", "qty": "6"}},
        ])
        first_claim = remap.claim_scope(worklist_code)
        assert first_claim["claimed"] == 2
        first_run = remap.run_reconversion(worklist_code)
        assert first_run["converted"] == 2
        first_file_rows = remap._read_jsonl(
            Path(first_run["artifact_path"]))

        # 再次领用同一批：已补转条目全部跳过，合法记录不重复进入领用范围
        second_claim = remap.claim_scope(worklist_code)
        assert second_claim["claimed"] == 0
        assert set(second_claim["skipped_converted"]) == {"PK-R01", "PK-R02"}

        # 再次补转：0 条新转换，产物文件不新增行
        second_run = remap.run_reconversion(worklist_code)
        assert second_run["converted"] == 0
        assert second_run["duplicates_skipped"] == 2
        assert second_run["artifact_written_lines"] == 0
        second_file_rows = remap._read_jsonl(
            Path(second_run["artifact_path"]))
        assert len(second_file_rows) == len(first_file_rows) == 2

    def test_remaining_rejections_for_unfixed_records(self):
        """未补发更正的拒收保留为剩余拒收数据，供源端继续处理。"""
        rr = RejectRecordService()
        _prepare_contracts()
        _prepare_three_rejections(rr)
        remap = RemapWorklistService()

        # 直接把三条不同原因拒收都构建进一份清单
        built = remap.build_worklist("字段", BATCH)
        worklist_code = built["worklist_code"]
        assert built["matched"] == 3

        # 源端只补发两条，第三条（必填缺失）未修正
        remap.receive_corrections(worklist_code, [
            {"记录主键": "PK-R01", "values": {"amount": "88.50", "qty": "3"}},
            {"记录主键": "PK-R02", "values": {"amount": "120.00", "qty": "6"}},
        ])
        claim = remap.claim_scope(worklist_code)
        assert claim["claimed"] == 2
        assert claim["skipped_waiting_correction"] == ["PK-R03"]

        result = remap.run_reconversion(worklist_code)
        assert result["converted"] == 2
        assert result["remaining_rejected"] == 1

        remaining = remap.remaining_rejections(worklist_code)
        assert remaining["remaining"] == 1
        assert remaining["items"][0]["记录主键"] == "PK-R03"
        assert "必填字段缺失" in remaining["items"][0]["拒收原因"]

        # 剩余清单视图只看待修正项
        remaining_rows = remap.list_worklist(worklist_code, only_remaining=True)
        assert [r["记录主键"] for r in remaining_rows] == ["PK-R03"]
        # 剩余拒收产物文件已写出
        remaining_file_rows = remap._read_jsonl(
            Path(result["remaining_path"]))
        assert len(remaining_file_rows) == 1

        # 重复执行补转换：剩余拒收是覆盖快照，不会累积重复行
        rerun = remap.run_reconversion(worklist_code)
        assert rerun["converted"] == 0
        assert rerun["remaining_rejected"] == 1
        assert len(remap._read_jsonl(Path(rerun["remaining_path"]))) == 1
