# CR03最终浏览器回归记录

结论：**累计10项通过**。这是分阶段验证：阶段1通过RG01–08、RG10；本轮仅重测RG09与干净首屏。没有声称本轮重跑全部10项，也未重复此前15项写业务。

使用真实HTTP、独立无头Edge 156.0.4314.58，APP_ENV=dev，18082后端与MySQL33307的claim_dev。未触碰claim_test或18080。所有样本为唯一UI-QA前缀的合成数据。

## 用例结果

| 用例 | 结果 | 阶段与证据 | 观察 |
| --- | --- | --- | --- |
| RG-01 | 通过 | phase-1 / ui-cr03-validation-attempt1.json | 默认我发起的；高亮与第一页API顺序一致。 |
| RG-02 | 通过 | phase-1 / ui-cr03-validation-attempt1.json | UI两组23/2与各自接口total一致。 |
| RG-03 | 通过 | phase-1 / ui-cr03-validation-attempt1.json | 快速切组三轮；真实旧响应延迟到达后不覆盖当前组。 |
| RG-04 | 通过 | phase-1 / ui-cr03-validation-attempt1.json | >20条时第二页与API一致；切组回第一页。 |
| RG-05 | 通过 | phase-1 / ui-cr03-validation-attempt1.json | outsider实际all=0，两组有明确空态，0只来自成功接口。 |
| RG-06 | 通过 | phase-1 / ui-cr03-validation-attempt1.json | Alice→Bob→outsider切换时立即清旧计数和私有区，新计数与新身份API一致。 |
| RG-07 | 通过 | phase-1 / ui-cr03-validation-attempt1.json | 第三方详情、消息均403，列表无他人申请。 |
| RG-08 | 通过 | phase-1 / ui-cr03-validation-attempt1.json | 仅两个UI分组，role=all仍200且只含本人相关ID。 |
| RG-09 | 通过 | phase-3-rg09-fix / ui-cr03-rg09-final-run.json | 全失败时—；online自动恢复23/2，5次online仅一轮3请求；有效列表total可作备用来源。 |
| RG-10 | 通过 | phase-1 / ui-cr03-validation-attempt1.json | 两组无交集，去重并集25=all25。 |

## RG09修复后的实际观察

1. 全部claims请求失败时，切换组及手动刷新均将两组显示为“—/暂不可用”，不冒称旧23/2是本次刷新结果，也不伪造0。
2. 恢复请求后触发online，不点击刷新即恢复真实23/2。通过最长10秒条件等待真实请求完成；本次记录恢复耗时 35 ms，此数字只描述本次事件，不作为性能基准。
3. 恢复请求的真实响应被临时延迟，在inflight期间派发5次online，只发出3次claims请求：applicant计数page_size=1、finder计数page_size=1、当前finder列表page_size=20，各一次。响应内容未伪造。
4. 单独让page_size=1计数请求失败时，本人当前applicant列表仍成功返回total=23，UI正确显示23；另一组没有任何成功total来源时显示—。恢复后online把另一组恢复为2。
5. 故障注入产生的网络资源错误单独归属RG09；最终独立干净页面控制台错误0、JS pageerror0、favicon.ico请求0，未发现非预期错误或真实后端5xx。

## 最终截图与安全检查

截图均来自实际浏览器，已逐张查看。只出现合成样本标题、演示角色和计数，**无仍有效令牌、明文交接码、真实身份或私有证据**。手机图为最新代码重新拍摄，390px无横向溢出。

| 图片 | 场景 |
| --- | --- |
| [ 06-final-group-overview.png ](ui-cr03/06-final-group-overview.png) | latest-default-group |
| [ 04-count-unavailable-error.png ](ui-cr03/04-count-unavailable-error.png) | latest-failed-count-unavailable |
| [ 07-online-recovered-counts.png ](ui-cr03/07-online-recovered-counts.png) | latest-online-recovery |
| [ 05-mobile-390-group.png ](ui-cr03/05-mobile-390-group.png) | latest-390px-group |

图片SHA、尺寸、来源运行与所测源码SHA见ui-cr03/final-screenshot-manifest.json。

## 源码版本证据

- `web/index.html` SHA-256 `13af85bf2f4222a5228c055e14701c0a55206c4d94edfd1e2669f461d7a8e7f9`
- `web/app.js` SHA-256 `3b4f0527ae393df8b28adac1dc74c426f321402a67bfca95928209637c2deebc`
- `web/styles.css` SHA-256 `02021b19855f28c388cd3e4465e5fac5c8e86166caee239e2fb5db05dc5fd4d0`

上述三文件在RG09执行及最终截图期间未变。阶段1的原始源码SHA另保留在原始JSON中，供对照跨阶段范围。

## 历史和清理

失败原证据ui-cr03-validation-attempt1.json、ui-cr03-validation-attempt2-rg09-before-fix.json及before-rg09-fix截图均保留。此前ui/ui-validation-attempt1/2.json中的favicon失败也未覆盖。
本轮RG09与单独最终截图各自采用不同唯一prefix；每次只新增26条snapshot，经真实POST创建26份申请，结束按自身前缀/申请ID清理26份申请、26条幂等缓存、26条审计与26条snapshot。自己的18082进程及浏览器均已关闭，MySQL33307与其他任务进程保持不变。

## 可复现附件

- scripts/ui_fixture.py为稳定fixture，严格限定claim_dev/33307及字母数字连字符UI-QA前缀，已不依赖tmp。
- scripts/ui_smoke.cjs已改用scripts/ui_fixture.py；此前15项证据继续使用，不因CR03重复执行。
- scripts/ui_cr03.cjs默认跑RG01–RG10；CLAIM_UI_CASE=RG-09仅重测该项，CLAIM_UI_CASE=SCREENSHOTS仅拍最终界面；环境变量CLAIM_PYTHON、CLAIM_PLAYWRIGHT_MODULE可指定本机运行时。
- 当前JSON是分阶段10项汇总；原始本轮只有1项测试，详见ui-cr03-rg09-final-run.json；最终图运行没有重复业务用例，详见ui-cr03-final-visual-capture.json。
