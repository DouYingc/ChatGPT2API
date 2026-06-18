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

## 2026-06-16 - Task: 修复 2K/4K 参考图中转 multipart 上传
### What was done
- 修复 2K/4K 带参考图调用 Duck / 中转接口时报 `files is not supported, use multipart` 的问题。
- 中转接口 `/images/edits` 上传改为由 Node helper 发送 multipart，不再使用 `curl_cffi files=`。
- multipart 上传继续读取全局代理配置，方便服务器走 `mihomo`。
- 本地 Docker 镜像已重新构建并重建容器，当前仍通过 `http://localhost:8080` 访问。
### Testing
- `node --check scripts/high_res_image_relay_fetch.mjs`
- `python -m py_compile services/high_res_image_relay_service.py`
- 使用 `https://postman-echo.com/post` 回显接口验证 Node helper 能发送 multipart 表单和图片文件字段。
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
### Notes
- `scripts/high_res_image_relay_fetch.mjs`：新增 multipart body 构造，并让 multipart 请求也走 Node helper 的代理发送逻辑。
- `services/high_res_image_relay_service.py`：新增 Node helper multipart 调用，移除 `/images/edits` 路径中的 `curl_cffi files=`。
- `docs/ops-health-and-queues.md`：补充 2K/4K 参考图上传说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore scripts/high_res_image_relay_fetch.mjs services/high_res_image_relay_service.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-16 - Task: 中转生图改为非流式返回
### What was done
- 将 Duck / 中转接口生图请求从流式返回改为非流式返回。
- 移除流式专用的 `partial_images` 参数，减少 2K/4K 长连接被代理或接口中途断开的概率。
- 本地 Docker 镜像已重新构建并重建容器，当前仍通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services/high_res_image_relay_service.py`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-RestMethod -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `ok=true`。
### Notes
- `services/high_res_image_relay_service.py`：中转生图请求体改为 `stream=false`，并移除 `partial_images`。
- `docs/ops-health-and-queues.md`：补充中转非流式返回说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/high_res_image_relay_service.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-16 - Task: 重构用户端画图页布局
### What was done
- 将用户端画图页重构为桌面双栏工作台：左侧常驻历史对话，右侧集中展示当前画布、生成结果和输入区。
- 移动端保留历史弹窗入口，避免小屏被侧栏挤占。
- 顶部状态区集中展示当前画布标题、额度和运行任务数，输入区固定在底部，降低核心操作寻找成本。
- 为移动端历史按钮补充可访问名称。
### Testing
- `npm run build` in `web`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-RestMethod -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `ok=true`。
- `Invoke-WebRequest -Uri http://localhost:8080/image -UseBasicParsing` 返回 `200`。
- 使用 Chrome/Playwright 检查 `1440x900` 和 `390x844` 视口：画布标题、输入框可见；桌面左侧工作台可见；手机历史按钮可见；未发现主要按钮/输入区横向撑破。
### Notes
- `web/src/app/image/page.tsx`：重构画图页主布局，新增桌面左侧工作台和移动端顶部入口。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore web/src/app/image/page.tsx progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-16 - Task: 中转请求补充 resolution 参数
### What was done
- 2K/4K 中转请求在发送像素尺寸 `size` 的同时，补充发送 `resolution=2k/4k`。
- 返回结果中补充 `target_resolution`，便于日志判断实际请求的清晰度。
- 保留原有像素尺寸映射，兼容认 `size=3840x2160` 的中转接口。
### Testing
- `python -m py_compile services/high_res_image_relay_service.py`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-RestMethod -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `ok=true`。
### Notes
- `services/high_res_image_relay_service.py`：中转生图请求体补充 `resolution` 字段。
- `docs/ops-health-and-queues.md`：补充中转高清参数兼容说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/high_res_image_relay_service.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-16 - Task: 优化画图页色彩与参数菜单定位
### What was done
- 调整画图页工作台、顶部状态区和输入区的色彩层级，减少页面整体单调感。
- 修复张数、比例、清晰度菜单在桌面端脱离按钮、在移动端贴边溢出的问题。
- 移动端底部参数栏由横向滚动改为自动换行，并为发送按钮预留固定空间，避免清晰度按钮和发送按钮互相压住。
- 本地 Docker 镜像已重新构建并重建容器，当前仍通过 `http://localhost:8080` 访问。
### Testing
- `npm run build` in `web`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-RestMethod -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `ok=true`。
- `Invoke-WebRequest -Uri http://localhost:8080/image -UseBasicParsing` 返回 `200`。
- 使用浏览器检查 `1440x900` 和 `390x844` 视口：桌面无横向溢出；手机端张数、比例、清晰度三个菜单均在视口内；底部参数栏不再压住发送按钮。
### Notes
- `web/src/app/image/page.tsx`：调整画图页背景、侧栏、顶部状态区的色彩层级。
- `web/src/app/image/components/image-composer.tsx`：调整输入区配色、参数按钮菜单定位和移动端换行布局。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore web/src/app/image/page.tsx web/src/app/image/components/image-composer.tsx progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-16 - Task: 收敛画图页视觉层级
### What was done
- 将画图页从多色渐变风格收敛为中性工作台风格，减少蓝绿黄堆叠造成的杂乱感。
- 移除空状态中的彩色光斑背景和大标题，改为更轻的空画布提示。
- 张数和清晰度上拉框改为桌面端按按钮中心展开，减少弹层偏移感。
- 去掉主内容区域、侧栏和输入框外层的大投影，避免出现“卡片外又套阴影框”的视觉问题。
- 本地 Docker 镜像已重新构建并重建容器，当前仍通过 `http://localhost:8080` 访问。
### Testing
- `npm run build` in `web`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-RestMethod -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `ok=true`。
- `Invoke-WebRequest -Uri http://localhost:8080/image -UseBasicParsing` 返回 `200`。
### Notes
- `web/src/app/image/page.tsx`：收敛主页面配色，并移除主内容区和侧栏的大投影。
- `web/src/app/image/components/image-composer.tsx`：收敛输入区配色、居中张数/清晰度弹层，并移除输入框外层大投影。
- `web/src/app/image/components/image-results.tsx`：移除空状态彩色光斑和大标题，改为轻量空画布提示。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore web/src/app/image/page.tsx web/src/app/image/components/image-composer.tsx web/src/app/image/components/image-results.tsx progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-16 - Task: 移除画图页外层卡片壳
### What was done
- 将画图页外层背景改为满宽白底，不再露出全局网格背景。
- 拆掉主内容区和侧栏的外层圆角卡片样式，改为侧边栏加内容区的工作台布局。
- 保留左侧与右侧之间的细分隔线，避免页面完全失去结构。
- 本地 Docker 镜像已重新构建并重建容器，当前仍通过 `http://localhost:8080` 访问。
### Testing
- `npm run build` in `web`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-RestMethod -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `ok=true`。
- `Invoke-WebRequest -Uri http://localhost:8080/image -UseBasicParsing` 返回 `200`。
### Notes
- `web/src/app/image/page.tsx`：移除画图页外层灰底、圆角主卡片和侧栏卡片壳。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore web/src/app/image/page.tsx progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-16 - Task: 回滚画图页重构尝试
### What was done
- 按用户反馈撤回画图页重构尝试，恢复 `page.tsx`、`image-composer.tsx`、`image-results.tsx` 到仓库原有版本。
- 保留其它非画图页 UI 的既有改动，不触碰本地配置文件。
- 本地 Docker 镜像已重新构建并重建容器，当前仍通过 `http://localhost:8080` 访问。
### Testing
- `npm run build` in `web`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-RestMethod -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `ok=true`。
- `Invoke-WebRequest -Uri http://localhost:8080/image -UseBasicParsing` 返回 `200`。
- `git status --short -- web/src/app/image/page.tsx web/src/app/image/components/image-composer.tsx web/src/app/image/components/image-results.tsx` 无输出，确认三个 UI 文件已恢复干净。
### Notes
- `web/src/app/image/page.tsx`：恢复到仓库原有版本。
- `web/src/app/image/components/image-composer.tsx`：恢复到仓库原有版本。
- `web/src/app/image/components/image-results.tsx`：恢复到仓库原有版本。
- `progress.md`：追加本轮回滚记录。
- 回滚方式：本轮是回滚操作；如需再次恢复重构尝试，只能从当前对话记录或 Git 暂存/补丁重新应用相关 UI 改动。

