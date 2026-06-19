# 运维健康检测与 2K/4K 队列说明

本文记录后台新增的注册链路检测、健康面板和 2K/4K 并发限制，方便后续本地验证和服务器排查。

## 本地访问

本地 Docker 容器启动后访问：

```text
http://localhost:8080
```

如果页面没有显示新功能，先在浏览器按 `Ctrl+F5` 强制刷新。

## 注册环境检测

入口：管理员首页 / 概览页。

检测内容：

- TempMail 直连是否可用。
- TempMail 通过注册代理是否可用。
- OpenAI 注册入口 `auth.openai.com/api/accounts/authorize` 是否可用。
- `https://chatgpt.com/api/auth/csrf` 是否可用，该项只作为参考。
- `https://auth.openai.com` 首页是否可用，该项只作为参考。
- 当前注册代理地址和可识别到的 mihomo 节点名。

接口：

```text
POST /api/register/health
```

用途：

- 邮箱直连失败，通常优先看服务器 IP 是否被 TempMail 限制。
- 邮箱代理成功但直连失败，说明注册邮箱链路应走代理。
- OpenAI 注册入口失败，优先切换代理节点。
- ChatGPT CSRF 或 auth.openai.com 首页显示 403 时，不一定影响注册；如果 OpenAI 注册入口正常，可以先按参考警告处理。
- 代理节点为空，说明本地/服务器未配置注册代理，或无法访问 mihomo 控制接口。

## 中转接口与号池健康面板

入口：管理员首页 / 概览页。

展示内容：

- Duck / 中转接口今日成功率。
- 最近失败原因。
- 今日平均耗时。
- 号池可用账号数。
- 限流、异常、停用账号数。
- 图片队列中任务数。
- 2K/4K 当前运行数与并发上限。

接口：

```text
GET /api/admin/overview
```

## 1K 账号池并发分配

配置项：

```json
{
  "image_account_concurrency": 5
}
```

行为：

- 该值表示单个账号最多同时承接多少个 1K 账号池图片任务。
- 分配账号时会优先选择当前没有生图任务的空闲账号；只有没有空闲账号时，才会在未达到该上限的忙账号里复用。
- 因此后台填写任意正整数时，账号池都会按当前配置动态控制复用上限，不需要改代码。

## 2K/4K 并发限制

配置项：

```json
{
  "high_res_image_concurrency": 3
}
```

默认值为 `3`。入口：管理员设置页的图片设置区域。

行为：

- 只有 `2k`、`4k` 图片任务会进入该并发限制。
- 超过并发上限的 2K/4K 任务会继续保持排队，等前面的任务结束再开始。
- 1K 任务不受这个限制影响。
- 已进入 `running` 的图片任务如果超过 `image_poll_timeout_secs + 60` 秒仍未返回，会在任务查询/概览刷新时自动标记为失败并返还预扣额度，避免前端长期停留在“正在创建图片”。
- 1K 账号池的非流式图片任务如果上游返回 `{"prompt": null, "size": ...}` 或 `{"prompt": "...", "size": "...", "n": 1}` 这类生图工具参数文本，会继续轮询当前 conversation 的图片结果，不会立即跳过轮询或换账号重开。
- 图片 SSE 已进入 `generating` 但长时间没有任何事件时，会主动结束当前流式等待，并按最近 conversation 恢复后继续轮询图片，避免任务一直停在“生成中”直到外层运行超时。
- 对已经进入图片轮询的任务，使用完整 `image_poll_timeout_secs` 作为等待上限，不再把单次轮询时间砍半。
- 已经收到上游进度、消息或图片指针的任务会留在当前账号/当前 conversation 上完成或失败；只有请求尚未真正开始前的 429、token 失效、连接异常等账号级问题才会切换账号。
- 上游 SSE 或 conversation 明细只要出现 `image_asset_pointer`、`file-service://...` 或 `sediment://...` 图片指针，都会被当作已生成图片处理；这覆盖了图片结果落在 assistant 消息或 patch 事件里的情况。
- 图片任务查询可返回 `progress`、`elapsed_secs` 和 `duration_ms`；画图页保留当前项目自身的展示逻辑，不整页搬参考项目 UI。
- 当前限制是单进程内限制；如果以后服务扩成多副本，需要再做跨进程队列。

