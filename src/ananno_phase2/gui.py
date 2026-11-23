"""PyQt5桌面入口；算法命令行模式仍可独立调用服务。"""
from .workbench_service import build_output_paths, dataset_order_summaries, run_packing_job


def should_launch_gui(argv: list[str]) -> bool:
    return not argv or argv == ["--gui"]


def launch_gui() -> int:
    try:
        from .qt_workbench_2025 import launch_workbench
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PyQt5"):
            import sys
            raise RuntimeError(f'PyQt5版需要安装界面依赖，请使用当前解释器运行："{sys.executable}" -m pip install -r requirements.txt') from exc
        raise
    return launch_workbench()
