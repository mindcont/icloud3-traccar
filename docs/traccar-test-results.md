# Traccar 验证记录

迁移来源分支：`mindcont/icloud3:feature/traccar-sync`。原始提交：`9577d4bb5fe3ca0929de928f8475205ea83ac994`。

## 本地验证

- Python 3.12.14 语法编译：通过（新增集成、两套测试）。
- 新增 JSON（manifest、英文/简体/繁体界面）：解析通过。
- `python -m unittest discover -s tests -v`：**47 项通过**。
- 实际回环 HTTP 服务：aiohttp web + 实际 ClientSession；模拟 Traccar 6.8.1 官方 REST 与 OsmAnd 协议。
- 原 `custom_components/icloud3` 文本文件 diff：为空；发布时以远端原 tree 为基底保留全部二进制文件和历史文档。

| 要求 | 验证行为 |
| --- | --- |
| API 请求构造 | REST Bearer、uniqueId 查询、POST 表单、数字 deviceId 轨迹读取；没有 POST /api/positions |
| 设备标识 | 使用注册表原 device_id，实体 ID 不变；实时/历史共用设备 |
| 设备复用/创建/重命名 | 复用原数字 ID、自动创建、保留 uniqueId/其他属性、创建响应丢失后重新查询 |
| 多设备 | 默认全选/明确选择、并发同设备不重复创建 |
| 实时去重 | 相同点和时间跳过、时间变化上传、最小移动距离过滤 |
| 网络/不可用 | 固定错误、退避 1/2 秒、401 不重试、重启后恢复 pending、异步等待不阻塞事件循环、慢历史点不阻塞同设备的新实时点 |
| 历史读取 | Recorder executor/完整属性/属性变化/只读 API 参数；实时从不调用 Recorder |
| 时间范围 | 包含开始、不包含结束、窗口边界、拒绝未来与反向范围、原始时间上传 |
| 断点续传 | 失败行不推进、重启保持暂停、手动继续、Recorder 清理后断点校验、重复任务查重、明确允许重新导入 |
| 缺失/重复数据 | 缺坐标/时间记录跳过原因、连续相同坐标可跳过 |
| 安全 | Token 密码框无默认值、留空保留、UI/诊断/日志不含测试 Token/坐标/服务端原始异常 |
| 加载/配置/卸载 | 实际模块函数在 HA doubles 下执行；选项菜单、表单、动作、空配置加载/卸载 |
| 隔离 | Apple 控制/原始 SQL/数据库客户端/DELETE 路径扫描无命中；未触及生产设备 |

## 真实 HA 验证

独立 `tests_runtime` 以 Home Assistant 2025.3.4 / Python 3.13 运行，测试真实 HA 模块导入、真实选择器/配置表单、空配置安装/卸载、Store 和事件助手。配置了分支 Actions 工作流。

本地安装 HA 被环境代理 HTTP 503 阻断，不能将 doubles 结果描述为真实 HA 通过。首轮 Actions 已通过 42 项行为测试及 3 项真实 HA 测试：[运行记录](https://github.com/mindcont/icloud3/actions/runs/38497647857)。真实 Recorder SQLite 读取（含状态不变、仅坐标属性变化）及另外 3 项真实 HA 测试已通过：[真实 Recorder 运行记录](https://github.com/mindcont/icloud3/actions/runs/38498162057)。浏览器界面尚未验证；无生产 Token/Apple 账号，也没有连接真实 Traccar 或修改真实位置。

## 仓库其他检查

首轮 hassfest 检查两个集成，仅原 `icloud3` 被标记为无效（既有 `xdescription`、占位符/URL/空白翻译格式）；新增 `icloud3_traccar` 未被标记无效。为保持原功能与中文界面不变，没有修改原翻译。

HACS Action 失败原因为仓库 Issues 未启用、缺少有效 topics；integration_manifest 和 hacsjson 已通过。未更改仓库设置或跳过检查。

最终代码增加了 Receiver ACK 后轨迹读回、Recorder 行偏移指纹校验、同设备不同历史/实时点的锁隔离。当前本地 47 项通过；分支持续集成同时运行这 47 项和 4 项真实 HA/Recorder 测试。最新运行见 [Traccar bridge tests](https://github.com/mindcont/icloud3-traccar/actions)。