## 2K/4K 参考图上传

2K/4K 带参考图时会走中转接口的 `/images/edits`，请求格式为 multipart。

注意事项：

- 这条路径不再使用 `curl_cffi` 的 `files=` 参数，避免出现 `files is not supported, use multipart`。
- multipart 请求由 Node helper 发送，和 2K/4K 文生图一样会读取全局代理配置。
- 日志中的 `proxy_used=true/false` 可以用于判断请求是否实际走了代理。
- 中转生图请求默认使用非流式返回，避免长时间流式连接在大图生成过程中被代理或接口断开。
- 中转请求会同时发送像素尺寸 `size` 和清晰度 `resolution`，兼容只识别 `resolution=2k/4k` 的中转接口。

## 图片自动清理

配置项：

```json
{
  "image_retention_days": 15,
  "cleanup_protect_gallery": true,
  "cleanup_protect_user_images": true
}
```

行为：

- 服务启动时会清理一次过期图片和失效缩略图。
- 服务运行期间会每天自动清理一次，使用和图片管理页“清理过期图片”相同的规则。
- `cleanup_protect_gallery=true` 时，已发布到画廊的图片不会被自动删除。
- `cleanup_protect_user_images=true` 时，有用户归属的图片不会被自动删除；匿名或 admin 自己生成且无归属的图片仍按保留天数清理。

## 失败提示归类

普通用户看到的生图失败文案会做归类，避免暴露上游原始错误：

- 额度不足：提示用户兑换额度。
- 账号池限流或额度耗尽：提示稍后重试。
- 中转接口连接失败：提示稍后重试或切换代理节点。
- 代理连接异常：提示切换节点后重试。
- 内容策略命中：提示调整提示词。

管理员日志仍保留更详细的原始错误，方便排查中转、代理和号池问题。

## 参考项目生图链路

当前本地 8080 项目保留自己的画图页 UI、鉴权、额度、账号权限和高清配置；仅将后端生图执行、上游结果识别、图片保存和必要输入解析对齐 `G:\desktop\image\chatgpt2api` 的稳定链路。

影响范围：

- 画图页不整页搬参考项目，输入框、结果区和本地会话状态保持当前项目实现。
- `/api/image-tasks`、`/v1/images/generations`、`/v1/images/edits` 保留当前项目的 `resolution`、取消任务、额度、权限和频率限制，并使用参考项目的上游调用与结果收集方式。
- 图片结果通过 `image_storage_service` 保存并生成 `/images/...` 访问地址。
- 上游请求的代理参数处理也已对齐参考项目，支持按账号读取代理配置并兼容 `curl_cffi` Session 参数。
- 账号池遇到工具参数 JSON 或纯文字无图时，会按参考项目方式继续轮询当前 conversation；只有 429 限流、token 失效、请求尚未开始前的连接异常等账号级问题才会换下一个可用账号。

## 画图页前端性能

画图页会轮询图片任务状态。为了避免轮询期间页面卡顿：

- 轮询结果没有变化时，不更新当前会话对象，也不刷新 `updatedAt`，从而减少整页重渲染和 IndexedDB 写入。
- 已有 `/images/...` URL 的成功图片优先使用 URL 展示，并在本地会话归一化时丢弃同一张图的 base64 副本，避免历史越多本地缓存越重。
- 灯箱所需的成功图片列表和索引会缓存到当前渲染周期内，避免每个图片格子重复扫描全部历史结果。
- 结果区使用稳定组件引用；输入框打字、设置变化或顶部状态刷新时，如果当前对话数据没变，历史结果区不会跟着整块重渲染。
- 结果容器滚动时，底部渐隐条只在显隐状态真正变化时才触发 React 状态更新，降低滚动时的额外渲染压力。

## 本地常用验证命令

```powershell
$h=@{Authorization='Bearer chatgpt2api'}
Invoke-RestMethod -Uri http://localhost:8080/auth/login -Method Post -Headers $h
Invoke-RestMethod -Uri http://localhost:8080/api/admin/overview -Headers $h
Invoke-RestMethod -Uri http://localhost:8080/api/register/health -Method Post -Headers $h
```

查看本地容器：

```powershell
docker ps --filter name=chatgpt2api-auth-local
docker logs --tail=100 chatgpt2api-auth-local
```
