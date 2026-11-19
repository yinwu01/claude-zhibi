# 账号与 Google Play 开通

用户需要注册、开通订阅、核对账号或排查付款时读取。先查明用户目前的状态，从第一个还没完成的步骤继续。已付费时先核对套餐与订单；已经付费并且套餐正常时直接转向配置或日常使用。

用户想看页面示例时，打开[注册与订阅图文教程](https://github.com/yinwu01/claude-zhibi/blob/main/docs/tutorials/claude-google-play.md)，从开头的进度表选到当前一步。已扣款时先带用户核对 Play 订单和 Claude 网页套餐。

使用官方页面。确认实际所在地符合 [Anthropic 支持地区政策](https://www.anthropic.com/legal/supported-regions)。设置 Google Play 地区时按 [Google Play 地区要求](https://support.google.com/googleplay/answer/7431675) 使用真实地区与付款资料。VPS 网络出口属于单独的环境配置。

Agent 能看到或操作实际页面时，用 computer use 打开官方入口、指出当前步骤、核对账号及状态。界面有差别时，读当前屏幕和官方说明。手机画面不在 Agent 的可操作范围内时，给用户当前一步的操作，等用户回报结果后再接着走。密码、验证码、完整卡号、账单地址和身份材料由用户直接在官方页面处理；付款确认也交给用户。向用户确认结果时，用「邮箱是否一致」等最少信息。

1. **选定同一个 Google 账号。** 启用这条 Play 路线时，桌面 Play 网页、安卓 Play 商店、Claude 的「使用 Google 登录」和 Play 付款弹窗用同一个账号。需要创建 Google 账号时从 [Google 账号入口](https://accounts.google.com/) 进入。已有能用的账号就复用。新建 Claude 账号或登录时按 [Claude 官方登录说明](https://support.claude.com/en/articles/13189465-log-in-to-your-claude-account) 操作。
2. **安装。** 让用户在安卓手机添加同一个 Google 账号并用它进入 Play 商店。在电脑上可用这个账号打开 [Claude 官方商店页](https://play.google.com/store/apps/details?id=com.anthropic.claude)，下发到用户选的手机；也可在手机上直接安装。电脑看不到手机时用 [设备关联排查](https://support.google.com/googleplay/answer/6178908)。
3. **确认订阅。** 让用户在 Claude App 用同一个账号登录。选择界面实际提供的方案，核对 Play 付款弹窗里的邮箱、支付方式、总额和续费周期。看到旧账号时先退出这次付款。付款方式可在 [Google 付款中心](https://payments.google.com/) 查看。金额和税费以实际结账页和收据为准。
4. **核对到账。** 用同一 Google 账号查看 [Google Play 订阅](https://play.google.com/store/account/subscriptions)，再到 [Claude 网页版](https://claude.ai/) 选择使用 Google 登录，确认套餐。Play 有订单而 Claude 仍显示免费时先核对邮箱和订单状态，再按 [官方账单排查](https://support.claude.com/en/articles/8325618-paid-plan-billing-faqs) 处理。
5. **转向日常使用。** 确认到账后用户可自行卸载安卓 App，续费、换卡和取消仍由 [Google Play](https://support.google.com/googleplay/answer/7018481) 管理。按 [需求分流](intake.md) 转到独立浏览器或浏览器加 Linux 路线。Claude Code 需要使用订阅时，选择对应的 Claude 账号完成 [官方授权流程](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-max-or-ultra-plan)。

遇到用户尚未开通的其他官方渠道，按用户当时的目标和可用选项协助。用户明确要求暂缓打开目标服务、登录或运行应用时，先做当前允许的准备或替身验收。
