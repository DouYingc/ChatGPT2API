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

## 2026-06-19 - Task: 修复生图 SSE 生成中空流卡住
### What was done
- 修复 1K 图片任务进入 `generating` 后上游 SSE 长时间没有事件时一直等待到外层任务超时的问题。
- 图片 SSE 空闲超过短等待阈值后会主动关闭流式等待，转入最近 conversation 恢复和图片轮询流程。
- 对没有任何 SSE 事件的图片模型请求，也按图片任务处理并尝试恢复 conversation，不再直接落入“无结果”消息。
### Testing
- `docker run --rm -v "G:\gpt\RemotePinee-ChatGPT2API:/src" -w /src -e UV_PROJECT_ENVIRONMENT=/app/.venv chatgpt2api-auth-local:dev uv run --with pytest pytest -q test/test_codex_image_route.py test/test_image_task_service.py test/test_account_image_capabilities.py` 通过，`40 passed, 1 warning, 8 subtests passed`。
### Notes
- `services/openai_backend_api.py`：为图片 SSE 增加空闲超时读取兜底，空流时关闭响应让后续轮询接管。
- `services/protocol/conversation.py`：让无 SSE 事件的图片模型请求也进入 conversation 恢复/轮询流程，并使用请求开始时间匹配最近 conversation。
- `test/test_codex_image_route.py`：新增空流恢复 conversation 并轮询到图片的覆盖。
- `docs/ops-health-and-queues.md`：补充 SSE 空流卡住的排障说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/openai_backend_api.py services/protocol/conversation.py test/test_codex_image_route.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 构建本地镜像并真实验证 5 张并发生图
### What was done
- 重新构建当前本地镜像 `chatgpt2api-auth-local:dev`。
- 使用同样的 `data` 和 `config.json` 挂载重启本地 `chatgpt2api-auth-local` 容器到 `http://127.0.0.1:8080`。
- 通过页面同一路径 `/api/image-tasks/generations` 提交 5 个 1K 文生图任务，验证并发任务能全部完成。
### Testing
- `docker build -t chatgpt2api-auth-local:dev .` 通过。
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/image` 返回 `200`。
- 第一轮真实 5 任务测试：`4/5` 成功，剩余 1 个卡在 `generating` 后因外层运行超时失败，用于确认 SSE 空流问题。
- 修复 SSE 空流后第二轮真实 5 任务测试：`5/5` 成功，总耗时约 `50.2s`，5 个任务均返回 `data=1`。
### Notes
- `progress.md`：追加本地镜像构建、容器重启和真实 5 张并发生图验证记录。
- 回滚方式：代码回滚见上一条记录；本地容器可重新执行旧镜像构建后的 `docker rm -f chatgpt2api-auth-local` 和同参数 `docker run`。

## 2026-06-19 - Task: 限制单个上游轮询会话占用整图预算
### What was done
- 继续排查 5 张并发生图成功率低的问题，确认成功任务会走到 `image_poll_hit` 并下载图片，失败任务分为工具参数 JSON 和真实轮询超时两类。
- 将 1K 账号池非流式图片任务的单账号图片轮询尝试限制为总 `image_poll_timeout_secs` 的一半，避免一个坏上游会话吃完整张图预算。
- 保持整张图仍受后台 `image_poll_timeout_secs` 总预算约束；该改动不会把页面配置改短。
- 本地 Docker 镜像已重新构建并重建容器，当前通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services/protocol/conversation.py`
- `docker exec chatgpt2api-auth-local sh -lc 'cd /app && uv run python -m unittest test.test_codex_image_route'` 通过，`Ran 8 tests`。
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/` 返回 `200`。
### Notes
- `services/protocol/conversation.py`：账号池重试时将单账号轮询尝试限制为总等待预算的一半。
- `test/test_codex_image_route.py`：增加单账号轮询尝试按总超时一半传入的测试。
- `docs/ops-health-and-queues.md`：补充单账号轮询尝试上限说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/protocol/conversation.py test/test_codex_image_route.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 校准图片账号池重试总等待时间
### What was done
- 排查服务器 5 张并发只出 2-3 张的问题，确认近期失败变多主要来自短轮询时间、账号池网页生图波动，以及重试每轮重新累计超时造成的长等待/失败暴露。
- 将非流式账号池图片任务的重试改为共享同一张图的总等待预算，避免设置 70 秒后每换一个账号又重新等待一轮 70 秒。
- 将 running 兜底缓冲从 60 秒收敛到 15 秒，减少前端长期停在“正在创建图片”的时间。
- 本地 Docker 镜像已重新构建并重建容器，当前通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services/protocol/conversation.py services/openai_backend_api.py services/image_task_service.py`
- `docker exec -w /app chatgpt2api-auth-local uv run python -m unittest test.test_codex_image_route` 通过，`Ran 6 tests`。
- `docker exec -w /app chatgpt2api-auth-local uv run python -m unittest test.test_image_task_service` 通过，`Ran 5 tests`。
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/auth/login -Method Post -Headers @{Authorization='Bearer chatgpt2api'}` 返回 `200`。
### Notes
- `services/protocol/conversation.py`：账号池非流式图片重试共享总截止时间，并把剩余时间传给上游图片轮询。
- `services/openai_backend_api.py`：图片结果解析支持传入单次轮询超时时间。
- `services/image_task_service.py`：running 兜底缓冲改为 15 秒。
- `test/test_codex_image_route.py`：增加总截止时间到期后不继续换账号的测试。
- `docs/ops-health-and-queues.md`：说明图片轮询超时是整张图的总等待预算。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/protocol/conversation.py services/openai_backend_api.py services/image_task_service.py test/test_codex_image_route.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 优先使用空闲账号承接并发生图
### What was done
- 调整 1K 账号池图片任务的账号分配策略：并发请求会先分散到当前没有生图任务的空闲账号。
- 当所有可用账号都已在忙时，再按 `image_account_concurrency` 的单账号并发上限选择负载最低的账号复用。
- 保持后台配置动态生效；该值没有写死，设置为 `3`、`5`、`6` 时都会按当前配置参与选择。
- 本地 Docker 镜像已重新构建并重建容器，当前通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services/account_service.py`
- `docker exec chatgpt2api-auth-local sh -lc 'cd /app && uv run python -m unittest test.test_account_image_capabilities'` 通过，`Ran 21 tests`。
- `docker exec chatgpt2api-auth-local sh -lc 'cd /app && uv run python -m unittest test.test_codex_image_route'` 通过，`Ran 6 tests`。
- `docker exec chatgpt2api-auth-local sh -lc 'cd /app && uv run python -m unittest test.test_image_task_service'` 通过，`Ran 5 tests`。
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/` 返回 `200`。
- `docker exec chatgpt2api-auth-local sh -lc 'cd /app && uv run python - <<\"PY\" ...'` 输出 `image_account_concurrency = 5`。
### Notes
- `services/account_service.py`：账号池选取时优先空闲账号，没有空闲账号时按最低 inflight 数复用。
- `test/test_account_image_capabilities.py`：增加并发值为 `3`、`5`、`6` 时分散账号的测试，以及忙账号不会优先复用的测试。
- `docs/ops-health-and-queues.md`：补充 1K 账号池并发分配规则。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/account_service.py test/test_account_image_capabilities.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 明确账号并发配置按后台填写值生效
### What was done
- 将账号池并发测试从固定示例值改为连续配置范围验证，避免误解为只支持个别数字。
- 调整运维说明，明确 `image_account_concurrency` 按后台填写的任意正整数动态生效。
### Testing
- `docker exec chatgpt2api-auth-local sh -lc 'cd /app && uv run python -m unittest test.test_account_image_capabilities'` 通过，`Ran 21 tests`。
### Notes
- `test/test_account_image_capabilities.py`：账号池并发测试改为验证 `1` 到 `8` 的连续配置值都会按当前配置分配账号。
- `docs/ops-health-and-queues.md`：将示例式描述改为“后台填写任意正整数”。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore test/test_account_image_capabilities.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 修复 1K 生图工具参数会话白等超时
### What was done
- 排查本地 5 张并发生图只有 1 张成功的问题，确认 5 个任务已分配到 5 个不同 web 账号，但失败任务里多数上游只返回了生图工具参数 JSON，没有产出图片文件。
- 修复 `stream_image_outputs`：当上游返回 `{"prompt": "...", "size": "...", "n": 1}` 这类工具参数文本且没有图片文件 id 时，立即交给账号池重试，不再进入图片轮询等满超时。
- 本地 Docker 镜像已重新构建并重建容器，当前通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services/protocol/conversation.py`
- `docker exec chatgpt2api-auth-local sh -lc 'cd /app && uv run python -m unittest test.test_codex_image_route'` 通过，`Ran 7 tests`。
- `docker exec chatgpt2api-auth-local sh -lc 'cd /app && uv run python -m unittest test.test_image_task_service'` 通过，`Ran 5 tests`。
- `docker build -t chatgpt2api-auth-local:dev .`
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev`
- `Invoke-WebRequest -UseBasicParsing -Uri http://localhost:8080/` 返回 `200`。
### Notes
- `services/protocol/conversation.py`：工具参数文本无图片结果时立即返回 message，让账号池快速换账号重试。
- `test/test_codex_image_route.py`：增加工具参数文本不进入图片轮询的测试。
- `docs/ops-health-and-queues.md`：补充工具参数文本会立即跳过轮询的说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/protocol/conversation.py test/test_codex_image_route.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 对齐参考项目的生图结果识别逻辑
### What was done
- 对比 `G:\desktop\image\chatgpt2api` 的稳定生图链路，确认它能更宽松地识别 SSE 和 conversation 明细里的图片指针，而当前项目容易漏掉落在 patch 或 assistant 消息里的图片结果。
- 当前项目迁移图片结果识别逻辑：SSE patch、tool 消息、assistant 消息中出现 `image_asset_pointer`、`file-service://...` 或 `sediment://...` 时都会记录为图片结果。
- conversation 明细解析同步支持 assistant/tool 两类图片记录，避免“上游已生成但本项目拿不到图”后继续空等或误判失败。
- 本地 Docker 镜像已重新构建并重建容器，当前通过 `http://localhost:8080` 访问。
### Testing
- `python -m py_compile services\protocol\conversation.py services\openai_backend_api.py` 通过。
- `docker exec chatgpt2api-auth-local sh -lc "cd /app && uv run python -m py_compile services/protocol/conversation.py services/openai_backend_api.py"` 通过。
- `docker exec chatgpt2api-auth-local sh -lc "cd /app && uv run python -m unittest test.test_codex_image_route"` 通过，`Ran 12 tests`。
- `docker exec chatgpt2api-auth-local sh -lc "cd /app && uv run python -m unittest test.test_account_image_capabilities"` 通过，`Ran 21 tests`。
- `docker build -t chatgpt2api-auth-local:dev .` 通过。
- `docker run -d --name chatgpt2api-auth-local -p 8080:80 -e STORAGE_BACKEND=json -v "${PWD}\data:/app/data" -v "${PWD}\config.json:/app/config.json" chatgpt2api-auth-local:dev` 已启动新容器。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/` 返回 `200`。
### Notes
- `services/protocol/conversation.py`：图片 SSE 状态更新改为识别 patch/assistant/tool 中的图片指针，并避免把用户上传参考图误记为生成结果。
- `services/openai_backend_api.py`：conversation 明细图片记录提取改为遍历 content/metadata，支持 assistant 消息中的图片指针。
- `test/test_codex_image_route.py`：增加 patch 图片指针和 assistant 图片记录提取的回归测试。
- `docs/ops-health-and-queues.md`：补充图片指针识别范围说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/protocol/conversation.py services/openai_backend_api.py test/test_codex_image_route.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 对齐参考项目的生图任务实时状态展示
### What was done
- 将图片任务接口补充为可返回单张任务的 `progress`、`elapsed_secs` 和 `duration_ms`。
- 画图页按单张图片展示排队、生成阶段、实时秒数和最终耗时；一组多图里已完成图片会先显示，未完成图片继续显示当前阶段。
- 网页生图链路新增轻量进度回调，覆盖确认账号、上传参考图、预热首页、获取 token、准备会话、启动生成、等待图片结果和接收图片等阶段。
- 已重新构建本地 Docker 镜像 `chatgpt2api-auth-local:dev`，并用新镜像重启 `chatgpt2api-auth-local` 到 `http://localhost:8080`。

