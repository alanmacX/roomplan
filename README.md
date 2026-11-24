# 智能家居课设演示

在此目录运行 `./start.sh`，打开 [本机演示](http://127.0.0.1:8768/)，默认口令 `2468`。运行只需要 Python 3.9+。数据库在 `.local/demo.sqlite3`，服务重启后仍保留。可用 `--db /path/to/demo.sqlite3` 指定另一数据库。

## 扫描户型

- 首页有 11 个房间。**3D** 是斜视，**2D** 用同一台正交相机转到正上方；两者共用 WebGL 场景、家具、灯具和交互面板。旧 `control-lab.html` 地址会转入首页的 2D 视角。
- 点房间按钮定位；在「通往」选择相邻房间，镜头平滑移向相邻房间，并标出对应门槛。「全屋」返回总览。
- 点「进入户型」让人物出现在走廊。点击地面或侧栏的房间让人物走过去；人物按扫描地面和碰撞几何寻路，不穿墙或家具。「退出行走」停在当前位置。
- 点「安装灯泡」，再点客厅地面，灯泡装在点击点正上方。不用输入安装高度。开关、调光和灯泡细节在两种视角里都能使用。
- 原手绘／JSON 户型编辑器和场景控制仍在 `floorplan-editor.html`，不在扫描户型的页面导航中。

## 数据与素材

- [Apple RoomPlan 官方样例](https://developer.apple.com/documentation/roomplan/merging-multiple-scans-into-a-single-structure)：从 11 个 USDZ 读取三角网格，保留样例的房间相对位置，并统一同层地面高度。根据捕获的门洞和相邻开放边界，局部清理重叠墙片、补齐扫描接缝；没有另画 2D 户型。
- 更新整屋网格：在 macOS 运行 `python3 tools/prepare-home.py /path/to/MergingMultipleScansIntoASingleStructure.zip`，需要 Swift 工具链。运行网页不需要 Xcode。
- [Poly Haven Lightbulb LED](https://polyhaven.com/a/lightbulb_led)（CC0），详见 `assets/led-bulb/SOURCE.md`。设备能力参考 Matter，命令由演示服务模拟。
