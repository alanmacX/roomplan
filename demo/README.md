# 面向多成员差异化作息的家庭分域智能家居系统

软件工程课程设计演示工程（五层单向依赖架构 + 双栏空间控制台）。

## 启动与测试

```bash
./demo/start.sh --port 8768
python3 demo/tests/test_rtm_all.py
```

浏览器打开 [http://127.0.0.1:8768/](http://127.0.0.1:8768/)，支持三类家庭角色空间分域权限切换（右上角 `⋯` → `成员切换…`）：
- **管理员**：`2468`（支持平面图编辑、动态添加配件类型、新建场景、CSV/JSON 批量导入导出与全屋控制）
- **长辈成员**：`1357`（支持日常控制、场景切换与语音视觉交互，不可修改户型拓扑）
- **临时访客**：`0000`（仅展示公共区域与客房，自动屏蔽主卧与长辈次卧的设备、在场状态与室内镜头）

## 五层架构目录结构

- `index.html` / `room.css` / `room.js` / `walk.js` / `floorplan-editor.html` / `app.js`：**展示层** —— 左舞台同源 3D/2D 连续相机 WebGL 视口与人物寻路漫游，右侧毛玻璃控制面板、房间内墙角广角透视摄像头及多步协同轨迹卡片。
- `backend/strategy/`：**策略层** —— `engine.py`（五级冲突仲裁、四季温湿滞回、自然底光补偿）、`hassil_grammar.py`（参考 OHF-Voice/HassIL 的中文意图槽位模板引擎）、`harness.py`（各房微气候与 `HomeAgentHarness` 多步工具编排器）及 `butler.py`（空缺槽位追问、室内视觉分析与统一路由）。
- `backend/control/`：**控制层** —— 空间分域 RBAC 视图脱敏与写校验、能力值域白名单与跨属性互斥检查、二次确认令牌、CSV/JSON 原子导入导出与场景引用完整性检查。
- `backend/device/`：**设备层** —— 参考 Matter 规范构建的配置驱动设备类型与能力注册表、软件设备模拟器（支持超时、离线与失败模拟）。
- `backend/data/`：**数据层** —— 基于 SQLite WAL 事务模式的 `SQLiteRepository` 持久化实现（默认位于 `.local/demo.sqlite3`）。

## 开源资产与许可说明

- [Apple RoomPlan 多房间扫描样例](https://developer.apple.com/documentation/roomplan/merging-multiple-scans-into-a-single-structure)（详见 `assets/apple-roomplan/LICENSE.txt`）
- [Three.js](https://threejs.org/)（MIT 协议，详见 `vendor/THREE-LICENSE.txt`）
- [Poly Haven Lightbulb LED](https://polyhaven.com/a/lightbulb_led)（CC0 协议，详见 `assets/led-bulb/SOURCE.md`）
