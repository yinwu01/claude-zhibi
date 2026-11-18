# 交付

交付以用户的日常操作为准：Linux 服务器上直接输入已包裹的应用命令；指纹浏览器里直接打开已配置的环境。浏览器配置由 Agent 按实际能力使用 API、computer use 或两者结合完成，不固定品牌或接入方式。

先说明用户以后输入什么应用命令、打开哪个浏览器环境，再提供本次验证结果。配置目录、报告和恢复工具属于维护材料，不要求用户每次使用前先运行知彼。

- 浏览器线路：需要隧道时配置独立后台连接并验证，再把代理保存到选定的浏览器环境。`connect --export-out` 保留为临时连接或排障工具，不以保持前台窗口作为默认日常交付。
- 仅浏览器：使用 `deliver --proxy-port PORT --egress --browser BROWSER_JSON --browser-profile NAME --browser-service LOCAL_SERVICE_DIR`，并列记录实际后台连接和浏览器的 IPv4、IPv6。若已经有固定的预期地址，仍可用 `--expected-ip` 和 `--expected-ipv6` 核对。
- 浏览器加 CLI：使用 `deliver --project LOCAL_PROJECT --egress --browser BROWSER_JSON --browser-profile NAME --browser-service LOCAL_SERVICE_DIR`。SSH 项目用 `project bind --runtime-workspace` 让启动和验收走同一环境。已知预期出口时加 `--expected-ip IP`。仅浏览器路线指定的验收端口须与随包交付的后台服务和 Chromium 工作区一致。
- 专用 Chromium 使用 `--browser-workspace CHROMIUM_DIRECTORY`，生成 `open-browser.sh`。选用 PVM 桌面内的浏览器时，加 `--vm-browser --browser-profile NAME`，生成 `open-vm-desktop.sh`。已绑定的项目生成 `open-project.sh`，从本机终端执行。
- 已安装远端用户网关时加 `--runtime-service REMOTE_SERVICE_DIR`，工作区的应用入口用 `--app-entry ENTRY` 记录。若启用了远端 Bash 或 Zsh 的原命令入口，再加 `--shell SHELL --remote-skill-entry REMOTE_ZHIBI_SCRIPT` 生成恢复命令。远端服务路径属于绑定项目的 SSH 目标；不同主机的独立服务分别记录。旧版 `build` 使用 `--host` 和 `--build-receipt` 交付。
- 恢复：`rollback.sh` 仅在记录了可恢复的改动时生成。后台服务管理器会校验自身部署回执；浏览器界面的手工改动另行记录原值。
- 断线报告：`--outage-report REPORT` 读取同一绑定最近 15 分钟内保存的 `project audit` 演练报告。无需再次停网。
- 重查：`reproduce.sh` 使用当前安装的知彼，复测正常连接。含浏览器时传当前实际浏览器的新导出文件，例如 `bash reproduce.sh NEW_BROWSER.json`。新报告同时对照本次两端读数和 `environment.private.json` 里的历史出口。固定线路选 `--exit-policy fixed`，历史 IP 变更会使验收失败；动态线路选 `--exit-policy dynamic`，历史变化会提示。声明预期 IP 时默认固定，否则默认动态。首次验收通过后才记录历史地址。如果要重测断线，单独按 [断网演练](audit.md#受控断网演练) 操作。

先报告能否正常运行、能否完成用户需要的操作、哪些项未测或失败，再给出启动、停止、恢复方式及文件夹路径。明确写出使用的是实际应用和浏览器，还是替身命令和测试页。

文件夹包含私人连接与读数，默认仅在本机保存；对外分享应使用脱敏摘要。新会话先用 `environment status --folder DIR` 查看过程或交付记录，然后按记录核对现场。过程目录可用 `--environment DIR` 从阶段命令自动写入产物路径，或用 `environment checkpoint` 引用已经完成的外部配置。

使用 runtime-service 时，把远端服务目录、服务名、profile 路径和完整 SSH 目标一起记录在私人交付目录，并给出 `manage.py status`、`systemctl --user restart SERVICE` 与 `manage.py rollback` 的远端执行方式。保留该服务目录中的 receipt.json 和 gateway-owner.json；恢复由对应 manage.py 校验文件摘要和端点归属。不要把用户级服务套用成 `/etc/systemd/system` 的旧 build 恢复命令。交互式应用另交付 process-entry 的 PATH 设置与检查方式。
