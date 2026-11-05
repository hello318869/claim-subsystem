# CR03分组与计数浏览器回归记录

执行日期：2026年11月5日（Asia/Shanghai）。独立无头Edge 156.0.4314.58；实际HTTP端口18082；真实MySQL33307的claim_dev。未操作claim_test或18080。

## 修复前状态

RG01-RG08、RG10共9项通过，390px无横向溢出。RG09保留失败，等待实现侧修复后限定复测。没有重复此前15项写业务。

| 用例 | 结果 | 观察 |
| --- | --- | --- |
| RG-01 默认分组 | 通过 | {'active_group': 'applicant', 'first_page_ids_match_api': True} |
| RG-02 两组计数准确 | 通过 | {'ui': {'applicant': {'text': '23', 'state': 'ready'}, 'finder': {'text': '2', 'state': 'ready'}}, 'api': {'applicant': 23, 'finder': 2}} |
| RG-03 快速切组与迟到响应隔离 | 通过 | {'quick_round_trips': 3, 'delayed_real_applicant_response_did_not_overwrite_finder': True} |
| RG-04 分页与切组重置 | 通过 | {'applicant_total': 23, 'page_two_exact': True, 'switch_resets_page': 1} |
| RG-05 空组说明 | 通过 | {'actual_api_total': 0, 'explicit_empty_states': True, 'zero_only_after_successful_total': True} |
| RG-06 身份变化清空计数和私有内容 | 通过 | {'identity_sequence': ['alice', 'bob', 'outsider'], 'immediate_counts': '—', 'private_workspace_hidden': True} |
| RG-07 第三方无详情或消息权限 | 通过 | {'detail_http': 403, 'messages_http': 403, 'outsider_list_total': 0} |
| RG-08 界面无混合入口且all兼容 | 通过 | {'ui_roles': ['applicant', 'finder'], 'all_http': 200, 'all_contains_only_related_ids': True} |
| RG-09 计数失败占位与恢复 | 待修复 | 断网注入的初次等待假设 data-count-state=error；实际呈现为 unavailable，已修正测试等待属性，未据此修改产品。 |
| RG-10 两组不重叠且并集等于all | 通过 | {'applicant': 23, 'finder': 2, 'intersection': 0, 'union': 25, 'all': 25} |

## RG09限定复现的实际数据来源

第二次仅执行RG09。初始alice的有效接口total为我发起的23、我收到的2。随后阻断全部 /v1/claims 请求，切换组产生的新列表请求失败，界面仍将之前23/2作为ready显示，没有标注“旧缓存”或“暂不可用”。再点击刷新，在两组均无新的成功total来源时显示“—”，没有伪造0。
恢复路由并派发online事件后，1秒时仍显示“—”；手工点击刷新后恢复真实23/2。1秒观察不作为最终自动恢复超时结论，修复后将以5至10秒内真实请求完成为准。
需区分：如果某组的专用page_size=1计数失败，但该组列表请求成功且返回准确total，可以用该total显示当前组；不应为了测试要求丢弃有效来源。最终复测将同时核对这一备用来源。

## 当前静态资源与控制台结果

最终独立干净首屏：favicon.ico请求0、控制台错误0、JavaScript pageerror0。故此前favicon404已经解决。RG09主动注入的ERR_INTERNET_DISCONNECTED单独保留为预期故障消息，不混算成正常运行错误。旧 evidence/ui/ui-validation*.json 的失败历史未覆盖。

## 数据与进程清理

每次新建唯一UI-QA前缀的26条ListingSnapshot；26份申请全部经真实POST /v1/claims创建，未手工插入/修改claim来凑计数。每次结束都只清理自身26条记录、26份申请、26条幂等响应及26条审计。18082自身进程与浏览器已停止，33307 MySQL和18080未改动。

## 可复现附件

- 稳定fixture已从tmp整理为 scripts/ui_fixture.py，严格限定claim_dev /33307和UI-QA字母数字连字符前缀；按所属申请、消息ID和精确前缀清理。
- scripts/ui_smoke.cjs 已引用 scripts/ui_fixture.py，最终附件无需tmp目录。
- scripts/ui_cr03.cjs 自动建立独立prefix、通过真实API产生分页样本、执行RG01-RG10、保存JSON/截图并清理。环境变量CLAIM_UI_CASE=RG-09可只跑未通过项；CLAIM_PYTHON及CLAIM_PLAYWRIGHT_MODULE可指定本机Python与Playwright包。
- 首轮9通过及RG09初始失败：evidence/ui-cr03-validation-attempt1.json；限定复现：evidence/ui-cr03-validation-attempt2-rg09-before-fix.json；对应图片留在evidence/ui-cr03/before-rg09-fix。
