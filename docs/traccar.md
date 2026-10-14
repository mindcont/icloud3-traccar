# iCloud3 可选 Traccar 同步（Traccar 6.8.1）

新增独立集成 `custom_components/icloud3_traccar`，功能默认关闭。原 `custom_components/icloud3` 的文件、Apple 登录/认证、中文翻译、事件日志和仪表盘均未修改。不存在 Apple 控制调用；不修改其他集成、HA 或 Traccar 数据库。

## 安装及配置

1. 从独立仓库的发布标签复制整个 `custom_components/icloud3_traccar` 目录到 HA 的 `config/custom_components/icloud3_traccar`。保持原 iCloud3 目录不变。本功能是第二个集成，不能假定现有 HACS 更新会自动安装它。
2. **首次安装需要重启 Home Assistant**，让 HA 发现新的集成。
3. HA「设置 → 设备与服务 → 添加集成 → iCloud3 Traccar」。可先全部留空并保持停用。
4. 填写 Traccar Web 服务地址，例如 `https://tracking.example.com` 或 `https://tracking.example.com/api`；Token 只发往该服务的 `/api`。
5. 填写 **独立的 OsmAnd HTTP 接收地址**。Traccar 默认 OsmAnd 监听端口通常是 5055，例如 `http://tracking.internal:5055`，或你已配置的 HTTPS 反向代理地址 `https://tracking.example.com/osmand`。它不是 Web API 的 `/api/positions`。反向代理需要允许表单 POST，保留请求体。配置表单只验证 REST 读取，不能在不写入位置的情况下完整验证接收端；第一次真实同步验证接收端。
6. 启用实时同步，配置间隔（5–3600 秒）、最小移动距离（米）、字段开关、重试次数（0–10）。设备留空表示当前注册的所有未禁用 iCloud3 device_tracker 设备，后续添加的设备自动纳入；选择具体设备则仅同步所选 ID。
7. API Token 输入框为密码类型，无已有值默认值；编辑时留空保留原 Token。页面仅显示已配置/未配置，诊断和状态实体不会包含 Token、URL、名称或坐标。要清除 Token，可删除此独立集成后重新添加空配置。

Token 使用 HA 原生 config entry 保存，与 HA 标准集成凭据相同。**密码选择器不等于磁盘加密**，HA `.storage/core.config_entries` 的访问和备份应由 HA 管理。本实现没有另造不受 HA 支持的“加密 secret 类型”，也不输出凭据。不需要 HA Token，不访问 Apple 账号、密码、验证码或 Token。

OsmAnd 6.8.1 接收协议本身没有 REST Bearer Token 验证。本模块不会向接收端泄露 REST Token；建议使用内网或由已有网关限制来源的 HTTPS 接收端。代码拒绝带账号/密码、查询参数、片段的 URL，禁止跟随重定向，保持 TLS 验证。

Traccar 用户需要对目标设备的读取、创建、名称更新及轨迹读取权限。不要开启该用户的“禁止报告/disableReports”，因为去重和上传结果确认需要查询历史位置。若当前用户看不到别人拥有的同 uniqueId 设备，模块不会绕过权限；创建冲突将报告失败，不生成第二个不同 uniqueId。

## 设备 ID

此版本 iCloud3 有多个标识字段：

- 本功能采用 **HA 实体注册表中 iCloud3 device_tracker 的现有 `device_id`**，与 iCloud3 `ha_device_id` 指向同一设备。
- `uniqueId` 的内容与上述 `device_id` 原样相同，不加前缀、不重新生成、不手工建立映射表。
- Apple 的 `icloud_device_id`、实体的 `unique_id=icloud3_{devicename}` 和 `device_tracker.xxx` 实体 ID 是其他标识，不作为 Traccar uniqueId。
- `GET /api/devices?uniqueId=<device_id>` 查找现有设备；找不到才 `POST /api/devices` 创建。数字 `id` 由 Traccar 分配，保存为自动生成的同步状态，查询轨迹时使用该数字 `deviceId`。
- 名称使用注册表已有的名称；下次上传时可通过 `PUT /api/devices/{id}` 更新 Traccar 名称，保留 uniqueId 和其他服务端字段。不会修改 HA/iCloud3 的名称或 ID。
- 同一进程使用按 uniqueId 的锁；创建请求响应丢失后先重新查询，再考虑重试；多个并发上传共用同一设备。
- 删除并重新创建 HA 设备通常会产生新的 device_id，因此会成为新 Traccar 设备。不会猜测两个不同 ID 是同一设备。

用户已接受的协议调整：**位置请求中的 `id` 使用 uniqueId**。官方 OsmAnd 解码器解析它并赋予位置内部数字 deviceId。不存在虚构的 `POST /api/positions`。实时与历史使用同一个 ID 解析路径。