### Testing
- `python -m py_compile services/image_task_service.py services/protocol/conversation.py services/protocol/openai_v1_image_generations.py services/protocol/openai_v1_image_edit.py services/openai_backend_api.py` 通过。
- `docker run --rm -v "${PWD}:/app" -w /app chatgpt2api-auth-local:dev uv run python -m unittest test.test_image_task_service test.test_codex_image_route` 通过，`Ran 18 tests`。
- `npm run build` 通过。
- `npx tsc --noEmit` 通过。
- `docker build -t chatgpt2api-auth-local:dev .` 通过。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/` 返回 `HTTP=200`。
- 生产镜像内未复制 `test/` 目录，因此 `docker exec -w /app chatgpt2api-auth-local uv run python -m unittest test.test_image_task_service` 无法在生产容器内执行；已用同一镜像依赖环境挂载源码完成测试。

### Notes
- `services/image_task_service.py`：图片任务记录进度、运行秒数和最终耗时，并将进度回调传给实际生图处理器。
- `services/protocol/conversation.py`：账号池和结果解析阶段触发生图进度回调。
- `services/protocol/openai_v1_image_generations.py`：文生图任务向 `ConversationRequest` 传入进度回调。
- `services/protocol/openai_v1_image_edit.py`：图生图任务向 `ConversationRequest` 传入进度回调。
- `services/openai_backend_api.py`：网页生图客户端在上传、预热、获取 token、准备会话和启动生成时上报进度。
- `web/src/lib/api.ts`：图片任务类型增加进度、运行秒数和耗时字段。
- `web/src/store/image-conversations.ts`：本地图片会话记录保留单张任务状态、进度、计时和耗时。
- `web/src/app/image/page.tsx`：将后端任务状态映射为单张图片卡片状态，成功/失败时保存耗时。
- `web/src/app/image/components/image-results.tsx`：生成中卡片显示图片序号、阶段和实时秒数，成功结果显示耗时。
- `test/test_image_task_service.py`：增加图片任务进度、运行秒数和耗时测试。
- `docs/ops-health-and-queues.md`：补充图片任务实时状态字段和前端展示行为说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/image_task_service.py services/protocol/conversation.py services/protocol/openai_v1_image_generations.py services/protocol/openai_v1_image_edit.py services/openai_backend_api.py web/src/lib/api.ts web/src/store/image-conversations.ts web/src/app/image/page.tsx web/src/app/image/components/image-results.tsx test/test_image_task_service.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 直接搬入参考项目生图链路
### What was done
- 按用户要求，以 `G:\desktop\image\chatgpt2api` 为准，直接搬入参考项目的生图页、图片任务接口、网页上游生图协议、图片结果保存和相关依赖。
- 为避免整站启动失败，仅补充当前项目必要兼容点：保留当前项目的鉴权、配额、账号权限、注册和高清中转配置，同时补回旧聊天接口仍需要的 `normalize_image_resolution`、`stream_chat_events` 和 `delete_conversation_safely`。
- 已重新构建本地 Docker 镜像 `chatgpt2api-auth-local:dev`，并用新镜像重启 `chatgpt2api-auth-local` 到 `http://localhost:8080`。
### Testing
- `python -m py_compile services/content_filter.py services/editable_file_task_service.py services/protocol/openai_search.py services/protocol/conversation.py services/config.py services/image_storage_service.py api/ai.py api/image_tasks.py api/image_inputs.py` 通过。
- `npx tsc --noEmit` 通过。
- `docker run --rm -v "G:\gpt\RemotePinee-ChatGPT2API:/app" -w /app chatgpt2api-auth-local:dev uv run python -c "from api import create_app; app=create_app(); print(type(app).__name__)"` 返回 `FastAPI`。
- `docker build -t chatgpt2api-auth-local:dev .` 通过。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/image` 返回 `200`。
- 使用本地 `config.json` 中的实际 auth-key 请求 `http://localhost:8080/api/image-tasks` 返回 `200`。
- 旧的 `test.test_image_task_service test.test_codex_image_route` 仍按前一版自定义字段断言，会因为 `running_timeout_getter`、`resolution`、`retry_after_progress` 等旧字段与参考项目原版链路不一致而失败；这批测试需要后续按参考项目行为重写。
### Notes
- `api/ai.py`：改为参考项目的 OpenAI 兼容接口入口。
- `api/image_tasks.py`：改为参考项目的图片任务接口。
- `api/image_inputs.py`：新增参考项目的图生图输入解析。
- `services/image_task_service.py`：改为参考项目的图片任务执行与公开状态逻辑。
- `services/openai_backend_api.py`：改为参考项目的网页上游调用逻辑。
- `services/image_storage_service.py`：新增参考项目的图片保存与 `/images/...` URL 生成服务。
- `services/content_filter.py`：改为参考项目的请求文本形态统计、base64 清洗和审核策略。
- `services/editable_file_task_service.py`：新增参考项目接口依赖的可编辑文件任务服务。
- `services/config.py`：补充参考项目图片存储配置入口，同时保留当前项目已有配置。
- `services/protocol/conversation.py`：改为参考项目的会话/生图协议，并补回当前聊天接口所需兼容函数。
- `services/protocol/openai_v1_image_generations.py`：改为参考项目的文生图协议适配。
- `services/protocol/openai_v1_image_edit.py`：改为参考项目的图生图协议适配。
- `services/protocol/openai_search.py`：新增参考项目搜索协议依赖。
- `utils/image_tokens.py`：新增参考项目图片 token 估算工具。
- `web/src/lib/api.ts`：对齐参考项目图片任务字段与接口调用。
- `web/src/store/image-conversations.ts`：对齐参考项目图片会话本地状态。
- `web/src/app/image/page.tsx`：对齐参考项目画图页主逻辑。
- `web/src/app/image/components/image-composer.tsx`：对齐参考项目画图输入组件。
- `web/src/app/image/components/image-results.tsx`：对齐参考项目图片结果展示组件。
- `docs/ops-health-and-queues.md`：补充当前生图链路已对齐参考项目的运维说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore api/ai.py api/image_tasks.py services/config.py services/content_filter.py services/image_task_service.py services/openai_backend_api.py services/protocol/conversation.py services/protocol/openai_v1_image_edit.py services/protocol/openai_v1_image_generations.py web/src/app/image/components/image-composer.tsx web/src/app/image/components/image-results.tsx web/src/app/image/page.tsx web/src/lib/api.ts web/src/store/image-conversations.ts docs/ops-health-and-queues.md progress.md` 并删除新增文件 `api/image_inputs.py services/editable_file_task_service.py services/image_storage_service.py services/protocol/openai_search.py utils/image_tokens.py`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 修复账号刷新代理参数兼容错误
### What was done
- 修复号池管理刷新账号时报 `BaseSession.__init__() got an unexpected keyword argument 'account'` 的问题。
- 将 `services/proxy_service.py` 对齐参考项目实现，让 `build_session_kwargs(account=...)` 先消费账号代理配置，再只把底层 Session 支持的参数传下去。
- 已重新构建本地 Docker 镜像 `chatgpt2api-auth-local:dev`，并用新镜像重启 `chatgpt2api-auth-local` 到 `http://localhost:8080`。
### Testing
- `python -m py_compile services/proxy_service.py services/openai_backend_api.py services/account_service.py` 通过。
- `docker run --rm -v "G:\gpt\RemotePinee-ChatGPT2API:/app" -w /app chatgpt2api-auth-local:dev uv run python -c "from services.openai_backend_api import OpenAIBackendAPI; api=OpenAIBackendAPI(''); print(type(api.session).__name__)"` 返回 `Session`。
- `npx tsc --noEmit` 通过。
- `docker build -t chatgpt2api-auth-local:dev .` 通过。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/accounts` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing -Headers @{Authorization="Bearer <本地 auth-key>"} http://localhost:8080/api/accounts` 返回 `200`。
- 使用一个本地账号调用 `POST /api/accounts/refresh`，不再出现 `BaseSession.__init__() got an unexpected keyword argument 'account'`；该账号自身返回 `token invalidated`，属于账号状态问题。
### Notes
- `services/proxy_service.py`：对齐参考项目的代理参数处理，支持 `account` 和显式 `proxy`，避免传入底层 `curl_cffi` Session。
- `docs/ops-health-and-queues.md`：补充参考项目链路包含代理参数处理对齐。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/proxy_service.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 保留当前页面并修复参考生图链路兼容
### What was done
- 按用户明确要求，停止整页搬参考项目 UI；画图页和前端会话状态保留当前项目实现。
- 将后端生图执行链路对齐参考项目，同时补回当前项目必须保留的 `resolution`、取消任务、额度扣退、账号权限、IP 限制、任务摘要和高清并发限制。
- 补齐参考链路依赖的图片轮询配置默认值，避免任务启动后因 `image_poll_interval_secs` 等配置字段缺失而全部失败。
- 修复工具参数 JSON/纯文字无图的处理：这类上游响应不再直接作为失败结果落库，而是标记为可重试并换下一个账号。
- 2K/4K 保留当前项目的 Codex 高清路径，高清失败不会静默降级为普通 `picture_v2`。
- 已重新构建本地 Docker 镜像 `chatgpt2api-auth-local:dev`，并用新镜像重启 `chatgpt2api-auth-local` 到 `http://localhost:8080`。
### Testing
- `python -m py_compile api\ai.py api\image_tasks.py api\image_inputs.py services\config.py services\image_task_service.py services\protocol\conversation.py services\protocol\openai_v1_image_generations.py services\protocol\openai_v1_image_edit.py services\openai_backend_api.py services\proxy_service.py` 通过。
- `docker run --rm -v "G:\gpt\RemotePinee-ChatGPT2API:/src" -w /src -e UV_PROJECT_ENVIRONMENT=/app/.venv chatgpt2api-auth-local:dev uv run --with pytest pytest test/test_image_task_service.py test/test_account_image_capabilities.py test/test_codex_image_route.py` 通过，`39 passed, 1 warning`。
- `npx tsc --noEmit` 通过。
- `docker build -t chatgpt2api-auth-local:dev .` 通过。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/image` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing -Headers @{Authorization="Bearer <本地 auth-key>"} http://localhost:8080/api/image-tasks` 返回 `200`。
- `docker exec chatgpt2api-auth-local uv run python -c "from services.image_task_service import image_task_service; print(image_task_service.summary())"` 通过，任务摘要可读。
### Notes
- `api/ai.py`：恢复当前项目的图片额度、权限和频率限制，并保留参考链路输入解析。
- `api/image_tasks.py`：补回当前页面依赖的 `resolution`、取消任务、额度扣退和账号策略，同时调用参考生图处理器。
- `api/image_inputs.py`：让图生图输入解析支持 `resolution`。
- `services/config.py`：补齐参考生图链路需要的轮询间隔、初始等待、并行开关和二次确认配置。
- `services/image_task_service.py`：补回取消、分辨率、额度退款、任务摘要、高清并发和取消后不覆盖状态的逻辑。
- `services/protocol/conversation.py`：补回账号池策略传递、工具参数 JSON 可重试、高清 Codex 路径和分辨率提示。
- `services/protocol/openai_v1_image_generations.py`：向底层会话请求传递 `resolution` 和账号池约束。
- `services/protocol/openai_v1_image_edit.py`：向底层会话请求传递 `resolution` 和账号池约束。
- `docs/ops-health-and-queues.md`：修正说明为“保留当前页面，只对齐后端生图链路”。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore api/ai.py api/image_tasks.py services/config.py services/image_task_service.py services/protocol/conversation.py services/protocol/openai_v1_image_edit.py services/protocol/openai_v1_image_generations.py docs/ops-health-and-queues.md progress.md && git clean -f -- api/image_inputs.py`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 修复生图工具参数 JSON 误触发换号重试
### What was done
- 按参考项目生图链路修正当前项目的 1K 账号池非流式生图行为。
- 工具参数 JSON 或上游文本提示不再被当成“换号重开”的信号，而是继续轮询当前 conversation 的图片结果。
- 已经收到上游进度、消息或图片指针后，不再中途切换账号重新发起同一张图，避免并发 5 张时部分任务被丢弃后长时间卡住。
- 非流式生图不再把图片轮询时间砍半，改为使用完整 `image_poll_timeout_secs`。
### Testing
- `docker run --rm -v "G:\gpt\RemotePinee-ChatGPT2API:/src" -w /src -e UV_PROJECT_ENVIRONMENT=/app/.venv chatgpt2api-auth-local:dev uv run --with pytest pytest -vv -x test/test_codex_image_route.py` 通过，`12 passed, 1 warning`。
- `docker run --rm -v "G:\gpt\RemotePinee-ChatGPT2API:/src" -w /src -e UV_PROJECT_ENVIRONMENT=/app/.venv chatgpt2api-auth-local:dev uv run --with pytest pytest -q test/test_image_task_service.py test/test_account_image_capabilities.py test/test_codex_image_route.py` 通过，`39 passed, 1 warning, 8 subtests passed`。
### Notes
- `services/protocol/conversation.py`：修正生图结果判定、轮询超时传递和账号切换条件。
- `test/test_codex_image_route.py`：更新工具参数 JSON、无结果和非流式轮询相关测试，覆盖“不换号重开”的行为。
- `docs/ops-health-and-queues.md`：更新生图排障说明，删除旧的“工具参数 JSON 立即换号”和“半超时轮询”描述。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore services/protocol/conversation.py test/test_codex_image_route.py docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 优化画图页本地流畅度
### What was done
- 优化画图页任务轮询更新：任务状态没有实际变化时，不再刷新会话对象和更新时间，减少整页重渲染与本地缓存写入。
- 成功图片优先使用后端返回的图片 URL 展示，并在本地会话归一化时丢弃同图的 base64 副本，降低历史图片越多时的状态体积。
- 缓存结果区灯箱图片列表和索引，避免每个图片格子重复扫描全部历史结果。
### Testing
- `npm run build` 通过；Next.js 仍提示已有的 `output: export` rewrite 警告和 workspace root 推断警告，未出现编译失败。
### Notes
- `web/src/app/image/page.tsx`：减少轮询无变化时的会话更新和 base64 状态保留。
- `web/src/app/image/components/image-results.tsx`：图片展示优先走 URL，并缓存灯箱列表和索引。
- `web/src/store/image-conversations.ts`：本地会话归一化时清理已有 URL 图片的 base64 副本。
- `docs/ops-health-and-queues.md`：补充画图页前端性能说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore web/src/app/image/page.tsx web/src/app/image/components/image-results.tsx web/src/store/image-conversations.ts docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 验证画图页流畅度优化本地镜像
### What was done
- 基于优化后的前端重新构建本地镜像 `chatgpt2api-auth-local:dev`。
- 用新镜像重启本地 `chatgpt2api-auth-local` 容器到 `http://localhost:8080`。
### Testing
- `npx tsc --noEmit` 通过。
- `docker build -t chatgpt2api-auth-local:dev .` 通过；仅出现 Dockerfile 既有的 `RedundantTargetPlatform` 警告。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/image` 返回 `200`。
- `docker logs --tail=80 chatgpt2api-auth-local` 未见启动错误。
### Notes
- `progress.md`：追加本地镜像构建和容器验证记录。
- 回滚方式：如需回到旧镜像，先回退上一条“优化画图页本地流畅度”记录列出的源码文件，然后重新执行旧源码的 `docker build -t chatgpt2api-auth-local:dev .` 并重启 `chatgpt2api-auth-local`；如果已有镜像备份标签，也可直接用备份标签重启容器。

## 2026-06-19 - Task: 继续优化画图页渲染流畅度
### What was done
- 将图片结果区改为稳定 memo 组件，当前对话数据不变时，输入框打字和设置变化不会触发整块历史结果区重渲染。
- 稳定删除确认相关回调引用，避免无意义地打破结果区 memo。
- 优化结果滚动容器的底部渐隐状态更新，只在显隐值变化时触发 React 状态更新。
### Testing
- `npx tsc --noEmit` 通过。
- `npm run build` 通过；Next.js 仍提示已有的 `output: export` rewrite 警告和 workspace root 推断警告，未出现编译失败。
### Notes
- `web/src/app/image/page.tsx`：稳定删除回调，并对滚动渐隐状态做变化检测。
- `web/src/app/image/components/image-results.tsx`：将结果区组件 memo 化，减少输入区操作时的历史结果重渲染。
- `docs/ops-health-and-queues.md`：补充第二轮画图页性能优化说明。
- `progress.md`：追加本轮修改记录。
- 回滚方式：使用 Git 回退本轮涉及文件，或执行 `git restore web/src/app/image/page.tsx web/src/app/image/components/image-results.tsx docs/ops-health-and-queues.md progress.md`；如果已提交则用对应提交点执行 `git revert <commit>`。

## 2026-06-19 - Task: 验证第二轮画图页渲染优化本地镜像
### What was done
- 基于第二轮渲染优化重新构建本地镜像 `chatgpt2api-auth-local:dev`。
- 用新镜像重启本地 `chatgpt2api-auth-local` 容器到 `http://localhost:8080`。
### Testing
- `docker build -t chatgpt2api-auth-local:dev .` 通过；仅出现 Dockerfile 既有的 `RedundantTargetPlatform` 警告。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/` 返回 `200`。
- `Invoke-WebRequest -UseBasicParsing http://localhost:8080/image` 返回 `200`。
- `docker logs --tail=80 chatgpt2api-auth-local` 未见启动错误。
### Notes
- `progress.md`：追加本地镜像构建和容器验证记录。
- 回滚方式：如需回到上一版镜像，先回退上一条“继续优化画图页渲染流畅度”记录列出的源码文件，然后重新执行 `docker build -t chatgpt2api-auth-local:dev .` 并重启 `chatgpt2api-auth-local`；如果已有镜像备份标签，也可直接用备份标签重启容器。
