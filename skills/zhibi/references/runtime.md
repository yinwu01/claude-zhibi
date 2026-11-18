# 进程与浏览器共用 VPS 出口

`connect --host HOST --user USER --local-port 10818` 默认只显示连接计划。加 `--apply` 以前台 SSH 在本机 127.0.0.1:10818 提供 SOCKS5。Agent 保留运行会话，不能结束工具进程后仍声称代理可用。停止该会话即关闭连接，不改全局代理或防火墙。

可同时指定 `--command-file FILE`，文件是本机权限 600 的用户启动脚本，通过 SSH 在 VPS 以 `sh -lc` 运行。`--workdir` 指定远端绝对工作目录。管道和 shell 表达式使用远端 shell 语义。进程继承远端环境和路由；已有代理/VPN 必须检查，不能仅凭远端运行就说使用预期出口。

需要交互时加 `--interactive` 并由宿主分配 PTY。让用户通过终端完成软件要求的登录。进程退出后该连接关闭；若浏览器需独立持续使用，另开不带命令的隧道会话。当前连接不承诺断线保持进程。

后台服务使用 `build`，仅用于不依赖交互输入、已安装且启动参数完整的程序。先检查工作目录、运行用户、权限与现有同名服务；保留原配置。不要把 shell 管道原样写进 systemd ExecStart。短命令不要用 Restart=always 无限重启。

验收包含：远端程序实际运行与操作结果、进程使用的网络路径、隧道仍运行、指定浏览器实际出口，以及停止和恢复。SSH 动态转发是 TCP SOCKS，不能承诺 UDP/WebRTC 全流量覆盖。多个浏览器可使用同一代理端口，但每个用户选定的浏览器都需要单独实测。

连接运行后，使用 `connection-check --local-port 10818 --expected-ip IP --network` 经该 SOCKS 查询实际出口。此命令不会回退直连；失败或不匹配返回非零状态。它验证指定代理路径，浏览器仍须自己采集。`connect` 退出时传递 SSH/远端命令退出码，不能把 JSON 输出当成成功。

需要交付可自行启动的入口时，用 `connect ... --export-out 新目录`，与 `--apply` 分开。文件夹含独立 `start.py`、私人连接配置、浏览器参数和使用说明；不复制私钥。生成后运行并实测，不能把导出成功当作已连通。

## 浏览器后台连接

在浏览器所在的 macOS 或 Linux 上导出连接服务。仅浏览器时用 `--vps-egress`，由 SSH 动态转发使用 VPS 现有出口。浏览器加远程应用时，改用 `--gateway-socket SOCKET`，通过 SSH 将本机 SOCKS 端口接到应用使用的同一个私人网关。SSH 连接需要用户现有的免交互认证和明确的目标身份。需要跳板或专用 known_hosts 时指定权限 600 的 `--ssh-config FILE`。

```bash
zhibi connection-service --host HOST --user USER --local-port 10818 \
  --name zhibi-web --out NEW_DIRECTORY --vps-egress
python3 NEW_DIRECTORY/manage.py install
python3 NEW_DIRECTORY/manage.py status
```

服务随本机用户登录运行。需要撤销时使用导出目录下的 `python3 manage.py rollback`。服务的就绪状态表示 SOCKS 握手成功。用 `connection-check` 和实际浏览器读数核对出口，关闭重开，并用授权测试页验证连接中断时的行为。线路切换或重连后需要确认新出口时再复测，不从服务状态推断出口 IP。系统没有可用的用户服务管理器时，可用前台连接临时测试，交付时注明它的生命周期。

### 可选 SOCKS5 上游

用户已有专用上游时，可让 VPS 私人网关转发到它。将配置写入 VPS 上当前用户拥有、权限 600 的新 JSON 文件：

```json
{"type":"socks5","host":"proxy.example","port":1080}
```

需认证时，在同一文件内加 `username`、`password`，用户名密码都不放在命令参数或报告里。SOCKS5 用户名密码协议本身不加密，使用用户信任的网络或已有加密连接。局部和上游代理均为 TCP。域名请求由上游解析，上游可能选择自己的 IPv6 路径，验收应测最终出口。