## 实时同步流程

1. 独立定时任务按配置间隔，从已加载的 iCloud3 `GlobalVariables.Devices_by_devicename` 读取内存。
2. 使用 `loc_data_latitude`、`loc_data_longitude`、`loc_data_secs`、`dev_data_battery_level`、`loc_data_gps_accuracy` 创建不可变快照。没有导入或启动 Apple 客户端，也没有读取 Recorder。
3. 经纬度和时间均未变则跳过。移动不足最小距离也跳过；最小距离为 0 时，相同坐标、不同定位时间可上传。
4. iCloud3 当前没有标准速度/方向字段，因此根据相邻成功实时定位的距离和定位时间估算速度、方向。速度转换为节（OsmAnd 6.8.1 默认单位），方向为度。首个点或定位间隔超过一小时不估算；不伪造缺失字段。电量为百分比，精度为米。
5. 上传前把当前待发送点写入 HA Store；查询/创建/复用设备，用数字 deviceId 查询同时间、同坐标轨迹，已有则不再发送。
6. OsmAnd 使用 **POST 表单请求体**：`id, lat, lon, timestamp`，可选 `speed, bearing, batt, accuracy`。坐标不放入 URL，不解释或执行服务端返回的命令内容。
7. HTTP 成功后读取轨迹确认位置可见。若接收端返回成功但 Traccar 过滤或尚未保存该点，有限轮询后报告明确错误，不把无轨迹的 ACK 算为成功。
8. 成功保存指纹、最后成功时间、设备数字 ID 和统计。请求失败使用指数退避（1、2、4…秒，上限 30 秒），超过单次重试次数后保留待发送点，下个周期继续。设备消失时清除缓存并重新解析设备。

多个设备最多四个实时请求任务并发；任务无积压。HTTP 超时 15 秒，所有等待都是异步的。实时同步失败不会传播到 iCloud3。重启后恢复待发送点和成功指纹，无需重新登录 Apple。

这是按间隔采样，不是每一次定位变化的全量队列。服务中断期间保留每设备一个待发送点；中间变化可从 Recorder 主动补导。

## 历史导入流程

入口：「iCloud3 Traccar → 配置 → 新建历史导入」。

- 输入带时区的 ISO 时间，例如 `2026-10-01T00:00:00+08:00`，避免服务器时区歧义。
- 范围 **包含开始、不包含结束**；结束必须在当前时间之前。
- 选择设备，留空使用同步设置中的设备集合；关闭实时同步仍可主动导入历史。
- “跳过连续重复坐标”默认开启；关闭后同坐标、不同历史时间可以分别上传。
- 批量大小 1–1000，控制每批处理后让出执行权；OsmAnd 每次请求一个点，不存在伪造的批量位置 API。Recorder 每次读取一个设备的一小时窗口，内存占用主要由该窗口内记录量决定。
- 默认不允许重新导入：上传前用同数字 deviceId、原状态时间与坐标查重，重叠任务也跳过已存在轨迹。明确开启“允许重新导入”后可再次发送，可能制造重复轨迹。

导入仅通过 HA 官方 Recorder `get_significant_states` 读接口和 Recorder executor，使用只读 session，读取完整属性和属性变化，不使用原始 SQL。latitude、longitude 来自状态属性；时间使用历史状态的 `last_updated`，不是当前时间或字符串形式的区域状态。

历史导入与实时任务分开；设备解析按设备 ID 加锁，位置去重按位置指纹加锁；不同历史点的网络重试不会阻塞同设备的新实时点。断点记录设备、窗口、行偏移和末行指纹；继续时若发现 Recorder 清理或迟到记录使原偏移失效，重读当前窗口并查重，避免跳过仍然存在的记录。**成功或明确跳过后才推进**；网络/Recorder 错误暂停在失败行，可点击“继续历史导入”。暂停、取消和实时停用各自独立。HA 重启或此独立集成重载后历史任务保持暂停，必须由用户点击继续；不会自动读取 Recorder。变更目标服务器地址会清空实时目标断点并取消旧目标的历史任务，需重新发起导入。

缺失/无效坐标、缺失时间、连续重复坐标及已存在轨迹按原因计数。不会修改实体、设备或 Recorder 数据。未保存在 Recorder 的属性、已被清理的历史、实体改名前的其他 entity_id，不能凭空恢复。导入中的实体 ID 变化会暂停，避免误配设备。

## 状态面板

独立的诊断 sensor “Traccar 同步状态”可直接加入任何 HA 仪表盘；原 iCloud3 仪表盘不变。也可在“配置 → 查看同步状态”查看。

状态包括启用、连接状态、Token 是否配置、最后成功上传时间、最后设备 ID、成功/失败操作数、固定脱敏错误、创建/复用设备数，以及历史状态、进度百分比、设备索引、窗口、行偏移、处理数、成功数、失败数、跳过数与原因。

