---
name: zhibi
description: Guide users through Claude account setup, Google Play subscription, dedicated browser or Linux workspace setup, and network troubleshooting. Compare observed IPv4 and IPv6 exits across the browser, proxy, and Linux runtime.
---

# 知彼

从用户已经做到的地方接着走。优先在用户实际能看到的页面上用 computer use 完成可代办步骤，边操作边解释。只需说明或没有可操作的设备画面时，根据用户当前页面给出下一步。脚本处理测量、部署和交付。

脚本入口为本 Skill 下的 `scripts/zhibi.py`。由 Agent 运行命令；安装依赖和界面操作根据宿主、系统及用户现状安排。已有授权继续有效，缺什么问什么。

## 1. 确定从哪一步开始

如果用户没交代现状，按 [intake](references/intake.md) 问三件事。从已有回答里补齐即可：

1. 你现在想做什么，想从哪一步开始？
2. 相关账号和订阅准备到哪一步？
3. 如果你想配置专用网络，你有 VPS 吗？

账号、运行环境和网络出口分别处理。需要注册或通过 Google Play 开通订阅时，读 [账号与 Google Play](references/google-play.md)。已有账号或已付费时从用户当前状态接着走。要配置 VPS 时请用户提供连接信息；只检查或只开通订阅时无需 VPS。

先区分这次要检查、配置还是复查。多步任务用 `environment init --folder DIR --route undecided` 创建本机过程记录；把目录路径交给用户。已有目录时先 `environment status --folder DIR`，读最近产物和下一步，再与现场状态核对。配置交付后优先从交付目录和 `reproduce.sh` 继续。

## 2. 检查实际环境

先确定用户实际使用的浏览器、机器和已有线路。`doctor` 仅检查本机。配置时按路线用 `doctor --route web`、`doctor --route remote` 或 `doctor --route pvm` 发现缺少的本机工具。`session --preset network --network` 在实际浏览器采集 IPv4、IPv6、WebRTC，已有自建 DNS 观测端时加 `--dns-observer URL`。只测两种 IP 用 `basic`。必要时使用 `--file`。不要用 Agent 的浏览器或终端出口替代用户环境。

