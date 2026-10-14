# 独立仓库验证记录

仓库：`mindcont/icloud3-traccar`。迁移分支：`feature/standalone-release`。

插件来源：`mindcont/icloud3` 提交 `991350f13de95a2ee238434e74fd9893e67170d3`。
独立仓库已验证代码提交：`2f9b1e33260c285ff6124863833f1997263bc7ac`。
迁移保持全部插件 Python 文件不变，更新 manifest 版本/链接并增加 HACS 元数据、文档、许可证来源声明和图标。

## 已执行

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| 本地 Python 编译 | 通过 | 插件、两套测试 |
| JSON/目录检查 | 通过 | manifest、翻译、hacs.json；只有一个自定义集成目录 |
| 品牌图标 | 通过 | 256/512 像素 RGBA PNG，原创建云/定位标记 |
| 本地行为测试 | 47 项通过 | 实际回环 HTTP + worker + 明确的 HA adapter doubles |
| 独立仓库 CI 行为测试 | 47 项通过 | Python 3.13 |
| 独立仓库真实 HA 测试 | 4 项通过 | HA 2025.3.4；模块导入、真实配置表单、加载/卸载及 SQLite Recorder 属性变化历史读取 |
| 独立仓库 hassfest | 通过 | 本仓库仅包含 icloud3_traccar，没有来源仓库的翻译格式问题 |

[独立测试运行](https://github.com/mindcont/icloud3-traccar/actions/runs/38505429335) · [独立 hassfest](https://github.com/mindcont/icloud3-traccar/actions/runs/38505429405) · [PR #1](https://github.com/mindcont/icloud3-traccar/pull/1)

## 行为覆盖

- REST Bearer 认证、uniqueId 查询、设备创建/复用/重命名、OsmAnd POST 请求体、数字 deviceId 轨迹读回。
- 多设备、同设备并发去重、最小移动距离、字段开关、定位时间变化。
- HTTP 失败退避、认证错误不重试、创建/位置响应丢失恢复、pending 持久化及重启恢复。
- 实时只读内存，不调用 Recorder；慢历史点不阻塞同设备的新实时点。
- Recorder 完整属性及属性变化读取、含开始/不含结束的时间范围、原时间上传。
- 历史断点、失败行不提前推进、重启保持暂停、手动继续、Recorder 清理后的偏移指纹检查。
- 重叠历史导入查重、显式重新导入、连续重复坐标、缺坐标/时间跳过原因。
- 密码字段无保存 Token 默认值、空输入保留 Token、固定错误、状态/诊断/日志不含测试凭据或完整坐标。
- 空配置默认关闭、设置菜单、历史操作、加载/卸载和任务清理。

## 明确未验证

- 真实 Traccar 6.8.1 服务端端到端测试：HTTP 测试使用本地 mock，并非运行中的 Traccar。
- 浏览器中的 HA 配置界面和仪表盘交互。
- HACS 实际安装、更新和预发布选择；main 尚未包含迁移代码。
- 生产 Apple/HA/Traccar 连接：未读取生产凭据或操作真实设备。
- 其他 HA / iCloud3 / Traccar 版本的运行兼容性。

`tests/` 使用 doubles，不能替代真实 HA；`tests_runtime/` 单独进程运行真实 HA 和临时 SQLite Recorder。没有对生产数据库执行操作，不需要生产数据库迁移。

## 来源证据与发布状态

来源仓库也曾通过 47 项行为测试和 4 项真实 HA/Recorder 测试：[来源运行](https://github.com/mindcont/icloud3/actions/runs/38498507465)。来源仓库当时的 HACS Issues/topics 与原 icloud3 翻译格式问题不代表本独立仓库检查失败。

当前是待评审的预览准备分支，不是已发布的 GitHub Release；浏览器、真实 Traccar 和 HACS 验证门槛保留在 `docs/release-checklist.md`。后续仅修改文档不会改变上述已验证插件代码；最新 CI 状态见仓库 Actions。