在原有 `proxy-gateway` 或 `runtime-service` 命令加 `--upstream-file FILE`。上游不可达、拒绝认证或拒绝目标时请求失败，不改用 VPS 直连。仅浏览器或多机器共用网关时，可在 VPS 用 `runtime-service --socket SOCKET --upstream-file FILE --name zhibi-edge --out SERVICE_DIR` 安装独立网关，再让浏览器连接服务使用 `--gateway-socket SOCKET`。使用上游时不选 `--vps-egress`，它只适合直接用 VPS 现有线路。

## 独立应用工作区

在目标 Linux 上用 `process-workspace --out PROFILE --workdir WORK --app-dir APP_DIR --timezone ZONE --locale LOCALE` 创建工作区。WORK 是专用可写目录，APP_DIR 是应用安装目录（只读挂载为 /opt/app）；不要把宿主 HOME 当工作目录，否则会重新暴露其中的资料。应用在独立 HOME 初始化，账号登录由用户完成。先确认 Linux 用户命名空间、bwrap、目标 locale 与应用运行库可用。

默认 isolated 模式不能访问外部网络。host 模式共享宿主线路。proxy 模式需要 `--graftcp BINARY --graftcp-sha256 SHA256 --proxy-socket SOCKET --dns-server RESOLVER`：固定 SHA256，使用合并版 graftcp，已验证源码 revision `574b30bfe1d4d36b3f3bff72041665b4df19573f`。按上游构建说明安装到专用目录，不覆盖用户既有版本。初始化仅在新 namespace 中创建无外部路由的接口，然后清空 capabilities 再运行应用。解析器须能从网关经 TCP 53 访问；按用户服务器实际 DNS 选择，不硬编码不可达的公共解析器。

`proxy-gateway --socket SOCKET` 可创建私人 Unix SOCKS5 端点，socket 的父目录需当前用户所有、权限 700。先启动临时前台网关，再创建与验证 proxy 工作区；工作区创建会检查 socket 与 graftcp。这个网关使用 VPS 现有 TCP 出口，不自动接管已有 VPN、代理或系统路由。

`process-entry --workspace PROFILE --name APP --program /opt/app/PATH --preserve-cwd` 创建独立 PATH 入口；此选项保留项目内的当前目录，项目外拒绝启动。生成结果包含手动入口与检查方法。在用户授权的 Bash 或 Zsh 配置中，用 `process-activate install --workspace PROFILE --name APP --shell bash --apply` 设置 PATH 和指向入口的交互式别名。别名使用绝对路径，入口丢失时会失败。验证会读取正常的新登录 shell 启动配置，若环境含启动钩子，应提前检查或换用临时 HOME 做演练。

重连后核对 `type -a APP` 和 `alias APP`，确保别名指向生成的入口。入口丢失、被其他别名覆盖或启动路径变化时，先修复再运行。绝对路径、其他用户和非交互程序需要单独验收。还原时用相同参数执行 `process-activate restore`，再按交付说明处理本轮创建的工作区。移除工作区前先恢复 shell 配置。

## 持续服务与恢复

`runtime-service --workspace PROFILE --name zhibi-NAME --out SERVICE_DIR` 导出独立用户级 systemd 服务。默认只托管私人网关，交互应用仍从上述入口启动。只有用户选择了后台程序时，才在命令末尾加 `-- PROGRAM ARGS...`，让服务同时托管该程序。它不提供交互终端，不替用户完成登录。

关闭此前临时网关，确认 socket 已由它正常移除，再运行输出的 `manage.py install`。安装前验证 user manager、单元语法与同名服务；新名称才安装，失败自动移除新单元。服务完成 SOCKS5 握手后通知 systemd 就绪；网关异常终止会带着后台应用一起重启。应用业务健康还需单独检查。

交付 `manage.py status` 与 `manage.py rollback` 及 receipt.json。恢复校验精确文件摘要，拒绝删除后续被修改的单元或带新增 drop-in 的服务。不要删除仍在运行的工作区/服务目录。检查 `loginctl show-user USER -p Linger`；如果用户要求退出全部登录后或重启后仍运行，再按系统权限配置用户管理器生命周期，记录原值。未启用 linger 时不承诺退出登录后继续运行。
