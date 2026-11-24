# 跨系统数据交换与批量传输平台

面向异构系统间批量数据交换的字段契约、增量窗口抽取、暂存落地、校验和对账、断点续传与到达核对平台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 源端登记 | `source_register` | 源端系统 | 源端编号、系统名称、数据域 |
| 目标端登记 | `target_register` | 目标端点 | 目标编号、系统名称、接收格式 |
| 字段契约 | `field_contract` | 字段映射 | 契约编号、源字段、目标字段 |
| 增量窗口 | `extract_window` | 抽取窗口 | 窗口编号、源端编号、增量字段 |
| 传输批次 | `transfer_batch` | 传输批次 | 批次编号、窗口编号、目标编号 |
| 暂存落地 | `staging_area` | 暂存分区 | 暂存编号、批次编号、落地路径 |
| 校验核对 | `checksum_verify` | 校验任务 | 校验编号、批次编号、源端校验值 |
| 到达对账 | `arrival_reconcile` | 对账单 | 对账编号、批次编号、应到条数 |
| 字段冲突 | `conflict_resolve` | 冲突记录 | 冲突编号、记录主键、冲突字段 |
| 断点续传 | `resume_point` | 续传断点 | 断点编号、批次编号、已完成分片 |
| 速率整形 | `speed_control` | 限速策略 | 策略编号、作用范围、每秒记录数 |
| 拒收回执 | `reject_record` | 拒收记录 | 拒收编号、批次编号、记录主键 |
| 待重新映射清单 | `remap_worklist` | 待重新映射记录 | 清单编号、拒收编号、记录主键、转换键、映射版本 |
| 格式适配 | `format_adapt` | 适配版本 | 适配编号、记录格式、旧版结构 |
| 传输血缘 | `transfer_lineage` | 血缘链路 | 链路编号、源端编号、抽取窗口 |
| 批次归档 | `history_archive` | 归档卷 | 归档编号、批次范围、归档路径 |
| 历史重放 | `exchange_replay` | 重放任务 | 重放编号、归档编号、重放范围 |
| 时效监控 | `sla_monitor` | 时效指标 | 指标编号、源端编号、约定到达时限 |
| 通道配置 | `channel_config` | 传输通道 | 通道编号、传输协议、并发连接数 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 待重新映射补转换（拒收回执 × 字段契约共享清单）

待处置拒收缺少能直接用于补转换的筛选结果，`remap_worklist` 把拒收回执与字段契约
连到同一份待重新映射记录清单：

1. `GET /api/reject_record/rejections/by-reason?reason=数值错误` 按拒收原因筛出待处置回执，
   同时返回字段映射明细与拒收时的实际映射版本（原拒收原因可追溯）。
2. `POST /api/reject_record/remap-worklist` 生成待重新映射记录清单，转换键
   `记录主键|契约编号|映射版本` 在构建时固化；字段契约侧可用
   `GET /api/field_contract/remap-worklist` 读同一份清单。
3. `POST /api/field_contract/revise` 为字段契约增加新规则版本，旧版本废弃，
   清单仍保留原映射版本。
4. `POST /api/remap_worklist/corrections` 接收源端补发的更正记录，按记录主键回填；
   未补发的条目留在剩余拒收数据中。
5. `POST /api/remap_worklist/claim` 领用可补转范围；已补转条目不会被重复领用。
6. `POST /api/remap_worklist/reconvert` 按领用范围补转换，写出
   `data/remap/<清单编号>_reconverted.jsonl` 与 `_remaining.jsonl`。
   转换键进入 `data/remap/converted_keys.jsonl` 索引，同一条记录再次补转不会多写一行。
7. `GET /api/remap_worklist/converted-keys` 核对实际转换键与版本，
   `GET /api/remap_worklist/remaining` 查剩余拒收数据供源端继续处理。

集成测试见 `backend/tests/test_remap_worklist.py`，前端专用工作台为
`frontend/src/views/RemapWorkbench.vue`（导航「待重新映射清单」）。

领域：数据工程
子方向：数仓与数据湖
