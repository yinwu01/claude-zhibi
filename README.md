# 知彼（Zhibi）

> **知己知彼，稳用 Claude。**
>
> 知彼是一个帮开发者从当前进度开始的 Agent Skill。它可以指导账号开通、检查实际网络，或配置独立浏览器和隔离的 Linux 工作区。网页版和 CLI 可以经过同一台自有 VPS 出网，配置是否生效以实际测量为准。

**先选你要怎么用**

- [只用 Claude 网页版](#路径-a只用-claude-网页版) · Agent 配好浏览器和后台连接，以后直接打开专用浏览器。
- [还要用 Claude Code](#路径-b网页版加-claude-code) · Agent 优先复用你的 Linux VPS，以后从本机打开绑定的项目。

[需要准备什么](#需要准备什么) · [安装 Skill](#快速开始) · [日常使用](#日常怎么用) · [当前验证范围](#当前验证范围) · [致谢](#致谢与参考项目) · [English](README.en.md)

## 需要准备什么

| 准备项 | 用途 |
| --- | --- |
| **一台自有 VPS（需要专用远端出口时）** | 家宽或机房线路都可以先实测，优先选择自己能管理的独享线路。准备服务器地址、SSH 用户名和端口，或已有的 SSH 别名，以及可从供应商控制台核对的主机指纹。 |
| **一个独立的浏览器环境** | 用于 Claude 网页版。可以使用自己选的指纹浏览器，或让知彼创建专用 Chromium 环境。Agent 根据现场选用可用 API 或操作界面。 |
| **Linux 工作环境** | 仅 Claude Code 路线需要。优先复用自己的 Linux VPS。一台机器可以既跑 CLI，又提供出口。也可以创建本机 PVM 虚拟机，或通过 SSH 接入已有 Linux 虚拟机。 |
| **Agent 和本机工具** | Python 3.9+、SSH 客户端和能执行命令的 Agent。浏览器配置需要可用 API、computer use 或少量手动操作。 |

只检查网络或只开通订阅时，可以从现有环境开始。Agent 可以带你操作官方页面，密码、验证码和付款确认由你自己处理。想用安卓手机开通订阅，可参考 [Google Play 开通教程](docs/tutorials/claude-google-play.md)。使用 Claude 前先核对其[支持地区政策](https://www.anthropic.com/legal/supported-regions)。

## 你会得到什么

- 一个单独的浏览器环境，配置好后直接打开使用。
- 如果选择 CLI 路线，一套 Linux 应用环境和具体的项目启动入口。
- 一份验收记录，并排展示浏览器与实际运行路径的 IPv4、IPv6 出口。WebRTC 和 DNS 各自显示检测结果；复查还能看到两端的地址是否一起换了。 [出口一致性检查](skills/zhibi/references/audit.md#出口一致性)

## 快速开始

在运行 Agent 的电脑上安装知彼：

> 你也可以把这个仓库交给 Agent，告诉它「请在我的电脑安装知彼。已有旧版就保留备份再升级，安装好后告诉我怎么开始。」

```bash
git clone https://github.com/yinwu01/cc-zhibi.git
cd cc-zhibi
python3 scripts/install_skill.py --host codex
```

已有旧版时，在最后一条命令加 `--replace`。安装器会保留旧版并显示回退命令。

新开 Agent 会话，输入：

> $zhibi 带我开始，从我当前做到的地方继续。

Agent 会先问你想做什么、账号或订阅准备到哪一步。要配置专用网络时，它再确认你有没有 VPS。你也可以直接说卡在哪个页面，或告诉它已准备好的信息，它会接着做。Agent 能操作你的电脑界面时，可以直接打开页面并带你走。看不到手机画面时，它会告诉你当前要点哪一步。

准备好 VPS 后，先让 Agent 带你在电脑上验证能用 SSH 密钥登录，再开始部署。只有初始密码时，也可以从首次连接开始。主机指纹用供应商控制台或其他可信来源核对。密码与私钥留在你自己的设备。 [首次连接说明](skills/zhibi/references/remote.md#首次连接)

如果你已经确定要配置哪条路线，也可以直接用下面的示例。

### 路径 A：只用 Claude 网页版

> $zhibi 先检查我的实际浏览器和自有 VPS。请为网页版配置一个独立浏览器环境，把它接到 VPS 出口。先用测试页面验证浏览器重开、断线和恢复，再告诉我日常该打开哪个环境。账号操作我自己做。

VPS 负责网页流量出网，可直接使用其现有线路，或选用你已有的 SOCKS5 上游。后台连接支持 macOS 和有 systemd 用户服务的 Linux。交付时记录浏览器环境名、实测出口和恢复方法。[连接与维护说明](skills/zhibi/references/runtime.md)

### 路径 B：网页版加 Claude Code

> $zhibi 先检查我的 VPS 和浏览器。请复用 VPS 搭建隔离的 CLI 工作区，让浏览器和 CLI 共用私人网关。先用不含账号或项目数据的替身命令验证，再告诉我从哪个目录启动和如何检查入口。真正的应用测试按我授权的范围进行。

本机编辑器通过 SSH 连入工作机。知彼可导出独立的 SSH 配置和打开远端项目的终端脚本。Agent 先验证新登录终端指向隔离入口，再从该项目目录检查工作目录、网络路径和故障行为。已有账号的用户可直接使用自己的账号。[编辑器接入](skills/zhibi/references/projects.md#编辑器接入)

**没有 Linux 服务器？** 知彼可以通过 PVM 在 Apple 芯片 Mac 或 Linux amd64 上创建本地 Ubuntu 虚拟机，用本机编辑器操作共享项目。没有 VPS 时可用本机网络出站；需要自有远端出口时再配置 VPS。也可通过 SSH 接入已有 Linux VM。本地项目副本保存在本机，Claude Code 仍可能把任务所需的代码上下文发送给模型服务。[本地 VM 说明与平台要求](skills/zhibi/references/local-vm.md) · [Claude Code 数据使用说明](https://code.claude.com/docs/en/data-usage)

## 日常怎么用

- **网页**：打开交付文件中写明的浏览器环境。专用 Chromium 从交付包的 `open-browser.sh` 启动。浏览器若装在 PVM 中，先从 `open-vm-desktop.sh` 打开虚拟机桌面。
- **CLI**：在本机终端执行交付包里的 `open-project.sh`。也可以通过 SSH 或编辑器进入远端的指定项目目录，再在验收过的 Bash 或 Zsh 入口输入 `claude`。
- **线路变动**：后台连接会尝试重连。让 Agent 用交付目录的 `reproduce.sh` 复查，与交付时的地址对照。固定出口变化会让验收失败，动态出口变化会提示。
- **换了 Agent 会话**：把本机的过程目录或交付目录交给 Agent，可用 `environment status` 看到做到哪一步、上次产物在哪。

本机 Claude Desktop、手机 App 和日常普通浏览器不在这套交付范围内。知彼保存环境和验收记录，账号资格、验证要求和账号状态由服务方决定。

## 为什么叫「知彼」

**知彼**是弄清实际使用的浏览器和应用各自走哪条线路。出口 IP、DNS 和 WebRTC 各有自己的设置，需要分别核对。

**知己**是把能控制的东西管起来。网页使用独立的浏览器环境，CLI 在 Linux 使用专用项目目录和 HOME。Agent 负责首次配置和检查，你平时仍然在浏览器和编辑器里工作。

> 作者曾在大厂国际风控团队实习，这套设计来自作者长期使用 Claude 的实践，包括两个 Claude Max 订阅的个人使用经历。

## 当前验证范围

- 远程 SSH、应用隔离、私人网关、项目文件传输，以及 PVM 创建和共享目录已有隔离环境记录。
- 新版浏览器后台连接已通过 macOS 本机回环实测，包括 SSH 自动重连、Chromium 在网关断开时访问失败、恢复后重开正常。Linux 命令入口用替身验证了 Bash 和 Zsh；新版入口和实际部署环境仍需实机复测。
- 只用浏览器时可走 VPS 现有出口。远程完整路线让两端使用同一私人网关，并分别测量出口 IP。DNS、WebRTC 和 IPv6 按各自证据记录。
- SOCKS5 上游、已有 VM 接入和编辑器配置已实现。真实线路、指纹浏览器和编辑器的使用流程需要各自验收。

更多细节见[双路线验收](docs/implementation/two-route-plan.md)、[持久入口进度](docs/implementation/native-delivery.md)和[数据流说明](docs/reference/privacy.md)。联网探针会访问报告中标明的测量服务；配置与私人报告留在本地。

## 致谢与参考项目

感谢以下项目的作者与贡献者：

- [xiaoxiaodong-vps](https://github.com/nevertoday/xiaoxiaodong-vps)：VPS 部署、Agent Skill 组织与运维流程参考。
- [CCBaga](https://github.com/liseami/CCBaga)：网络检查与环境配置流程，部分浏览器出口检测代码适配。
- [CheckCC](https://github.com/yacuo/check-cc)：部分浏览器环境采集、字体探测与研究模型适配。
- [IPQuality](https://github.com/xykt/IPQuality)：IP 质量检查的研究与对照。
- [Blackhole](https://github.com/tommy0103/blackhole)：项目绑定、持久化会话和启动体验参考。
- [PVM](https://github.com/huangzheng2016/pvm)：本地 Linux VM、共享目录、桌面与出口的可选外部后端。
- [bubblewrap](https://github.com/containers/bubblewrap)：Linux 进程隔离。
- [graftcp](https://github.com/hmgle/graftcp)：应用和子进程的代理网络接入。

[MIT](LICENSE) · [第三方声明](THIRD_PARTY_NOTICES.md) · [上游复用说明](docs/research/upstream-reuse.md) · [贡献](CONTRIBUTING.md)
