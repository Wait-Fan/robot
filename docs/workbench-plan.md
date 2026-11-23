# Local Packing Workbench Implementation Plan

**Goal:** 实施用户要求的标准库 Tkinter 工作台。
**Spec:** workbench-design.md
**Architecture:** 服务负责输入/结果/任务；Tk 工作台负责线程、交互和展示；标准库投影函数供 Tk Canvas 与离线 PNG 使用。保留 gui.py 既有服务入口与 CLI 行为。
**Tech Stack:** Python 3.10+ 标准库（tkinter / threading / queue / zlib），实际验证 Python 3.13.7。

## 约束与审查重点
- 不使用数据库，不接 WCS，不改阶段性算法决策；仅文件输入输出。
- 所有未放置箱都计入进度；停止后无新完成结果。
- 标准 CSV 无订单也能运行；JSON 自带尺寸；拒绝非有限数。
- 旧结果可回看；坏结果不替换当前结果；新运行不覆盖历史。
- 无第三方图形库；Tk 对象仅在主线程使用，关闭窗口先等待计算停止。

## 执行任务
1. [x] 为输入识别、进度、取消、结果校验写失败测试；实现 workbench_service.py 和 packer.py 可选回调；gui.py 保留兼容导出。
2. [x] 为 Tk 的输入/计算/动画/表格/筛选联动写失败测试；实现 native_scene.py 与 tk_workbench.py，并切换 launch_gui。
3. [x] Python 3.13 全套测试、真实订单、PNG 检查、README/依赖更新；备份并同步用户 E 盘工程，交付修正版 ZIP。

本工程没有 Git 仓库，使用用户目录原文件备份和工作区副本隔离改动，不创建或提交 Git 仓库。
