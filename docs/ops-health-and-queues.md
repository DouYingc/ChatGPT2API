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
- 当前限制是单进程内限制；如果以后服务扩成多副本，需要再做跨进程队列。

## 2K/4K 参考图上传

2K/4K 带参考图时会走中转接口的 `/images/edits`，请求格式为 multipart。

注意事项：

- 这条路径不再使用 `curl_cffi` 的 `files=` 参数，避免出现 `files is not supported, use multipart`。
- multipart 请求由 Node helper 发送，和 2K/4K 文生图一样会读取全局代理配置。
- 日志中的 `proxy_used=true/false` 可以用于判断请求是否实际走了代理。

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