成功数记录确认的新上传；已经存在的点属于跳过。失败数包含失败操作和历史重试失败，不等同于永久丢失位置数。进度按时间窗口和设备计算，窗口内详细进度看 `processed` 和 `offset`。模块本身不打印请求、响应或异常文本到普通日志。Traccar/反向代理的请求体日志不受此模块控制。

## 文件与架构

- `const.py`：默认关闭、配置默认值、固定错误文案。
- `models.py`：快照、时间/坐标校验、指纹、移动距离、协议字段。
- `api.py`：官方 REST 设备管理/轨迹读取、OsmAnd 上传、结果确认、重试。
- `source.py`：只读注册表/内存适配器及用户请求的 Recorder 读适配器。
- `coordinator.py`：独立实时/历史任务、去重、暂停/继续、持久化、状态白名单。
- `__init__.py`：HA 安装/更新/卸载和停机任务清理。
- `config_flow.py`：独立配置流程和历史入口；`sensor.py`：状态实体；`diagnostics.py`：仅白名单状态。
- `manifest.json`、`strings.json`、`translations/en.json`、`zh-Hans.json`、`zh-Hant.json`：HA 描述和界面。
- `tests/`：回环 HTTP 及 worker/HA 适配器行为测试；HA 适配层使用明确的 doubles。
- `tests_runtime/`：单独使用真实 HA 的导入、配置与生命周期测试。
- `.github/workflows/traccar-tests.yml`：Python 3.13 + HA 2025.3.4 的验证流程。

## 测试及边界

本地执行 `python -m compileall -q custom_components/icloud3_traccar tests tests_runtime`；`python -m unittest discover -s tests -v`（依赖 aiohttp、voluptuous）。测试使用测试专用 Token 和本地 mock 端点，无 Apple 账号，无真实 HA/Traccar 设备。覆盖请求构造、device_id/uniqueId、复用/创建/重命名、并发去重、多设备、失败退避、断网恢复、接收响应丢失、Recorder 调用、时间范围、断点续传、历史/实时共用设备、Token/UI/诊断/日志脱敏、配置选项和加载/卸载。

当前云环境代理返回 HTTP 503，无法通过 Git 克隆或 pip 安装 HA。源码用 GitHub 连接工具按固定提交获取，voluptuous 0.15.2 的源码也通过同一工具获取到仓库外测试目录。本地 Recorder 及 HA 生命周期是 adapter doubles 行为测试，**不等于真实 HA 数据库或浏览器 UI 测试**。首轮真实 HA 导入、配置、加载/卸载测试已在 GitHub Actions 通过；后续完整结果见分支 Actions 和 `docs/traccar-test-results.md`。Traccar 6.8.1 协议与字段已对照官方该版本源码；未连接生产 Traccar。

OsmAnd HTTP ACK、Traccar 异步存储与 HA Store 之间没有分布式事务；读回检查降低响应丢失和重启重复风险，但服务端延迟、过滤、其他客户端并发或启用重新导入时不能保证严格 exactly-once。已有 Traccar 设备/轨迹不会删除。历史导入可能触发 Traccar 服务端既有事件、通知和“最新位置”逻辑，取决于服务端配置；代码不改变这些设置。若服务器设置了拒绝历史位置的过滤规则，应先由管理员检查规则，不能用数据库写入绕过。

## 回滚、重启与数据库

- 停止：独立集成中关闭实时同步，暂停/取消历史任务；不影响 iCloud3。
- 回滚：在 HA 删除 `iCloud3 Traccar` 配置条目，移除 `custom_components/icloud3_traccar` 目录并重启 HA。也可恢复安装前备份。不要删除 Traccar 设备或轨迹。
- 成功断点/待发送坐标只存于 `.storage/icloud3_traccar.<entry_id>`，不是数据库迁移；回滚可保留该文件，确认不再需要恢复后可仅清理此功能自己的文件。
- **不需要 Recorder 或 Traccar 数据库迁移**；原集成配置不迁移。
- 首次安装/删除代码需要 HA 重启。之后修改配置由此独立集成重载生效，无需重启 HA；历史断点保留并等待手动继续。


## 对照的官方协议来源

- [Traccar v6.8.1 OsmAndProtocolDecoder](https://github.com/traccar/traccar/blob/v6.8.1/src/main/java/org/traccar/protocol/OsmAndProtocolDecoder.java)
- [Traccar v6.8.1 DeviceResource](https://github.com/traccar/traccar/blob/v6.8.1/src/main/java/org/traccar/api/resource/DeviceResource.java)
- [Traccar v6.8.1 OpenAPI](https://github.com/traccar/traccar/blob/v6.8.1/openapi.yaml)
