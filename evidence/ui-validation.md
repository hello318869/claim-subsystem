# 真实浏览器验证记录

验证日期：2026年11月5日（Asia/Shanghai）。

使用独立无头 Microsoft Edge 156.0.4314.58，Playwright 1.62.1；后端通过真实 HTTP 在本项目专用端口 18082 运行，APP_ENV=dev，数据库为真实 MySQL 33307 的 claim_dev。alice、bob、finder、outsider 使用四个独立 BrowserContext。未访问性能测试端口 18080，也未操作 claim_test。

## 结论

15 项业务、权限及版面检查通过；整轮状态保留为 **未完全通过**，因为首屏自动请求 `/favicon.ico` 返回 404，产生一条非预期资源控制台错误。没有 JavaScript pageerror。交接码过期测试主动产生的 410 属预期错误反馈。未通过项没有被隐藏或改写成成功。

## 已实际执行的检查

| 检查 | 结果 | 观察 |
| --- | --- | --- |
| four-isolated-browser-contexts | 通过 | 四个独立角色上下文，令牌仅在页面内存。 |
| desktop-no-horizontal-overflow | 通过 | 1440px 视口，文档 scrollWidth=1440。 |
| my-lost-record-matching-with-reasons | 通过 | 本人 lost 记录真实请求匹配，rules-v1.1 返回1条目标候选且有理由。 |
| two-pending-applications-created-via-ui | 通过 | Alice 与 Bob 各通过真实表单对同一物品发起 PENDING 申请。 |
| anonymous-text-message-via-ui | 通过 | 服务端 DTO 含 sender_alias 且不含 sender_id；界面呈现“我/对方”匿名角色标签。 |
| xss-payload-rendered-as-text | 通过 | 含 img/onerror 的文本按文字显示，DOM 未生成 img，onerror 未执行。 |
| pii-blocked-in-ui-and-server-not-persisted | 通过 | 手机号样例在界面被拦，直接真实 API 也返回422，数据库确认未保存该样例。 |
| outsider-api-denied | 通过 | 第三方读取申请与消息均403。 |
| approval-closes-other-pending-claim | 通过 | 拾获者通过界面批准 Alice 后，Bob 申请变 CLOSED_OTHER。 |
| two-party-handover-real-ui | 通过 | 双方通过各自界面取得本方码并提交对方码；仅一方确认保持 APPROVED，双方后 COMPLETED。 |
| disputed-freeze-history-and-export | 通过 | 通过带二次确认的界面冻结争议；消息输入禁用，真实写 API409，取码409，历史可读，导出可下载且无身份映射键。 |
| expired-code-error-ui-and-explicit-reset | 通过 | 只把自身前缀的码过期时间改到过去；真实取码410且页面说明到期，界面显式重置成功且reset_count=1。 |
| identity-switch-clears-private-dom-and-no-token-storage | 通过 | 切换到 outsider 后私有工作区隐藏、原私有证据不在可见正文；localStorage/sessionStorage均0项。 |
| 390px-mobile-no-horizontal-overflow | 通过 | 390px 视口，文档 scrollWidth=390。 |
| expired-signed-token-real-401-ui | 通过 | 注入正确签名但已过期的合成令牌，后续请求实际命中后端401，页面清除私有内容并提示重新选择身份。 |

## 真实截图

全部截图来自实际浏览器页面，未显示有效明文交接码；不模拟或绘制页面。以下路径相对于本证据目录。

| 图片 | 场景 |
| --- | --- |
| [ 01-desktop-overview.png ](ui/01-desktop-overview.png) | 桌面首屏 |
| [ 02-explainable-matching.png ](ui/02-explainable-matching.png) | 本人失物与可解释匹配 |
| [ 03-private-evidence-and-alias-chat.png ](ui/03-private-evidence-and-alias-chat.png) | 私有证据、匿名角色聊天及XSS纯文本 |
| [ 04-two-party-handover-completed.png ](ui/04-two-party-handover-completed.png) | 双方交接完成与只读聊天 |
| [ 05-dispute-read-only-export.png ](ui/05-dispute-read-only-export.png) | 争议冻结、历史与去身份导出 |
| [ 06-expired-code-error.png ](ui/06-expired-code-error.png) | 交接码到期错误 |
| [ 07-mobile-390px.png ](ui/07-mobile-390px.png) | 390px手机首屏 |
| [ 08-mobile-found-list.png ](ui/08-mobile-found-list.png) | 390px手机失物列表 |
| [ 09-expired-token-error.png ](ui/09-expired-token-error.png) | 过期令牌错误与私有内容清理 |

## 失败和修正记录

1. 首次运行在“必须展示申请人-XXXXXX字符串”的测试断言停止；实际 DTO 有 sender_alias，前端用“我/对方”显示。经项目负责人确认该匿名标签满足范围，测试将 DTO 与界面分别验证，没有修改应用实现来迎合断言。原结果保存在 ui/ui-validation-attempt1.json。
2. 第二次执行完成15项主要检查及9张截图，最后因favicon404导致严格控制台断言失败。原结果保存在 ui/ui-validation-attempt2.json；当前 ui/ui-validation.json 保留此失败状态。

## 测试接缝和边界

- 仅使用唯一前缀 `UI-QA-20261105-2042-` 的7条合成记录。所有新增4条申请、3条消息、3条交接码及对应审计/幂等/唯一获批指针在结束时按前缀或所属申请ID删除。没有清空表。
- 过期码通过修改自身合成记录时间实现，不等待30分钟。过期令牌通过测试浏览器对演示认证响应注入一个正确签名的已过期令牌；之后401来自真实后端，未模拟受保护接口。没有等待60分钟自然过期。
- 本轮验证匿名角色标签，不宣称页面展示服务端唯一别名。没有真实校园数据、其他成员真实服务、SSO、公网或长期运行验收。
- 界面业务由 Codex 侧独立验证；本记录不能代替学生本人课程验收和理解。

## 进程与可复现性

独立18082后端和本轮浏览器上下文已停止；33307隔离MySQL保持不变，18080性能测试进程未触碰。
脚本：scripts/ui_smoke.cjs；合成数据与时间接缝工具：tmp/ui/ui_fixture.py。运行前须用新的 UI-QA- 前缀 seed，再以同一 CLAIM_UI_PREFIX 执行脚本；脚本最后只清理自己的前缀。需要本机浏览器/网络的执行权限。
完整动作、API状态、限制、截图路径和清理数量：evidence/ui/ui-validation.json；所测源码哈希：evidence/ui/validation-source-hashes.json。

补充清理：消息的幂等响应只含消息ID，不含申请ID，最初清理按申请ID未覆盖4条自身消息缓存。已按各次执行的精确UTC时间窗、alice角色、chat.send操作、所属申请别名和已知合成消息逐项匹配删除，未操作其他缓存；详见 evidence/ui/cleanup-supplement.json。可复现清理工具已补充按自身消息ID清理的路径。

复现附件更新：稳定合成数据工具现为 scripts/ui_fixture.py，scripts/ui_smoke.cjs 已改用该路径，不依赖最终附件会排除的 tmp。上述执行历史仍如实保留当时的临时工具路径。favicon 修复后的独立干净首屏结果另记在 evidence/ui-cr03-validation.json，不覆盖本轮失败历史。