## 2026-06-16 - Task: 增加图片自动清理与友好失败提示
### What was done
- 服务启动时继续清理过期图片和失效缩略图，并新增后台每日自动清理，复用图片管理页手动清理的保留天数和保护规则。
- 普通用户看到的生图失败提示增加归类：额度不足、账号池限流/额度耗尽、中转接口连接失败、代理连接异常、内容策略命中。
- 前后端错误文案映射保持一致，避免浏览器端把后端友好文案重新改回泛化提示。
- 本地 Docker 镜像已重新构建并重建容器，当前仍通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile api/app.py services/image_service.py services/public_errors.py`
- 使用 `services.public_errors.public_error_message` 样例验证中转、代理、账号池、额度、内容策略错误会映射到预期中文提示。
- `npm run build` in `web`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-RestMethod -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `ok=true`。
- `Invoke-WebRequest -Uri http://localhost:8080/image -UseBasicParsing` 返回 `200`。
- `GET /api/images/storage` 返回当前存储统计与 `retention_days=15`。
- `POST /api/images/cleanup` 返回 `removed_images=0`、`removed_thumbnails=0`，确认清理入口正常。
### Notes
- `api/app.py`：应用生命周期中启动图片自动清理线程，并使用完整清理函数处理缩略图。
- `services/image_service.py`：新增每日图片清理后台线程，复用现有清理逻辑。
- `services/public_errors.py`：增强后端公共错误文案归类。
- `web/src/lib/public-error.ts`：同步前端公共错误文案归类。
- `docs/ops-health-and-queues.md`：补充图片自动清理和失败提示归类说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore api/app.py services/image_service.py services/public_errors.py web/src/lib/public-error.ts docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 修复图片任务长期 running 并重建本地 Docker
### What was done
- 为已进入 `running` 的图片任务增加生命周期保护，超过 `image_poll_timeout_secs + 60` 秒未返回时自动标记失败并返还预扣额度。
- 任务超时后如果后台请求迟到返回，不再覆盖已失败/已取消状态，避免前端重新被旧结果带偏。
- 补充单测覆盖 running 超时和迟到结果忽略场景。
- 本地 Docker 镜像已重新构建并重建容器，当前通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services/image_task_service.py`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `200`。
- `docker exec -w /app chatgpt2api-auth-local uv run python -m unittest test.test_image_task_service` 通过，`Ran 5 tests`。
### Notes
- `services/image_task_service.py`：增加 running 任务超时失败、额度返还和迟到结果忽略逻辑。
- `test/test_image_task_service.py`：增加 running 超时与迟到结果保护测试。
- `docs/ops-health-and-queues.md`：补充图片任务 running 超时行为说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/image_task_service.py test/test_image_task_service.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 优化账号池图片任务无结果重试
### What was done
- 排查 5 张并发图生图时 3 张快速成功、2 张长期卡住的问题，确认卡点在 ChatGPT 网页生图会话进入轮询后没有及时产出图片文件。
- 非流式 1K 账号池图片任务遇到“只有进度但无图片结果”时，会标记当前账号失败并换下一个可用账号重试。
- 将本地测试配置 `image_poll_timeout_secs` 从 240 秒调整为 90 秒，避免坏会话长时间占住界面。
- 本地 Docker 镜像已重新构建并重建容器，当前通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services/protocol/conversation.py services/protocol/openai_v1_image_edit.py services/protocol/openai_v1_image_generations.py services/image_task_service.py`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `200`。
- `docker exec -w /app chatgpt2api-auth-local uv run python -m unittest test.test_codex_image_route test.test_image_task_service` 通过，`Ran 9 tests`。
- `docker exec -w /app chatgpt2api-auth-local uv run python -c "from services.config import config; print(config.image_poll_timeout_secs)"` 输出 `90`。
### Notes
- `services/protocol/conversation.py`：为非流式图片请求增加无图片结果后的换账号重试逻辑。
- `services/protocol/openai_v1_image_edit.py`：图生图非流式任务启用进度后重试策略。
- `services/protocol/openai_v1_image_generations.py`：文生图非流式任务启用进度后重试策略。
- `config.json`：本地图片轮询超时调整为 90 秒。
- `test/test_codex_image_route.py`：增加账号池无结果换账号测试，并隔离高分辨率路由配置。
- `test/test_image_task_service.py`：放宽 running 超时测试窗口，适配 Docker 测试环境。
- `docs/ops-health-and-queues.md`：补充账号池无结果重试与建议轮询时间。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/protocol/conversation.py services/protocol/openai_v1_image_edit.py services/protocol/openai_v1_image_generations.py config.json test/test_codex_image_route.py test/test_image_task_service.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 识别生图工具参数文本并换账号重试
### What was done
- 排查 `{"prompt":null,"size":"1792x1024","n":1...}` 这类失败信息，确认它是上游返回的生图工具参数文本，不是额度或账号登录错误。
- 非流式账号池图片任务遇到这类参数文本时，不再直接失败，而是标记当前账号失败并换下一个可用账号重试。
- 本地 Docker 镜像已重新构建并重建容器，当前通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services/protocol/conversation.py`
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `200`。
- `docker exec -w /app chatgpt2api-auth-local uv run python -m unittest test.test_codex_image_route test.test_image_task_service` 通过，`Ran 10 tests`。
### Notes
- `services/protocol/conversation.py`：识别生图工具参数文本，并在非流式任务中换账号重试。
- `test/test_codex_image_route.py`：增加参数文本无图片结果后换账号成功的测试。
- `docs/ops-health-and-queues.md`：补充参数文本无图片结果的处理说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/protocol/conversation.py test/test_codex_image_route.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。
