# Ananno 2025 独立装箱研究工程 v0.1.0

本工程从你的2024版v0.4.1继承，加入2025论文启发的固定开放方向接近模型。原2024目录不修改。两版均为功能研究实现，尚未证明完整论文数值复现。

来源论文为 **Ananno & Jonsson (2025)**，不是2024年的Ananno & Ribeiro。依据与简化假设见 [2025对应说明](docs/ananno2025-scope.md)，继承的2024参数与约束见 [2024核对说明](docs/full-reproduction-spec.md)。其他旧文档是继承历史，不代表2025新增验证。

## 从 GitHub 下载后运行 EC66 离线示例

在项目根目录，使用兼容的 Python 3.13 环境执行：

```powershell
python -m pip install -r requirements-robot.txt
python main.py --algorithm robot2025 --input-json examples/ec66_offline_demo.json --robot-scene examples/ec66_scene_demo.json --paper-config examples/ec66_ga_demo.json --output-json output/ec66_offline_demo_plan.json --output-csv output/ec66_offline_demo_positions.csv --no-show
```

示例使用软件测试工位，不连接真实机械臂。真实工位需要自行配置托盘、取箱、TCP等标定参数。当前界面默认仍使用轻量检查；完整EC66检查通过命令行的`--robot-scene`启用。详细说明见[EC66离线接入说明](docs/EC66_Windows离线接入说明.txt)。

仓库包含代码、机械臂模型、测试及小型示例。`robot_runtime`独立运行库、`data`原始数据、`examples/imported`业务数据副本、`output`结果、历史备份及本地基线源码压缩包保留在本机，通过`.gitignore`排除；旧文档中的数据和基线核验命令需要自行提供对应本地文件。

## 在指定2025目录启动

在PowerShell运行：

```powershell
Set-Location -LiteralPath 'E:\范卓燃\码垛算法\文件\装箱算法\robot\robot'
& 'E:\program\python3.13\python.exe' -m pip install -r requirements-ga.txt
& 'E:\program\python3.13\python.exe' main.py
```

也可双击`start_workbench.bat`。无需数据库。界面应显示 **Ananno 2025**，默认“2025 可达性”，保留“论文两阶段”（2024模式）和“基础模式”。VSCode中用“打开2025 PyQt5工作台”启动。

1. 选择CSV、JSON或XLSX，核对托盘长宽和限高，尺寸单位必须一致。
2. “装箱设置”选择来向：`+Z`从上往下，`-X`从X负侧进入，其他方向同理。托盘和GA参数在下一层设置。
3. 点击“一键装箱”。新结果保存在`output/robot2025_results/run_.../`，含JSON、每箱XYZ/姿态/顺序CSV、PNG。
4. 在“算法 / 约束记录”查看开放方向、逐箱检查、GA内部拒绝次数和基线哈希；“单托盘 / 回放”按新执行顺序播放。

切换算法或修改来向后需重新计算；加载旧JSON不会把它转换成2025结果。通用Excel与WCS JSON沿用2024解析，不新增订单分组；论文Dataset的`Order`选择功能继续保留。

## 命令行小样例

```powershell
& 'E:\program\python3.13\python.exe' main.py --algorithm robot2025 --open-direction=-X --input-json examples/paper_two_phase.json --output-json output/robot2025_plan.json --output-csv output/robot2025_positions.csv --save-plot output/robot2025.png --no-show
```

负方向建议用`--open-direction=-X`这种等号写法。命令行默认仍为基础模式，需明确指定`--algorithm robot2025`；`--algorithm paper`用于2024对照。XLSX用`--input 文件.xlsx`，不含托盘尺寸时补`--pallet 长 宽 高`。

## 目前做到了什么

- 继承2024的层/块、DEAP μ+λ / NSGA-II、EP及原有约束。
- 固定开放方向的刚性箱体扫掠检查，支撑与遮挡依赖共同生成执行顺序。
- 在GA内部拒绝无可执行顺序的候选；第一阶段不合格盘的箱体退回GA；最终逐箱复核。
- 新PyQt5入口、方向设置、审计输出与基线溯源。

