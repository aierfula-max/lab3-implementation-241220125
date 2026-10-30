# 栖居酒店在线预订系统 · 实现

241220125 王璟昊｜南京大学 软件工程实践 实验三（软件实现与构建）

承接实验一 34 条需求与实验二 UML 设计，用 **Python 3.12 + Tkinter + SQLite** 实现桌面版。
无第三方运行时依赖，`python run.py` 即可启动。

## 快速开始

```bash
cd code
python -m venv .venv && source .venv/bin/activate   # 可选
python run.py                    # 默认库 ~/.qiju/qiju.db，首次启动自动写入演示数据
python run.py --db ./qiju.db     # 指定数据库
python -m qiju.cli demo          # 无界面跑一遍主流程（内存库）
python -m pytest -q              # 91 个测试
ruff check qiju tests run.py     # 代码风格
```

演示账号（首次启动自动写入）：

| 角色 | 手机号 | 密码 |
| --- | --- | --- |
| 顾客 | 13600000001 | Qiju@2026 |
| 前台 | 13700000001 | Front@2026 |
| 店长 | 13900000001 | Manager@2026 |
| 平台管理员 | 13800000000 | Admin@2026 |

店长邀请码（河西店，待审核）：`PENDING-INVITE`。

## 分层

```
qiju/
├── domain/          纯规则，不依赖 sqlite / tkinter
│   ├── entities.py      12 个实体 + 聚合关系
│   ├── enums.py         7 状态、角色、退款/审核枚举
│   ├── order_state.py   7 条允许转换 + 角色/原因/库存影响
│   ├── pricing.py       每晚明细与总价
│   ├── cancellation.py  18:00 / no-show / 提前退房口径
│   └── validation.py    手机号、日期、人数、间数
├── application/     用例层，一个用例一个事务
│   ├── booking_service.py    查询、报价、幂等下单、逐晚扣减
│   ├── order_service.py      确认/拒绝/取消/改单/入住/退房/退款
│   ├── inventory_service.py  房态日历、批量设置、停售
│   ├── report_service.py     8 项经营指标
│   ├── scheduler_service.py  超时取消、未入住关闭、对账
│   └── audit_service.py      日志查询与 CSV 导出
├── infrastructure/  SQLite、仓储、口令哈希、演示数据
└── ui/              Tkinter：登录、顾客、商家、平台、消息
```

依赖方向单向：`ui → application → domain`，`application → infrastructure` 只经由
`Repositories` 门面。界面不写 SQL，领域层不 import `sqlite3`。

## 实现要点

| REQ | 做法 | 代码 |
| --- | --- | --- |
| 008/029 | 条件 UPDATE 扣库存，任一晚失败整单回滚 | `infrastructure/repositories/inventory.py` |
| 010/017 | 7 条转换表 + `version` 乐观锁 | `domain/order_state.py`、`order_service.py` |
| 012/016/025 | 纯函数退款口径 + 固定时钟测试 | `domain/cancellation.py` |
| 024 | `(user_id, request_id)` 唯一 + 2 分钟重复确认 | `booking_service.py` |
| 018 | 计费间夜/已住间夜/可售间夜三口径 | `report_service.py` |
| 019/021 | 业务与日志同事务、手机号脱敏、CSV 导出 | `application/base.py`、`audit_service.py` |
| 028 | 唯一约束、外键、CHECK、事务 | `infrastructure/db.py` |
| 033 | 不接支付/短信；退款只记账 | 全局 |

## 与实验二的差异

- 状态转换按需求表逐行数实为 **7 条**（实验二报告写 8 条，多算的是“顾客取消/超时取消”两条同目标转换）。
- 订单新增 `confirm_deadline`：确认时限在**下单时快照**，改配置只影响新订单。
- 酒店新增 `pending_profile`：关键资料变更审核期间仍展示旧值、照常接单。
- 新增 `ReportService`、`AuditService`、`SchedulerService`，对应实验二组件图中的“运营服务/任务调度”。
- 桌面版用“单连接 + 可重入锁 + `BEGIN IMMEDIATE`”替代 PostgreSQL 行锁，见报告 7.2 的不足。

## 测试

```
91 passed
核心层（domain + application + infrastructure，排除 seed）覆盖率 80%
UI 层没有自动化测试，由 scripts/capture_ui.py 逐页冒烟截图
```

并发用例在 `tests/test_concurrency.py`：50 个线程抢 1 间房，断言恰好 1 单成功、
库存为 1、其余 49 个都是 `SOLD_OUT`。

## 目录说明

- `scripts/capture_ui.py`：用 ImageMagick `import` 抓取报告截图（开发工具，不参与运行）。
- `docs/`：预留的设计/运行补充材料。
- 演示数据、数据库文件、`__pycache__`、`.coverage` 均在 `.gitignore` 中。
