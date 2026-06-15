## 2026-06-15 - Task: 注册链路健康检测、健康面板与 2K/4K 并发限制
### What was done
- 后台新增注册环境检测，能检查 TempMail 直连/代理、ChatGPT CSRF、auth.openai.com 和当前代理节点信息。
- 管理员概览新增中转接口、号池和图片队列健康信息，便于判断是中转不稳、号池不足还是任务排队。
- 2K/4K 图片任务新增可配置并发限制，默认同时最多运行 3 个，超出的任务继续排队。
- 本地 Docker 镜像已重新构建并重建容器，当前可通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services/config.py services/image_task_service.py services/register_health_service.py api/register.py api/system.py`
- `npm run build` in `web`
- `docker build -t chatgpt2api-auth-local:dev .`
- `Invoke-RestMethod -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回管理员登录成功。
- `Invoke-RestMethod -Uri http://localhost:8080/api/admin/overview -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `relay`、`account_pool`、`image_tasks`，且 `high_res.limit` 为 `3`。
- `Invoke-RestMethod -Uri http://localhost:8080/api/register/health -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回检测结果；本地当前未配置注册代理，接口能明确显示该状态。
- `Invoke-RestMethod -Uri http://localhost:8080/api/images/storage -Headers @{Authorization='Bearer chatgpt2api'}` 返回图片存储统计。
### Notes
- `services/register_health_service.py`：新增注册链路健康检测服务。
- `api/register.py`：新增注册健康检测接口。
- `api/system.py`：管理员概览增加中转、号池和图片任务健康数据。
- `services/config.py`：新增 `high_res_image_concurrency` 配置项，默认值为 3。
- `services/image_task_service.py`：2K/4K 任务执行前进入并发限制，排队任务等待空位。
- `web/src/lib/api.ts`：补充健康检测、概览和并发配置的前端 API 类型。
- `web/src/app/dashboard/page.tsx`：管理员首页增加注册环境检测和中转/号池健康面板。
- `web/src/app/settings/store.ts`：设置页状态增加 2K/4K 并发配置。
- `web/src/app/settings/components/settings-sections.tsx`：图片设置区域增加 2K/4K 总并发输入。
- `docs/ops-health-and-queues.md`：新增本次功能的使用和排查说明。
- 回滚方式：使用 Git 回退本次涉及文件，或在本地执行 `git restore services/register_health_service.py api/register.py api/system.py services/config.py services/image_task_service.py web/src/lib/api.ts web/src/app/dashboard/page.tsx web/src/app/settings/store.ts web/src/app/settings/components/settings-sections.tsx docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-15 - Task: 修正注册环境检测口径
### What was done
- 注册环境检测新增更贴近真实注册流程的 OpenAI 注册入口检测。
- ChatGPT CSRF 和 auth.openai.com 首页 403 改为参考警告，不再把整体环境误判为不可注册。
- 前端注册环境检测卡片改为显示“正常 / 参考 / 异常”三种状态。
- 本地 Docker 镜像已重新构建并重建容器，当前仍通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services/register_health_service.py`
- `npm run build` in `web`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-RestMethod -Uri http://localhost:8080/api/register/health -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `ok=true`，其中邮箱直连和 OpenAI 注册入口为正常，邮箱代理未配置、ChatGPT CSRF 403、auth.openai.com 首页 403 为参考警告。
### Notes
- `services/register_health_service.py`：调整注册健康检测判定逻辑并新增 OpenAI 注册入口探测。
- `web/src/lib/api.ts`：注册健康检测结果类型增加 `level`。
- `web/src/app/dashboard/page.tsx`：注册环境检测结果改为三态展示。
- `docs/ops-health-and-queues.md`：补充注册检测参考警告的解释。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/register_health_service.py web/src/lib/api.ts web/src/app/dashboard/page.tsx docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。