**当前通过只表示箱体在此简化模型下的直线接近无箱体遮挡，不代表真实机械臂必定可达。** 尚未建模机器人连杆、夹具、臂展、关节限制、IK、完整搬运轨迹，未做RobotStudio或实物验证。每个输出仍标记`is_complete_reproduction: false`。默认+Z时，外观与2024结果相同是可能的。

## 溯源

- `provenance/baseline_2024_source.zip`：开始本次工作时的2024源码、样例、文档快照（不包含输出/缓存/旧备份）。
- `provenance/baseline_2024_manifest.json`：99个基线文件的SHA256、来源目录、快照哈希。
- `provenance/changes_2025.json`：相对基线的新增/修改清单及哈希。
- `src/ananno_phase2/robot_approach.py`：新模型接口。
- `src/ananno_phase2/robot_pipeline.py`：继承与优化集成；未来可在模型接口接入真实机械臂检查。

独立目录和快照提供本次继承关系；后续版本可继续记录变更。原始2024 README也在基线ZIP里。

## 验证记录

本次125项测试通过。`output/robot2025_validation/`保存报告、界面图、JSON/CSV：

- 9箱：Phase1放8箱，GA处理1箱；2025来向-X检查通过；继承2024模式与原目录坐标结果相同。
- 2箱机制例：2024一盘；-X接近与继承对齐约束冲突，GA拒绝该方案，2025得到两盘。该例证明约束生效，不代表工业性能提升。
- 当前磁盘的`668箱子数据集_删除YZX244.xlsx`实际有632箱；只取前4种箱型各最多6箱共24箱验证，+Z通过。未对632箱/668箱全量运行新版模型；原始668同名文件本次未找到。

复查命令：

```powershell
$env:PYTHONPATH='src;.'
& 'E:\program\python3.13\python.exe' -m unittest discover -s tests -v
& 'E:\program\python3.13\python.exe' tools/capture_baseline_2024.py 'E:\范卓燃\码垛算法\文件\装箱算法\复现ananno2024算法\ananno_phase2_reproduction' --verify
& 'E:\program\python3.13\python.exe' tools/verify_robot2025.py --xlsx 'E:\范卓燃\码垛算法\文件\数据集\668箱子数据集\668箱子数据集_删除YZX244.xlsx'
```

`tools/release_2025.py sync`只接受指定2025目录，已有变更文件先备份；不会同步至2024目录。`tools/package_workbench.py`生成独立`ananno2025_reachability_workbench.zip`，不会覆盖2024压缩包。

## 多个接近开放侧

2025工作台的“装箱设置”支持勾选多个开放侧，每箱从允许方向中选择可行侧，至少选一项。修改后需要重新计算。命令行可重复使用`--open-direction`，例如`--open-direction=+Z --open-direction=-X`。详见[多个开放侧设置](docs/多个开放侧设置.md)。

## 托盘坐标统一为长边X

新计算自动将托盘较长底边映射到X、较短底边映射到Y，Z向上。例如1440×2240×720统一为X2240、Y1440、Z限高720。导入、设置、命令行和输出使用同一约定；历史结果保持原坐标，需要重新计算。机器人旧托盘坐标采用保持物理位置的刚体转换。详见[托盘坐标约定](docs/托盘坐标约定.md)。

## 可视化工位与现场机械臂

双击`start_workcell_editor.bat`或在工作台点击“工位布局”，可选择EC66或FANUC R-2000iC/210L，看图拖动托盘、取箱台和障碍物，设置关节及工具。现场吸盘面600×800mm，高度250mm为用户确认的暂定值，使用虚拟外包络检查碰撞。应用工位后，工作台计算接入所选型号的IK、携箱碰撞和完整抓放路径；预览本身不代表验证通过。详见[可视化工位与机械臂选择](docs/可视化工位与机械臂选择.md)。
