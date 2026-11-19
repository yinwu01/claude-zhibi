# 知彼（claude-zhibi）

> **知己知彼，从风控的角度减少账号封禁风险。**

知彼是一个从账号开通到日常使用都能接手的 Agent Skill。让 Agent 带你注册、实测本地网络，或配置独立浏览器和隔离的 Linux 工作区。告诉它你已经做到哪一步，它就从那里接着做。
BTW，作者通过本套方案稳定使用两份 Claude Ultra 订阅。

**从你要做的事开始**

- 📖 [我要注册或开通订阅](docs/tutorials/claude-google-play.md)
- 🌐 [我只用 Claude 网页版](#路径-a只用-claude-网页版)
- 💻 [我还要用 Claude Code 写代码](#路径-b网页版与-claude-code)

[项目输出](#你会得到什么) · [输入清单](#需要准备什么) · [使用范围](#可以怎么用哪些用法不支持) · [快速开始](#快速开始) · [看体检报告](#核心体验) · [日常使用](#日常使用) · [English](README.en.md)

## 为什么叫「知彼」？

市面上不少防封教程一上来就让你在本机套一层重型虚拟机。对大多数开发者来说，本机虚拟机吃内存、耗电量高、编码体验割裂，且一旦宿主机代理闪断仍可能漏出真实网络特征；更关键的是，如果你不清楚平台到底在审什么，哪怕套了虚拟机照样会被误杀。

我们追求的是**生产级别的长期稳定**。「知彼」的核心设计是**双向的**：

### 1. 知彼：大厂的风控团队在看什么？
现代风控系统从来不只看“IP 在不在海外”，而是在做**多维信号的自洽性交叉验证**：
* **网络层**：出口 IP 的纯净度与 ASN 属性（机房段还是住宅段）、是否存在多人共用的黑历史、底层协议是否漏出真实地址（WebRTC / DNS / 直连 UDP）。
* **终端层**：客户端上报的宿主环境特征（系统时区、语言、硬件与系统级遥测、应用商店与支付归属地）。
* **轨迹层**：同一个账号在不同终端、不同时间段登录时的网络与设备特征是否前后打架。

### 2. 知己：作为用户，怎么把“触发风控的特征”压到最低？
答案不是去强行伪装你全身都是本土特征的日常主力系统，而是**主动收敛暴露面**。客户端越“原生”，拿到的系统底层权限就越深，漏出去的异常信号就越多——这也直接决定了「知彼」的架构设计：

* **🚫 为什么长期使用时严禁在主力设备上安装和使用 Claude 原生客户端？**\
  你的日常手机和电脑宿主机是风控特征的“重灾区”（手机有 SIM 卡运营商代码、App Store 账号归属、系统级推送与定位；电脑原生桌面端能直接读取宿主机环境与真实网卡）。在日常主力系统上几乎不可能把原生客户端包得滴水不漏，一旦分流遗漏或代理闪断就会瞬间裸连穿帮。**知彼严格限制长期使用入口。电脑用独立浏览器，写代码用隔离 Linux。开通 Google Play 订阅时需要临时使用安卓 Claude App，确认网页套餐生效后卸载。**
* **✅ 为什么采用「独立浏览器 + 隔离的 Linux 环境」？**\
  砍掉高危原生客户端后，我们把所有使用场景收敛进两个**暴露面极小、完全可控**的隔离容器里，同时把具体工具与部署形态的选择权留给你：
  1. **日常网页对话 👉 用「配好的独立浏览器」**：把网页交互关在独立的浏览器沙盒内，隔离指纹、Cookie、WebRTC 与时区语言（可以由知彼配置专用 Chromium，也可以选用 AdsPower、MoreLogin 或比特浏览器）。*如果你只用网页版，走到这一步就够了。*
  2. **写代码、跑 Claude Code CLI 👉 放进「隔离的 Linux 环境」**：指纹浏览器保护不了宿主机命令行，在宿主机终端直接裸跑 CLI 极易暴露本地环境。因此知彼为 CLI 准备独立的 Linux 环境，并分别实测浏览器与 CLI 是否共用预期出口。
     * 🌟 **首选推荐：远程 Linux 服务器（可直接复用你的海外 VPS）** · 编码任务在远程运行，浏览器和 CLI 可以共用 VPS 出口。
     * 🔧 **兼容备选：本机 Linux 虚拟机（支持但不推荐默认使用）** —— 如果你的项目代码因合规/保密要求不便上云，「知彼」同样支持部署在本机虚拟机中；只是它更吃本机硬件资源，且对本地透明代理/防泄漏配置的要求更高，建议按需选用。

> 有趣的是，以上的 motivation 主要来自于我在 ByteDance 负责国际风控 agent research时的一些总结，会比较片面:)，欢迎大家交流👏

## 🗺️ 整体架构一览

**推荐部署采用自有 VPS 统一出口。** 如果使用本地 Linux 虚拟机，也可以选择沿用本机网络。

```text
┌──────────────────────── 你的日常主力电脑 (本地宿主机) ───────────────────────┐
│                                                                              │
│  ✅ 配好的独立浏览器                    ✅ 本地编辑器 / 终端                 │
│  (负责：日常网页对话)                   (负责：VS Code Remote-SSH / 纯 SSH)  │
│  * 专用 Chromium 或指纹浏览器           * 连入远程 Linux 或本地 Linux 虚拟机 │
│                                                                              │
│  ❌ 严禁日常普通浏览器直接裸连            ❌ 严禁宿主机终端直接裸跑 CLI       │
│  ❌ 长期使用：严禁安装或使用 Claude Desktop 和手机 App                       │
│  📱 安卓 App 仅用于 Google Play 注册和订阅，网页确认到账后卸载               │
└───────────────┬──────────────────────────────────────────┬───────────────────┘
                │ 加密代理通道                              │ SSH 开发连接
                ▼                                          ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  ☁️ 海外 VPS (独享网络底座)       +       🐧 隔离的 Linux 环境 (CLI 运行底座)│
│                                                                              │
│  🌟 推荐形态：远程 Linux 服务器 —— 可直接与左侧 VPS【一机两用】(建议 ≥2GB)   │
│  🔧 备选形态：本机 Linux 虚拟机 —— 支持代码留本地，但吃资源且防漏要求更高    │
└───────────────────────────────────────┬──────────────────────────────────────┘
                                        │ 共用自有 VPS 出口（可接已有的 SOCKS5 上游）
                                        ▼
                          🎯 分别实测浏览器和 CLI 的网络出口
                                        │
                                        ▼
                             🌐 Anthropic (Claude 服务)
```

## 需要准备什么

| 准备项 | 用途 |
| --- | --- |
| **一台自有 VPS（需要专用远端出口时）** | 家宽或机房线路均可先实测，优先选择可自主管理的独享线路。请准备服务器地址、SSH 用户名与端口（或已有 SSH 别名），以及可在服务商控制台核对的主机指纹。 |
| **一个独立的浏览器环境** | 用于 Claude 网页版。可使用自选的指纹浏览器，或由知彼创建专用 Chromium 环境；Agent 会视当前条件自动调用接口或辅助操作界面。 |
| **Linux 工作环境** | 仅 Claude Code 路线需要。优先复用自有 Linux VPS（单机即可同时运行 CLI 并提供出口）；也可基于 [PVM](https://github.com/huangzheng2016/pvm) 创建本地虚拟机，或通过 SSH 接入已有 Linux 虚拟机。 |
| **Agent 和本机工具** | Python 3.9+、SSH 客户端，以及能执行本地命令的 Agent。推荐采用Codex，因为会涉及到computer use。 |

如果只是检测网络或开通订阅，直接从现有环境开始即可。Agent 可引导你操作官方页面，涉及密码、验证码与付款确认的步骤均由你本人完成。通过安卓手机订阅时，准备一台能用 Google Play 的手机、一个 Google 账号和当地 Play 接受的付款方式。[Google Play 开通教程](docs/tutorials/claude-google-play.md)

**付款前先看 Google Play 的首期总额和续费金额。** Claude Ultra 的网页版标价为每月 200 美元，移动端价格可能不同。约 250 美元可作结账金额示例，实际套餐价、税费和总额以你的结账页为准。[Claude Ultra 定价](https://support.claude.com/en/articles/17728952-what-is-the-ultra-plan) · [Google Play 税费说明](https://support.google.com/googleplay/answer/2850368)

## 你会得到什么

- **[账号开通](docs/tutorials/claude-google-play.md)**：按图文教程注册、安装和订阅，也可以请 Agent 带你走当前这一步。
- **独立的浏览器环境**：配置完成后，日常直接打开使用。
- **隔离的 CLI 工作区**（选配 Claude Code 时）：一套隔离的 Linux 应用环境，以及绑定到具体项目的启动入口。
- **可复查的验收记录**：并排对比浏览器与实际运行路径的 IPv4、IPv6 出口，附上已测到的 WebRTC 与 DNS 结果。后续复查时还能核对两端地址是否同步切换。详见[出口一致性检查](skills/zhibi/references/audit.md#出口一致性)。

配置完成后，Agent 会交给你一个**交付目录**。打开 `先读我.md` 找日常启动入口，打开 `报告.html` 看本次验收结果和待处理项。

## 可以怎么用，哪些用法不支持

**日常只推荐两个入口：独立浏览器里聊 Claude，隔离的 Linux 里跑 Claude Code。** 从风控角度看，同一账号换到另一个客户端时，设备特征、权限和联网方式也随之变化。把日常工作集中在这两处，可以减少主力设备上少见的个性化特征组合，也方便 Agent 实测网页与 CLI 是否走同一出口。[为什么只推荐浏览器和 Linux](#为什么叫知彼)

| 场景 | 支持的用法 | 不在知彼配置和验收范围内的用法 |
| --- | --- | --- |
| 网页对话 | 打开配好的专用 Chromium 或指纹浏览器配置。 | 在日常浏览器的默认配置中直接登录。进入长期使用后，严禁安装或使用 Claude Desktop 和手机 App。 |
| 编码 | 用本机编辑器打开项目，从交付的入口在远程 Linux 或本地 Linux 虚拟机里运行 Claude Code。 | 直接在主力电脑终端或未经配置的 SSH 登录环境里启动 CLI。 |

**通过 Google Play 注册和开通订阅时，需要临时安装安卓 Claude App。** 在 App 内登录或创建 Claude 账号并付款。确认 Claude 网页端已显示付费套餐后，卸载手机 App，之后只用配好的独立浏览器或隔离 Linux。[Google Play 开通教程](docs/tutorials/claude-google-play.md)

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

## 日常使用

交付时请先打开交付目录中的 **先读我.md**。里面写的是你这次实际配好的浏览器、项目和启动方式。

- 🌐 **聊 Claude** · 打开交付时命名的浏览器配置。专用 Chromium 有 `open-browser.sh`；浏览器装在 PVM 桌面里则用 `open-vm-desktop.sh`。
- 💻 **写代码** · 在本机终端进入交付目录，运行 `bash open-project.sh` 启动绑定的项目。编辑器通过 SSH 打开文件；如果交付说明还确认了远程项目里的 `claude` 已指向隔离入口，也可以在那里直接输入 `claude`。[编辑器接入](skills/zhibi/references/projects.md#编辑器接入)
- 🔍 **换线后复查** · 把交付目录交给 Agent，说「帮我复查现在的出口」。涉及浏览器时，先从正在用的浏览器重新采集，再让 Agent 用 `reproduce.sh` 比较本次读数与交付记录。[交付与复查](skills/zhibi/references/deliver.md)


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
