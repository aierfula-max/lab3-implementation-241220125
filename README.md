# 实验三 软件实现与构建 · 栖居酒店在线预订系统

241220125 王璟昊｜南京大学 软件工程实践

本实验承接：

- 实验一：需求规格说明书（34 条需求）
- 实验二：UML 设计（11 张图、12 屏界面）

把设计实现为可运行的桌面程序：Python 3.12 + Tkinter + SQLite，生产代码 9,479 行，测试 1,711 行（97 个用例）。

## 交付物

| 内容 | 位置 | 说明 |
| --- | --- | --- |
| 实验报告 | `实验报告.pdf` | 源文件 `report/实验报告.tex` |
| UML | `UML/` | 实现版类图 2、组件图、状态图、时序图 2、部署图，`.puml` 与 `.png` 一一对应 |
| 源码 | `code/` | 分层实现、97 个测试、CLI 演示、截图脚本 |
| AI 记录 | `chat.txt` | AI-01～AI-10、CHK-01～CHK-16，逐行编号 |

## 运行

```bash
cd code
python run.py
```

首次启动会在 `~/.qiju/qiju.db` 写入演示数据。演示账号见 `code/README.md`。

```bash
python -m qiju.cli demo          # 无界面走一遍主流程
python -m pytest -q              # 97 passed
ruff check qiju tests run.py     # All checks passed
```

## 仓库

- 实现仓库：https://github.com/aierfula-max/lab3-implementation-241220125
- 实验一：https://github.com/aierfula-max/lab1-requirements-241220125
- 实验二：https://github.com/aierfula-max/lab2-design-241220125

## 目录

```
实验3_241220125_王璟昊/
├── 实验报告.pdf
├── 实验报告.tex
├── chat.txt
├── UML/                 # 7 组 .puml + .png
├── code/                # 可运行工程（qiju/、tests/、run.py）
└── report/              # 报告源文件与截图
```
