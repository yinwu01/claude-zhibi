# 知彼（claude-zhibi）

> **知己知彼，稳用 Claude。**

知彼带你从注册、订阅走到日常使用 Claude。告诉 Agent 你已经做到哪一步，它会从那里接手。

📖 **[我要注册或开通订阅](docs/tutorials/claude-google-play.md)**　跟着图文教程注册 Google 账号，在安卓手机上付款，再到 Claude 网页确认套餐到账。

🌐 **[我只用网页版](#路径-a只用-claude-网页版)**　用独立的浏览器配置聊 Claude。配好一次，以后直接打开。

💻 **[我还想用 Claude Code 写代码](#路径-b网页版与-claude-code)**　有 Linux 服务器就复用；没有就建本地 Linux 虚拟机。代码在工作区里运行，你照常用自己的编辑器。

**为什么日常只推荐浏览器和 Linux？** 从风控角度看，同一账号在电脑、手机之间切换时，设备特征、权限和网络出口也会随之变化。知彼把日常使用集中在两处：主流浏览器里的独立配置，以及隔离的 Linux 工作区。这样能少暴露个人设备上少见的特征组合，也方便 Agent 实测两端是否走同一出口。

[快速开始](#快速开始) · [看体检报告](#核心体验) · [日常使用](#日常使用) · [为什么只推荐浏览器和 Linux](#为什么叫知彼) · [English](README.en.md)

## 快速开始

**第一步 · 打开 Codex，把这句话发给它。**

```text
帮我在电脑上安装知彼（https://github.com/yinwu01/claude-zhibi），装好后告诉我怎么开始。
```

**第二步 · 安装完成后，新开一个 Codex 对话，输入下面这行。**

```text
$zhibi 带我开始，从我当前的进度继续。
```

Agent 会问你想怎么用、账号和订阅准备到哪一步，以及是否已有 VPS（云服务器）。你也可以直接说「我已经付费，只想配网页版」，或「我还没有服务器，先帮我检查这台电脑」。

如果 Agent 能操作桌面，它可以按你眼前的页面引导；最后的付款由你在官方页面确认。

<details>
<summary>在终端手动安装或升级</summary>

本机准备好 Git、Python 3.9+ 和 Codex，然后在终端运行：

```bash
git clone https://github.com/yinwu01/claude-zhibi.git
cd claude-zhibi
python3 scripts/install_skill.py --host codex
```

看到「已安装完整知彼 Skill」后，新开 Codex 对话输入上面的 `$zhibi`。升级已有安装时，在最新检出的仓库里运行最后一条命令，并在末尾加上 `--replace`。安装器会保留旧版并打印回退命令。

</details>

### 路径 A：只用 Claude 网页版

告诉 Agent：「帮我把网页版配好，接入我的 VPS，告诉我以后打开哪个浏览器。」

你可以让知彼创建专用 Chromium，也可以沿用已有的指纹浏览器。Agent 会在你选的浏览器里核对出口，并告诉你以后打开哪个配置。

在 macOS 或使用 systemd 的 Linux 上，知彼还可配置后台连接。隧道中断时，专用 Chromium 仍按指定代理连接，后台服务会尝试重连。[连接与维护](skills/zhibi/references/runtime.md)

### 路径 B：网页版与 Claude Code

告诉 Agent：「我还要写代码。帮我把网页版和 Claude Code 配到同一出口，并给我一个项目启动入口。」

**有 Linux VPS 或开发服务器**

优先复用现有机器。一台 Linux VPS 就能兼做工作区和网络出口。你在本机用 VS Code 或 Cursor 通过 SSH 编辑远端文件，从交付的项目入口启动 Claude Code。[首次连接服务器](skills/zhibi/references/remote.md#首次连接)

**没有 Linux 服务器，或希望项目文件留在本机**

知彼可以在 Apple 芯片 Mac 或 amd64 Linux 上用 PVM 创建 Ubuntu 虚拟机，也可以通过 SSH 接入已有的虚拟机。PVM 会共享你选定的项目目录：本机编辑，虚拟机运行，两边看到同一份代码。[本地虚拟机方案](skills/zhibi/references/local-vm.md)

> **虚拟机决定代码在哪里跑，出口决定流量从哪里出去。** 选本机网络时，虚拟机沿用电脑的出口。需要让网页和代码共用固定远端出口时，再接入自己的 VPS。

## 核心体验

**网页和 Claude Code 走的是同一条线路吗？** 只用网页版时，报告并排显示浏览器和代理的出口。也用 Claude Code 时，就对照浏览器和 Linux 工作区。

![知彼验收报告示例：应用与浏览器的 IPv4 一致，IPv6 不一致，报告给出复查建议。](docs/assets/exit-check-example.png)

*报告示例：IPv4 一行的两个地址相同，IPv6 一行却不同。只查 IPv4，就会漏掉这处差异。*

读自己的报告时，先看两端的地址，再看标成「需处理」和「待确认」的项目。每项都有下一步建议。

- **WebRTC** · 核对网页实时通信使用的公网地址，看看它和普通网页请求的出口是否一致。
- **DNS** · 配置观测端后，可以查看实际处理域名查询的解析器。
- **换线复查** · 使用固定出口时，可以把本次读数和交付记录对照。[出口一致性与断线演练](skills/zhibi/references/audit.md#出口一致性)

## 准备清单

| 我想做什么 | 提前准备 |
| --- | --- |
| 看注册教程、开通安卓订阅 | 能使用 Google Play 的安卓手机、自己的 Google 账号（可新建），以及 Play 接受的付款方式。可直接[按图操作](docs/tutorials/claude-google-play.md)。 |
| 让 Agent 检查本机环境 | 能执行本地命令的 Agent 和 Python 3.9+。只做本机检查时无需 VPS。 |
| 接入自己的 VPS | 家宽或机房线路都可以，选自己能管理的独享出口。多人共用的公共代理节点很难追踪出口变动。准备好 SSH 地址和用户名或已有别名，首次连接时核对主机指纹。自有网关也可接已有的 SOCKS5 上游。 |
| 使用本地虚拟机 | 准备要共享的项目目录，让 Agent 检查本机是否满足 PVM 要求；已有 Linux VM 时提供它的 SSH 连接方式。 |

## 日常使用

交付时请先打开交付目录中的 **先读我.md**。里面写的是你这次实际配好的浏览器、项目和启动方式。

- 🌐 **聊 Claude** · 打开交付时命名的浏览器配置。专用 Chromium 有 `open-browser.sh`；浏览器装在 PVM 桌面里则用 `open-vm-desktop.sh`。
- 💻 **写代码** · 在本机终端进入交付目录，运行 `bash open-project.sh` 启动绑定的项目。编辑器通过 SSH 打开文件；如果交付说明还确认了远程项目里的 `claude` 已指向隔离入口，也可以在那里直接输入 `claude`。[编辑器接入](skills/zhibi/references/projects.md#编辑器接入)
- 🔍 **换线后复查** · 把交付目录交给 Agent，说「帮我复查现在的出口」。涉及浏览器时，先从正在用的浏览器重新采集，再让 Agent 用 `reproduce.sh` 比较本次读数与交付记录。[交付与复查](skills/zhibi/references/deliver.md)

## 为什么叫「知彼」

### 知彼：同一个账号，换个入口会发生什么？

你在电脑浏览器里聊到一半，出门后拿起手机，用移动网络继续。对你来说是同一段对话，从风控角度看，客户端、设备和出口都换了。只查一次 VPS 的 IP，看不到这些变化。知彼因此分别测量你实际使用的浏览器和 Linux 工作区。

### 知己：每个入口需要接触哪些本机信息？

- **网页版用主流浏览器的独立配置。** 可以让知彼创建专用 Chromium，也可以使用配置好的指纹浏览器。给 Claude 单独一份 Cookie、扩展和站点权限，你日常浏览器里多年积累的设置就不用一起带进来。
- **Claude Code 放在隔离的 Linux。** 终端程序能访问当前用户有权限读取的文件、环境变量，还能启动子进程。知彼给它独立的主目录和选定的项目目录，并检查这个工作区的实际出口。远程服务器和本地 Linux 虚拟机遵循同一个原则；本机编辑器仍然照常用。
- **Claude Desktop、手机 App 和日常浏览器配置不作为日常入口。** 桌面和手机各有自己的系统权限、本地状态和网络切换方式；浏览器上的配置也管不到这些原生客户端。安卓手机在 Google Play 路线里承担的是安装、付款和核对订阅。网页确认套餐到账后，就可以卸载 App，回到配好的环境。[注册与订阅图文教程](docs/tutorials/claude-google-play.md)

> 作者曾在大厂国际风控团队实习。目前我用这套环境长期使用两份每月 200 美元的 Claude Ultra 订阅。

## 底层架构与隐私安全

远程 Linux 用 `bubblewrap` 隔离进程和主目录，用 `graftcp` 将应用及其子进程的 TCP 连接交给代理。浏览器使用单独配置的网络连接。Agent 可以用受控断线演练验证阻断和恢复，把结果和还需要核验的协议写进本机报告。账号登录、验证码和付款都在官方页面由你完成。

[双路线架构](docs/implementation/two-route-plan.md) · [持久化入口](docs/implementation/native-delivery.md) · [数据流与隐私](docs/reference/privacy.md) · [Anthropic 支持地区](https://www.anthropic.com/legal/supported-regions)

## 致谢与参考项目

感谢以下优秀开源项目的作者与贡献者：

- [xiaoxiaodong-vps](https://github.com/nevertoday/xiaoxiaodong-vps)：VPS 部署、Agent Skill 组织与运维流程参考。
- [CCBaga](https://github.com/liseami/CCBaga)：网络检查与环境配置流程参考，适配了部分浏览器出口检测代码。
- [CheckCC](https://github.com/yacuo/check-cc)：适配了部分浏览器环境采集、字体探测与研究模型。
- [IPQuality](https://github.com/xykt/IPQuality)：IP 质量检测方法研究与对照。
- [Blackhole](https://github.com/tommy0103/blackhole)：项目绑定、持久化会话与启动体验参考。
- [PVM](https://github.com/huangzheng2016/pvm)：提供本地 Linux 虚拟机、共享目录、桌面与出口能力的可选后端。
- [bubblewrap](https://github.com/containers/bubblewrap)：Linux 轻量级进程沙箱隔离工具。
- [graftcp](https://github.com/hmgle/graftcp)：应用及其子进程的代理网络接管工具。

[MIT](LICENSE) · [第三方声明](THIRD_PARTY_NOTICES.md) · [上游复用说明](docs/research/upstream-reuse.md) · [贡献](CONTRIBUTING.md)