有用户指定的 VPS 时先按 [首次连接](references/remote.md#首次连接) 核验连接与免交互认证，再用 `check --host HOST --egress` 读取远端现状。`scan`、`suite` 保留深入检查，按问题选模块。外部查询只在允许范围内执行；原始配置和凭据留在本机。

以具体观测解释结果。数据中心标签、公共 DNS、中文语言或不同系统本身不构成失败；现有评分仅供背景，不能据此要求更换线路。说明已测、未测以及实际需要处理的问题。

用户仅要求检查时直接交付结果。完整配置时分开确认运行环境与网络出口。优先远程 Linux；没有服务器时按 [local-vm](references/local-vm.md) 通过 PVM 创建本机 Linux VM，已有 SSH 虚拟机也可接入。只有本机网络时，经用户明确选择使用 `--exit direct`；有专用出口需求时单独配置和核验。

修改前检查现有软件、服务和端口。用户已授权的步骤直接继续；新增范围才补问。用户要求暂缓运行真实应用或访问目标站时，用合成命令和测试站验收基础设施。

## 3. VPS 服务与进程

本节用于远程路线。本地路线按 local-vm 参考创建共享项目与桌面，并使用相同的 project 启动/恢复入口；不要把整个远程部署流程重复套在本地 VM 上。

仅浏览器的用户无需应用工作区，按 [runtime](references/runtime.md) 交付连接服务，再进行浏览器配置。

阅读 [runtime](references/runtime.md) 和 [remote](references/remote.md)。根据命令的真实运行方式选择交互终端、一次性执行或后台服务。准备依赖时根据实际 Linux 发行版、安装渠道和权限安排，安装后验证可执行文件和版本。不要改变用户命令的用途。

`connect` 可以同时提供本机 SOCKS5 与远端进程；`build` 用于非交互后台服务，默认只出计划。后台常驻不等于应用可用，必须检查日志和用户所需的应用操作。先保存原值和已有服务配置，再执行授权的变更。

需要专用进程环境时，按 runtime 参考使用 `process-workspace` 与 `process-entry`。需要受控代理联网时选择 proxy 模式，核验固定版本 graftcp 和解析器可达性；用 `runtime-service` 交付用户级网关服务。用户希望直接运行应用名时，用 `process-activate` 配置并核对新登录终端。安排从项目目录启动；验收前先确认实际解析到专用入口。

需要按项目保存连接、再次启动或恢复应用会话时，阅读 [projects](references/projects.md)。SSH 项目用 `project bind --runtime-workspace REMOTE_PROFILE` 让启动、恢复和探针共用同一工作区；`--no-browser-proxy` 让命令启动独立于浏览器服务。`project editor` 导出远程编辑器连接，`project upload/download` 处理选定的单个文件或图片。应用会话恢复与后台常驻分别验证。

## 4. 浏览器

阅读 [browser](references/browser.md)。由 Agent 根据现有能力选择 API、computer use 或两者结合，在用户选择的指纹浏览器中配置并保存专用环境。已有可用且足以完成任务的 API 时优先使用；没有 API 或功能不足时通过 computer use 操作实际界面。不固定品牌或点击步骤，不将 API Key 作为前提。目标是用户以后直接打开该浏览器环境即可使用所需服务，无需再次运行知彼或手动启动隧道。本地 VM 路线也可在 VM 桌面内配置。保存后在实际浏览器验证出口和目标服务访问；API 和 computer use 都无法完成的必要步骤才交给用户。

## 5. 总体验收与交付

按 [audit](references/audit.md) 执行适用的运行上下文测量、实际浏览器对比、协议检查和受控断网恢复。仅浏览器时核验浏览器与预期出口；同时运行应用时分别测量两端实际线路。PVM 的 warn/skipped 与缺测项保留原状态。

部署或更换线路后，在实际浏览器重新采集。仅浏览器时，用 `accept --proxy-port PORT --egress --browser FILE` 比对后台连接和浏览器。浏览器加 CLI 时，用 `accept --project PROJECT --egress --browser FILE` 比对项目工作区和浏览器。先给用户看两侧测到的 IP、地址族和结论，再说明 WebRTC、DNS 等各自有何证据。SSH 宿主或自定义探针读数保留为应用待验。

按 [deliver](references/deliver.md) 把同一组选项交给 `deliver`，有断线演练报告时用 `--outage-report` 带进交付。记录已配置的浏览器环境名或 Chromium 启动目录、服务目录和应用入口。确认用户能从交付文件直接找到浏览器和 CLI 的启动方式。按用户授权检查进程的实际操作和浏览器访问；账号登录由用户完成。验证停止连接及恢复原配置。使用合成命令或测试页时记录验收范围，真实应用和目标站保留为未测。

`build --apply` 保存私人原值与部署回执；交付时传 `--build-receipt`，生成作用于该 VPS 的服务与时区恢复命令。安装依赖、语言生成和浏览器修改分别记录恢复方式。已有过程目录时，给 `session`、`check`、`build`、`browse`、`accept` 和 `deliver` 加 `--environment DIR`；独立的 VM 或后台连接配置用 `environment checkpoint --folder DIR --route ROUTE --artifact LOCAL_PATH` 记录实际产物。复查时确认用户选择固定还是动态出口，查看同次一致性及交付时的历史出口对照。

## 必要边界

服务端进程与本地浏览器可以共用出口，但这不意味着它们是同一设备，也不保证账号结果。只管理用户授权的环境；不收集 Cookie 或账号凭据。遵循用户选用软件的实际使用要求，不用泛化的产品禁令或幽默免责声明替代事实。
