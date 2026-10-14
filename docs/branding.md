# Logo 与图标显示检查

本 Logo 用蓝色云、青绿色定位标记和同步箭头表达 iCloud3 到 Traccar 的位置同步。不是 Apple、Home Assistant 或 Traccar 官方商标。

## 资源位置

```text
/config/custom_components/icloud3_traccar/brand/
├── icon.png
├── icon@2x.png
├── logo.png
├── logo@2x.png
├── dark_icon.png
├── dark_icon@2x.png
├── dark_logo.png
└── dark_logo@2x.png
```

普通图片 256 × 256，高清图片 512 × 512，均为带透明背景的 PNG。同一配色适用于深浅背景，因此 dark 文件使用同一符号。目录名是单数 `brand`，文件名与集成域 `icloud3_traccar` 必须正确。不要放进原 `icloud3` 目录。

## 仍显示 icon not available

仓库有 Logo 不等于本地 HA 已安装资源。先检查实际安装目录中的文件是否存在、非空且能作为 PNG 打开；不要只更新 README 或复制到 /config/www。

1. 备份现有 `brand/`，将本次图标文件复制到上面的目录。不改动 Python 文件、manifest 版本、配置或数据库。
2. **完整重启 Home Assistant**，让集成加载器重新发现 brand 目录。仅重载配置条目可能仍保留发现缓存。
3. 浏览器强制刷新；必要时清除此站点的前端缓存或用无痕窗口检查。
4. 若仍异常，在浏览器开发者工具 Network 中过滤 `icloud3_traccar`，检查前端实际品牌图片请求的响应码。不要公开包含访问 token 的完整请求 URL 或请求头。

已对照 HA 2026.9.3：`loader.Integration.has_branding` 依据集成顶层 brand 目录判断；brands 服务优先读取本地资源，再尝试 CDN。故本地资源存在且重新发现后，不需要把图片提交到官方 brands 仓库。较旧 HA 若只使用官方品牌 CDN，本地图片未必显示；需要检查对应 HA 版本是否支持本地品牌资源，不应通过篡改 HA 核心或伪造 manifest 字段修补。

截图中的本地版本号与公开仓库版本可能不同。可单独更新品牌目录，不要为了 Logo 覆盖本地定制业务代码或降低版本号。

## 验证范围

已校验八个 PNG 文件名、透明通道、256/512 尺寸，以及 README 引用。实际用户 HA 的文件、缓存和图片请求未在本次操作中读取；因此不能仅凭仓库修改就声称截图中的问题已在该实例解决。

## English

Place the eight PNG assets under `/config/custom_components/icloud3_traccar/brand/`. Restart HA completely to rediscover the branding directory, then hard-refresh the frontend. On HA versions supporting local branding (source verified against 2026.9.3), local integration files take precedence over the brands CDN. Older versions may need different upstream branding support. This asset update does not change integration code, version, credentials or Recorder/Traccar data.
