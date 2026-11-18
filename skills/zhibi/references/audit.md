# 两条路线的验收

先记录用户实际需求和目标出口。配置存在、进程运行、上游命令退出 0 都不是完整验收。

## 出口一致性

配置前用 `session --preset network --network` 记录实际浏览器的 IPv4、IPv6 和 WebRTC。已有自建 DNS 观测域名时加 `--dns-observer https://dns.example.org`；没有时 DNS 保持未测。配置和恢复后在目标浏览器重新采集，使用同次读数：

```bash
# 路线 A，后台转发与浏览器
zhibi accept --proxy-port PORT --egress --browser BROWSER_JSON
# 路线 B，绑定应用与浏览器
zhibi accept --project LOCAL_PROJECT --egress --browser BROWSER_JSON
```

报告把两处运行环境并排列出，每个地址族单独比较。两端采样的 HTTPS 端点需相同，时间相差五分钟内。只有一端取得 IPv6 时保留读数和症状，不能单凭另一端超时推断其 IPv6 被禁用。浏览器旧版本导出仍可使用，缺少的项目标为待确认。另有固定的预期出口时加 `--expected-ip IPV4`，有单独的预期 IPv6 时加 `--expected-ipv6 IPV6`。手动提供的预期地址也可独立用于浏览器核对。

`connection-check --local-port PORT --family 6 --network` 可单独排查后台连接的 IPv6。需要 ASN、运营商和 IP 类型时，用已有的 `scan --network --ipv6 --reputation --target browser --browser BROWSER_JSON --out NEW_DIRECTORY` 查询浏览器测到的地址，逐个来源查看结果与分歧。

交付包的 `报告.html` 首屏并排列出出口、需要处理的差异和下一步。WebRTC 记录公网候选与 HTTPS 对照。浏览器 DNS 只有通过配置好的观测端取得解析器记录时才有读数。主动扫描和 `session` 的 `report.html` 展示本轮查到的网络归属、ASN、线路类型、代理标签及各来源信誉分。

## 应用上下文

远程路线在 bind 时传 `--runtime-workspace REMOTE_PROFILE`，启动、恢复和探针走同一份 bwrap 工作区与项目目录。探针本身只运行知彼的 Python 命令。未绑定这个工作区时，宿主读数和旧版 `--probe-prefix-file` 的自定义探针都不能确认应用通过同一运行器。PVM 在该项目实际使用的 guest 内测量。

PVM 路线的探针运行在绑定 VM 内。实际浏览器必须是用户选定的浏览器：远程路线通常为本地专用浏览器，VM 路线可为 VM 桌面浏览器。`session` 导出的 JSON 用于同一次出口对比；旧读数不算新验收。

```bash
zhibi project audit --project LOCAL_PROJECT --network --expected-ip EXPECTED_IP \
  --browser BROWSER_JSON --out NEW_REPORT.private.json
```

探针通过 api.ipify.org 和 api6.ipify.org 分别测两种地址族；报告私有保存，输出包含本次 IP。DNS 解析成功只说明可解析。对 DNS 路径需要自建观察端或 PVM 出口探针，UDP 用已知可达的测试端点验证，IPv6 需结合路由和实际请求。PVM 还检查 IPv6 地址和路由策略。缺少观测保留待确认。

## 受控断网演练

准备两个本机 600 私人脚本，仅操作本次已授权测试环境的出口：断开脚本与恢复脚本。脚本可以通过 SSH 操作特定服务，也可以操作测试网关；不得停止用户整个代理、整台宿主网络或无关服务。

```bash
zhibi project audit --project LOCAL_PROJECT --network --expected-ip EXPECTED_IP \
  --disconnect-file DISCONNECT_SCRIPT --reconnect-file RECONNECT_SCRIPT \
  --browser BROWSER_JSON --out NEW_REPORT.private.json
```

先证明正常状态可访问，才执行断开；恢复动作在 finally 执行。任何一个地址族在断开期间仍取得公网出口，演练即失败。探针必须仍可执行，且此前有出站读数的地址族请求失败，才有本次阻断证据。SSH/VM 整体失联保持待确认。恢复后核对回到原来的出口。

这个 HTTPS 演练不证明所有协议均无泄漏，所以报告不自动将 complete 设为 true。交付还需：应用实际操作、浏览器访问、DNS 路径、UDP 策略、IPv6 策略、直连例外、退出/重启/恢复逐项有证据。上游 PVM audit 附在同一报告里；它的协议成功也不替代应用和浏览器验收。

同一次搭建的 `accept` 或 `deliver` 可加 `--outage-report NEW_REPORT.private.json`。工具核对项目绑定、时效和应用出口，记录演练结果。通过的演练仅在当前应用出口仍符合演练基线时计为通过；SSH 整体失联等未确认结果仍列为未完成。导入和日常复查均不会执行断开脚本。

验收首页列出已知项目错误和待确认项。浏览器 IPv6 探针有成功读数时保留地址和采集时间；只有同地址族的预期出口可用于比对。一次 IPv6 请求失败不能证明 IPv6 已阻断。看到出口比对通过后，继续看哪些项目未确认。

配置不支持的协议明确标“已阻断”需要实际验证或有效隔离证据；请求超时不自动等于已阻断。将结果与未完成项写入交付记录，不把手填结果冒充测量。
