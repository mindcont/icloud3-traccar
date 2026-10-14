# iCloud3 Traccar

[English](README.md) · [完整使用说明](docs/traccar.md) · [测试记录](docs/traccar-test-results.md)

独立的 Home Assistant 自定义集成：把 iCloud3 内存位置同步到 **Traccar 6.8.1**，也可以主动从 HA Recorder 导入历史位置。默认关闭，不会出现在 iCloud3 原配置页面。

当前版本为 **`0.1.0-beta.1` 预览版**。已有自动化 HTTP mock、真实 HA 和 SQLite Recorder 测试。维护者于 2026-10-14 确认真实 Traccar、浏览器界面与 HACS 安装验证通过；手工验证结果由维护者提供，自动化验证见本仓库 Actions。

## 安装

需要 HA 2025.3.4 或更新版本（当前运行测试针对该版本）、运行中的 iCloud3，以及 Traccar Web API 和独立的 OsmAnd HTTP 接收地址。适配来源为 iCloud3 3.7.5，不能保证所有其他版本的内存结构都兼容。

HACS：HACS → 自定义仓库 → 添加 `https://github.com/mindcont/icloud3-traccar` → 类型 **Integration** → 下载并重启 HA。预发布版本可能需要在 HACS 开启测试版显示。这不代表已经进入 HACS 默认列表。

手动：将目标分支/发布版本中的 `custom_components/icloud3_traccar` 整个目录复制到 `/config/custom_components/icloud3_traccar`，重启 HA。不要覆盖原 `icloud3` 目录。

两种方式安装后，都需在「设置 → 设备与服务 → 添加集成」单独搜索 **iCloud3 Traccar**。

## 配置

1. Traccar Server URL：Web 地址，例如 `https://tracking.example.com`，也可带 `/api`。
2. OsmAnd Receiver URL：例如内网 `http://traccar.internal:5055` 或已有 HTTPS 代理地址；不是 `/api/positions`。
3. API Token：需要设备读取、创建、更新和轨迹读取权限；仅发送到 REST API。编辑时留空保留已有 Token，不会显示完整 Token。
4. 启用实时同步，设置间隔、最小移动距离、字段开关、重试次数和设备。设备留空跟随当前所有未禁用 iCloud3 tracker 设备。

保存连接配置只进行 REST 读取验证；首次真实上传才验证接收端。**首次同步或主动历史导入时，会按 uniqueId 自动创建/复用 Traccar 设备**，无需手工映射表。仅安装或保存停用配置不会创建设备。

## 标识和同步

使用 HA 注册表中 iCloud3 device_tracker 原有的 **`device_id`**，原样作为 Traccar `uniqueId`；它不是 Apple 的 `icloud_device_id`，也不是实体 ID。数字 id 由 Traccar 生成。实时、历史共用同一标识；改名不改变 uniqueId。

设备管理使用 REST API；位置用官方 OsmAnd HTTP POST，传入 uniqueId，由服务器解析内部 deviceId。读回轨迹使用数字 deviceId。没有虚构的 `POST /api/positions`。

实时只读 iCloud3 内存，不读 Recorder，支持多设备、去重、重试和重启恢复。速度/方向来自相邻实时点估算，首点等信息不足时省略。按间隔采样不会保留中断期间的每一次位置变化；可主动从 Recorder 补导。

历史入口在独立集成「配置」中。时间须带时区，例如 `2026-10-01T00:00:00+08:00`，包含开始、不包含结束。支持设备选择、连续重复坐标过滤、批量处理、进度、暂停、继续、取消及显式重新导入。重启后历史保持暂停，必须手动继续；改变目标服务地址会取消旧目标历史任务。

## 隐私与状态

不读取 Apple 登录凭据、不控制 Apple 设备、不使用 HA Token、不直接写数据库。坐标在 POST 请求体中；Token 不发往 OsmAnd 接收端。独立状态 sensor、配置页面及诊断仅暴露状态与脱敏错误。

Token 保存在 HA 原生 config entry，密码框不等于磁盘加密。断点包含坐标，保存在 HA `.storage`，请保护文件权限与备份。OsmAnd 本身不使用 REST Bearer Token 认证，应通过可信网络或限制来源的 HTTPS 网关接入。代理和服务器日志由对应系统管理。

## 回滚和限制

先停用实时并暂停/取消历史，再删除独立配置条目和 `custom_components/icloud3_traccar`，重启 HA。不要删除 Traccar 设备或轨迹。不需要 Recorder 或 Traccar 数据库迁移。后续修改配置仅重载此集成。

不存在跨系统事务，无法保证严格零重复。Recorder 已清理的数据、未记录的属性、其他旧实体 ID 的历史不能凭空恢复。Traccar 端历史过滤和事件/通知规则仍然生效。更多限制见完整使用说明。

保留 [MIT 许可证](LICENSE) 和原作者署名，迁移来源见 [NOTICE](NOTICE)。
