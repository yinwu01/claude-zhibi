# 知彼（Zhibi）

> **知己知彼，稳用 Claude。**
>
> 知彼是一个帮开发者检查、搭建和维护 Claude 使用环境的 Agent Skill。网页用独立浏览器环境，写代码用隔离的 Linux 环境。两端可以经过同一台自有 VPS 出网，配置是否生效以实际测量为准。

[需要准备什么](#需要准备什么) · [你会得到什么](#你会得到什么) · [快速开始](#快速开始) · [日常怎么用](#日常怎么用) · [当前验证范围](#当前验证范围) · [致谢](#致谢与参考项目) · [English](README.en.md)

## 为什么叫「知彼」

**知彼**是弄清服务可能看到什么。网站看到的出口 IP 取决于实际请求走的线路。DNS、WebRTC 和客户端权限又各有自己的设置，单看代理开关或一个 IP 标签看不全。

**知己**是把能控制的东西管起来。给网页单独建一个浏览器环境，限制不需要的权限、扩展和同步；在 Linux 里给 CLI 单独的项目目录和 HOME；两边分别测出口，线路出问题时先复查。知彼把这些检查和配置交给 Agent，你平时仍然在浏览器和编辑器里工作。

> 作者曾在大厂国际风控团队实习，这套设计来自作者长期使用 Claude 的实践，包括两个 Claude Max 订阅的个人使用经历。

## 需要准备什么

| 准备项 | 用途 |
| --- | --- |
| **一台自有 VPS** | 完整方案的网络出口。家宽或机房线路都可以先实测，重点是来源清楚、有管理权限且能保持稳定。公共机场节点无法替代这台服务器。 |
| **一个独立的浏览器环境** | 用于 Claude 网页版。可以使用自己选的指纹浏览器，或让知彼创建专用 Chromium 环境。Agent 根据现场选用可用 API 或操作界面。 |
| **Linux 工作环境** | 仅 Claude Code 路线需要。优先复用自己的 Linux VPS。一台机器可以既跑 CLI，又提供出口。也可以创建本机 PVM 虚拟机，或通过 SSH 接入已有 Linux 虚拟机。 |
| **Agent 和本机工具** | Python 3.9+、SSH 客户端和能执行命令的 Agent。浏览器配置需要可用 API、computer use 或少量手动操作。 |

只检查网络时，从现有环境开始即可。注册、订阅、付款和身份验证由用户在官方流程里完成。付费时按服务要求准备自己的支付方式。使用 Claude 前先确认实际所在地和账号符合其[支持地区政策](https://www.anthropic.com/legal/supported-regions)。

## 你会得到什么

- 一个单独的浏览器环境，配置好后直接打开使用。
- 如果选择 CLI 路线，一套 Linux 应用环境和具体的项目启动入口。
- 一份验收记录，写清实际出口、测过的断线行为、还有哪些未测，以及如何复查和恢复配置。

## 快速开始

在运行 Agent 的电脑上安装知彼：

```bash
git clone https://github.com/yinwu01/cc-zhibi.git
cd cc-zhibi
python3 scripts/install_skill.py --host codex
```

新开 Agent 会话，选择下面与你需求对应的一段。如果只想先检查，把「请配置」改成「只检查并给我报告」。

### 路径 A：只用 Claude 网页版

> $zhibi 先检查我的实际浏览器和自有 VPS。请为网页版配置一个独立浏览器环境，把它接到 VPS 出口。先用测试页面验证浏览器重开、断线和恢复，再告诉我日常该打开哪个环境。账号操作我自己做。

VPS 负责网页流量出网，可直接使用其现有线路，或选用你已有的 SOCKS5 上游。后台连接支持 macOS 和有 systemd 用户服务的 Linux。交付时记录浏览器环境名、实测出口和恢复方法。[连接与维护说明](skills/zhibi/references/runtime.md)

### 路径 B：网页版加 Claude Code

> $zhibi 先检查我的 VPS 和浏览器。请复用 VPS 搭建隔离的 CLI 工作区，让浏览器和 CLI 共用私人网关。先用不含账号或项目数据的替身命令验证，再告诉我从哪个目录启动和如何检查入口。真正的应用测试按我授权的范围进行。

本机编辑器通过 SSH 连入工作机。知彼可导出独立的 SSH 配置和打开远端项目的终端脚本。Agent 先验证新登录终端指向隔离入口，再从该项目目录检查工作目录、网络路径和故障行为。已有账号的用户可直接使用自己的账号。[编辑器接入](skills/zhibi/references/projects.md#编辑器接入)

如果项目文件需要留在本机，可以选择 PVM。当前适配 macOS arm64 和 Linux amd64，使用单独安装的 PVM v1.1.6。已有 VMware、Parallels 或 UTM Linux 虚拟机可通过 SSH 接入，建机和开关机由各自的管理器处理。本机 VM 可以保留本地项目副本，Claude Code 仍可能把任务所需的代码上下文发送给模型服务。[本地 VM 说明](skills/zhibi/references/local-vm.md) · [Claude Code 数据使用说明](https://code.claude.com/docs/en/data-usage)

## 日常怎么用

- **网页**：打开 Agent 交付的浏览器环境。
- **CLI**：在指定的 Linux 项目目录使用 Agent 交付的入口。远程 Linux 的持久命令入口验收通过后，可在 Bash 或 Zsh 中直接输入 `claude`。PVM 路线可使用已绑定的项目启动入口。
- **线路变动**：后台连接会尝试重连。更换出口、恢复失败或看到异常时，先要求 Agent 复测；能重连只说明连接恢复，实际出口以复测结果为准。

本机 Claude Desktop、手机 App 和日常普通浏览器不在这套交付范围内。知彼保存环境和验收记录，账号资格、验证要求和账号状态由服务方决定。

## 当前验证范围

- 远程 SSH、应用隔离、私人网关、项目文件传输，以及 PVM 创建和共享目录已有隔离环境记录。
- 新版浏览器后台连接已通过 macOS 本机回环实测，包括 SSH 自动重连、Chromium 在网关断开时访问失败、恢复后重开正常。Linux 命令入口用替身验证了 Bash 和 Zsh；新版入口和实际部署环境仍需实机复测。
- 只用浏览器时可走 VPS 现有出口。远程完整路线让两端使用同一私人网关，并分别测量出口 IP。DNS、WebRTC 和 IPv6 按各自证据记录。
- SOCKS5 上游、已有 VM 接入和编辑器配置已实现。真实线路、指纹浏览器和编辑器的使用流程需要各自验收。注册与支付专项手册仍单独安排。

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
