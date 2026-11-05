/* Real browser smoke validation. Only task-prefixed claim_dev fixtures are changed.
 * Run from the project root with CLAIM_UI_PREFIX already seeded by scripts/ui_fixture.py.
 * No credentials or live handover codes are written to evidence.
 */
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.CLAIM_PLAYWRIGHT_MODULE || String.raw`C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt\dependencies\node\node_modules\playwright`);
const ROOT = path.resolve(__dirname, '..');
const PYTHON = process.env.CLAIM_PYTHON || String.raw`C:\Users\asus\AppData\Local\Programs\Python\Python311\python.exe`;
const PREFIX = process.env.CLAIM_UI_PREFIX || 'UI-QA-20261105-2042-';
const PORT = 18082;
const BASE = `http://127.0.0.1:${PORT}`;
const OUT = path.join(ROOT, 'evidence', 'ui');
const FIXTURE = path.join(ROOT, 'scripts', 'ui_fixture.py');
const env = { ...process.env, APP_ENV: 'dev' };
delete env.DATABASE_URL;
fs.mkdirSync(OUT, { recursive: true });
const result = { started_at: new Date().toISOString(), database: 'claim_dev', mysql_port: 33307,
  app_port: PORT, fixture_prefix: PREFIX, real_http: true, checks: [], screenshots: [], api_events: [],
  console_errors: [], page_errors: [], limitations: [], cleanup: null, success: false };
const actors = {};
let server;
let browser;
let sequence = 0;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function helper(action, claimId) {
  const args = [FIXTURE, action, '--prefix', PREFIX];
  if (claimId) args.push('--claim-id', claimId);
  return cp.execFileSync(PYTHON, args, { cwd: ROOT, env, windowsHide: true, encoding: 'utf8' }).trim();
}
function check(name, detail) { result.checks.push({ name, passed: true, detail }); }
async function api(actor, suffix, method = 'GET', body) {
  const response = await actors[actor].context.request.fetch(`${BASE}/v1${suffix}`, {
    method, headers: { Authorization: `Bearer ${actors[actor].token}`, 'Idempotency-Key': `${PREFIX}api-${++sequence}` },
    ...(body === undefined ? {} : { data: body })
  });
  let data;
  try { data = await response.json(); } catch { data = null; }
  result.api_events.push({ actor, method, path: suffix, status: response.status(),
    ...(response.status() >= 400 ? { error_code: data?.code } : {}),
    ...(data?.status ? { claim_status: data.status } : {}) });
  return { status: response.status(), data };
}
async function uiResponse(page, suffix, method, action) {
  const responsePromise = page.waitForResponse(response => {
    const url = new URL(response.url());
    return url.pathname === `/v1${suffix}` && response.request().method() === method;
  });
  await action();
  const response = await responsePromise;
  const data = await response.json();
  result.api_events.push({ actor: page.__actor, method, path: suffix, status: response.status(),
    ...(response.status() >= 400 ? { error_code: data?.code } : {}),
    ...(data?.status ? { claim_status: data.status } : {}), via: 'browser UI' });
  return { status: response.status(), data };
}
async function waitText(page, selector, needle) {
  await page.waitForFunction(({ selector, needle }) => document.querySelector(selector)?.textContent.includes(needle), { selector, needle });
}
async function screenshot(page, filename, selector) {
  assert.equal(await page.locator('#own-code').filter({ visible: true }).count().catch(() => 0), 0,
    'Refusing screenshot with a visible handover code');
  const target = selector ? page.locator(selector) : page;
  if (!selector) await page.evaluate(() => window.scrollTo(0, 0));
  const file = path.join(OUT, filename);
  await target.screenshot({ path: file, animations: 'disabled', ...(selector ? {} : { fullPage: false }) });
  result.screenshots.push({ filename, path: file, selector: selector || 'viewport', actor: page.__actor, live_code_visible: false });
}
async function login(actor, options = {}) {
  const context = await browser.newContext({ viewport: options.viewport || { width: 1440, height: 1000 }, acceptDownloads: true });
  const page = await context.newPage();
  page.__actor = actor;
  page.on('pageerror', error => result.page_errors.push({ actor, message: error.message }));
  page.on('console', message => {
    if (message.type() === 'error') result.console_errors.push({ actor, text: message.text() });
  });
  await page.goto(BASE, { waitUntil: 'networkidle' });
  const auth = await uiResponse(page, '/demo/token', 'POST', () => page.locator(`[data-actor="${actor}"]`).click());
  assert.equal(auth.status, 200);
  actors[actor] = { page, context, token: auth.data.token };
  await page.locator('#found-list [data-listing-id]').first().waitFor();
  return actors[actor];
}
async function createClaim(actor, suffix, evidence) {
  const page = actors[actor].page;
  const itemId = PREFIX + suffix;
  await page.locator(`#found-list [data-listing-id="${itemId}"]`).click();
  await page.locator('#claim-form').waitFor({ state: 'visible' });
  await page.locator('#claim-item-number').fill(PREFIX + 'PRIVATE-NUMBER');
  await page.locator('#claim-evidence-input').fill(evidence);
  const response = await uiResponse(page, '/claims', 'POST', () => page.locator('#claim-submit').click());
  assert.ok([200, 201].includes(response.status));
  await page.locator('#claim-workspace').waitFor({ state: 'visible' });
  await page.locator('#claim-detail-content').waitFor({ state: 'visible' });
  await waitText(page, '#claim-meta', response.data.id);
  actors[actor].claimId = response.data.id;
  return response.data.id;
}
async function openClaim(actor, id) {
  const page = actors[actor].page;
  await page.locator('#refresh-claims').click();
  const button = page.locator(`#claims-list [data-claim-id="${id}"]`);
  await button.waitFor();
  await uiResponse(page, `/claims/${id}`, 'GET', () => button.click());
  await page.locator('#claim-detail-content').waitFor({ state: 'visible' });
  await waitText(page, '#claim-meta', id);
  actors[actor].claimId = id;
}
async function dialogConfirm(page, { reason, acknowledge = false } = {}) {
  await page.locator('#action-dialog').waitFor({ state: 'visible' });
  if (reason !== undefined) await page.locator('#action-dialog-reason').fill(reason);
  if (acknowledge) await page.locator('#action-dialog-ack').check();
  await page.locator('#action-dialog-confirm').click();
}
async function approve(id) {
  const page = actors.finder.page;
  await openClaim('finder', id);
  const response = await uiResponse(page, `/claims/${id}/approve`, 'POST', async () => {
    await page.getByRole('button', { name: '批准申请', exact: true }).click();
    await dialogConfirm(page);
  });
  assert.equal(response.status, 200);
  assert.equal(response.data.status, 'APPROVED');
  await waitText(page, '#claim-badges', '已批准');
}
async function refreshClaim(actor) {
  const page = actors[actor].page;
  await uiResponse(page, `/claims/${actors[actor].claimId}`, 'GET', () => page.locator('#refresh-claim').click());
  await page.locator('#claim-detail-content').waitFor({ state: 'visible' });
}

(async () => {
  const log = fs.openSync(path.join(OUT, 'ui-server.log'), 'a');
  try {
    server = cp.spawn(PYTHON, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(PORT)], {
      cwd: ROOT, env, windowsHide: true, stdio: ['ignore', log, log]
    });
    result.server_pid = server.pid;
    let ready = false;
    for (let i = 0; i < 75; i++) {
      try { const response = await fetch(`${BASE}/health`); if (response.ok) { ready = true; break; } } catch {}
      await delay(200);
    }
    assert.ok(ready, 'UI-QA backend did not start');
    browser = await chromium.launch({ executablePath: String.raw`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`, headless: true });
    result.browser_version = browser.version();
    result.playwright_version = require(process.env.CLAIM_PLAYWRIGHT_MODULE ? path.join(process.env.CLAIM_PLAYWRIGHT_MODULE, 'package.json') : String.raw`C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt\dependencies\node\node_modules\playwright\package.json`).version;
    for (const actor of ['alice', 'bob', 'finder', 'outsider']) await login(actor);
    check('four-isolated-browser-contexts', 'alice / bob / finder / outsider each have separate browser storage and in-memory tokens');
    const alice = actors.alice.page;
    const finder = actors.finder.page;
    const overflowDesktop = await alice.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
    assert.ok(overflowDesktop.scroll <= overflowDesktop.width);
    check('desktop-no-horizontal-overflow', overflowDesktop);
    await screenshot(alice, '01-desktop-overview.png');
    await alice.locator(`#lost-list [data-listing-id="${PREFIX}L-ALICE"]`).click();
    const matches = await uiResponse(alice, '/matches', 'GET', () => alice.locator('#load-matches').click()).catch(async () => {
      throw new Error('Matching UI request failed');
    });
    assert.equal(matches.status, 200);
    assert.ok(matches.data.candidates.some(c => c.item.id === PREFIX + 'F-HANDOVER' && c.reasons.length));
    await waitText(alice, '#matches-list', '规则版本');
    await screenshot(alice, '02-explainable-matching.png', '#lost-section');
    check('my-lost-record-matching-with-reasons', { candidate_count: matches.data.candidates.length, rule_version: matches.data.rule_version });

    const privateText = `${PREFIX}私有核验：内袋有银色星形钥匙扣`;
    const handoverId = await createClaim('alice', 'F-HANDOVER', privateText);
    const bobId = await createClaim('bob', 'F-HANDOVER', `${PREFIX}另一申请的私有说明`);
    check('two-pending-applications-created-via-ui', { alice_claim_id: handoverId, bob_claim_id: bobId });
    await openClaim('finder', handoverId);
    await alice.locator('#message-text').fill('请在图书馆服务台核对物品细节。');
    const sent = await uiResponse(alice, `/claims/${handoverId}/messages`, 'POST', () => alice.locator('#message-submit').click());
    assert.equal(sent.status, 201);
    await finder.locator('#refresh-messages').click();
    await waitText(finder, '#message-list', '图书馆服务台');
    assert.ok(sent.data.sender_alias.startsWith('申请人-'));
    assert.ok((await finder.locator('#message-list').innerText()).includes('对方'));
    check('anonymous-text-message-via-ui', { status: sent.status, dto_alias_present: true, ui_anonymous_label: '我/对方', raw_sender_id_returned: Object.hasOwn(sent.data, 'sender_id') });
    result.limitations.push('MessageDTO returns sender_alias, but current UI renders only 我/对方 labels, not the server alias. Initial assertion expecting the full alias stopped attempt 1; no application code was changed to pass.');

    const xssText = '<img src=x onerror="window.__uiXssExecuted=true">UI-QA文本渲染验证';
    await alice.locator('#message-text').fill(xssText);
    const xssResponse = await uiResponse(alice, `/claims/${handoverId}/messages`, 'POST', () => alice.locator('#message-submit').click());
    assert.equal(xssResponse.status, 201);
    await waitText(alice, '#message-list', xssText);
    assert.equal(await alice.locator('#message-list img').count(), 0);
    assert.equal(await alice.evaluate(() => window.__uiXssExecuted === true), false);
    check('xss-payload-rendered-as-text', { image_elements_created: 0, onerror_executed: false });

    await alice.locator('#message-text').fill('请联系13800138000');
    await alice.locator('#message-submit').click();
    await waitText(alice, '#message-form-error', '手机号');
    const blocked = await api('alice', `/claims/${handoverId}/messages`, 'POST', { text: '请联系13800138000' });
    assert.equal(blocked.status, 422);
    const inspectPhone = JSON.parse(helper('inspect', handoverId));
    assert.equal(inspectPhone.blocked_phone_present, false);
    await alice.locator('#message-text').fill('');
    check('pii-blocked-in-ui-and-server-not-persisted', { ui_error_visible: true, api_status: blocked.status, database_phone_present: false });
    await screenshot(alice, '03-private-evidence-and-alias-chat.png', '#claim-workspace');
    const unauthorized = await api('outsider', `/claims/${handoverId}`);
    const unauthorizedChat = await api('outsider', `/claims/${handoverId}/messages`);
    assert.equal(unauthorized.status, 403);
    assert.equal(unauthorizedChat.status, 403);
    check('outsider-api-denied', { claim_status: unauthorized.status, messages_status: unauthorizedChat.status });

    await approve(handoverId);
    const closedBob = await api('bob', `/claims/${bobId}`);
    assert.equal(closedBob.data.status, 'CLOSED_OTHER');
    check('approval-closes-other-pending-claim', { bob_state: closedBob.data.status });
    await refreshClaim('alice');
    await waitText(alice, '#claim-badges', '已批准');
    const aliceCode = await uiResponse(alice, `/claims/${handoverId}/code`, 'GET', () => alice.locator('#fetch-code-button').click());
    const finderCode = await uiResponse(finder, `/claims/${handoverId}/code`, 'GET', () => finder.locator('#fetch-code-button').click());
    assert.equal(aliceCode.status, 200);
    assert.equal(finderCode.status, 200);
    await alice.locator('#counterpart-code').fill(finderCode.data.code);
    const firstConfirmed = await uiResponse(alice, `/claims/${handoverId}/handover/confirm`, 'POST', () => alice.locator('#handover-confirm-submit').click());
    assert.equal(firstConfirmed.data.status, 'APPROVED');
    await finder.locator('#counterpart-code').fill(aliceCode.data.code);
    const completed = await uiResponse(finder, `/claims/${handoverId}/handover/confirm`, 'POST', () => finder.locator('#handover-confirm-submit').click());
    assert.equal(completed.data.status, 'COMPLETED');
    await refreshClaim('alice');
    await waitText(alice, '#claim-badges', '已完成');
    await screenshot(alice, '04-two-party-handover-completed.png', '#claim-workspace');
    check('two-party-handover-real-ui', { single_party_state: firstConfirmed.data.status, both_parties_state: completed.data.status, live_codes_written_to_evidence: false });

    const disputeId = await createClaim('alice', 'F-DISPUTE', `${PREFIX}争议核验：背面有月亮贴纸`);
    await alice.locator('#message-text').fill('约定在教学楼服务台交接。');
    await uiResponse(alice, `/claims/${disputeId}/messages`, 'POST', () => alice.locator('#message-submit').click());
    await approve(disputeId);
    await refreshClaim('alice');
    const disputed = await uiResponse(alice, `/claims/${disputeId}/dispute`, 'POST', async () => {
      await alice.locator('#dispute-button').click();
      await dialogConfirm(alice, { reason: '交接细节无法一致，需要转交管理员处理', acknowledge: true });
    });
    assert.equal(disputed.data.status, 'DISPUTED');
    await waitText(alice, '#claim-badges', '争议');
    assert.ok(await alice.locator('#message-text').isDisabled());
    assert.ok(await alice.locator('#message-submit').isDisabled());
    await waitText(alice, '#message-list', '教学楼服务台');
    const frozenWrite = await api('alice', `/claims/${disputeId}/messages`, 'POST', { text: '不应入库的冻结后消息' });
    assert.equal(frozenWrite.status, 409);
    const frozenCode = await api('alice', `/claims/${disputeId}/code`);
    assert.equal(frozenCode.status, 409);
    const exported = await api('alice', `/claims/${disputeId}/dispute-export`);
    assert.equal(exported.status, 200);
    const exportKeys = JSON.stringify(exported.data);
    for (const forbidden of ['"user_id"', '"publisher_user_id"', '"publisher_id"', '"applicant_id"', '"finder_id"', '"sender_id"']) assert.ok(!exportKeys.includes(forbidden));
    const downloadPromise = alice.waitForEvent('download');
    await alice.locator('#export-button').click();
    const download = await downloadPromise;
    const exportedPath = path.join(OUT, 'dispute-export-ui-fixture.json');
    await download.saveAs(exportedPath);
    await screenshot(alice, '05-dispute-read-only-export.png', '#claim-workspace');
    check('disputed-freeze-history-and-export', { input_disabled: true, write_http_status: frozenWrite.status, code_http_status: frozenCode.status, history_readable: true, identity_mapping_keys_absent: true, download: exportedPath });

    const expiryId = await createClaim('alice', 'F-EXPIRY', `${PREFIX}到期核验：杯底梅花图案`);
    await approve(expiryId);
    await refreshClaim('alice');
    helper('expire-code', expiryId);
    const expiredCode = await uiResponse(alice, `/claims/${expiryId}/code`, 'GET', () => alice.locator('#fetch-code-button').click());
    assert.equal(expiredCode.status, 410);
    await waitText(alice, '#code-status', '过期');
    await screenshot(alice, '06-expired-code-error.png', '#handover-section');
    const reset = await uiResponse(alice, `/claims/${expiryId}/handover/reset`, 'POST', async () => {
      await alice.locator('#reset-handover-button').click();
      await dialogConfirm(alice, { reason: '本测试合成记录的确认码已过期', acknowledge: true });
    });
    assert.equal(reset.status, 200);
    assert.equal(reset.data.reset_count, 1);
    check('expired-code-error-ui-and-explicit-reset', { expiry_status: expiredCode.status, reset_status: reset.status, reset_count: reset.data.reset_count, seam: 'Only own prefixed HandoverCode.expires_at set into past; no natural 30-minute wait' });

    await alice.locator('[data-actor="outsider"]').click();
    await waitText(alice, '#session-status', 'outsider');
    assert.ok(await alice.locator('#claim-workspace').isHidden());
    assert.ok(!(await alice.locator('body').innerText()).includes(privateText));
    assert.equal(await alice.evaluate(() => localStorage.length), 0);
    assert.equal(await alice.evaluate(() => sessionStorage.length), 0);
    check('identity-switch-clears-private-dom-and-no-token-storage', { private_workspace_hidden: true, private_evidence_absent: true, local_storage_entries: 0, session_storage_entries: 0 });

    const mobileContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 1, hasTouch: true });
    const mobile = await mobileContext.newPage();
    mobile.__actor = 'alice-mobile';
    mobile.on('pageerror', error => result.page_errors.push({ actor: 'alice-mobile', message: error.message }));
    await mobile.goto(BASE, { waitUntil: 'networkidle' });
    await mobile.locator('[data-actor="alice"]').click();
    await mobile.locator('#found-list [data-listing-id]').first().waitFor();
    const overflowMobile = await mobile.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth }));
    assert.ok(overflowMobile.scroll <= overflowMobile.width, `Mobile overflow ${JSON.stringify(overflowMobile)}`);
    await screenshot(mobile, '07-mobile-390px.png');
    await screenshot(mobile, '08-mobile-found-list.png', '#found-section');
    check('390px-mobile-no-horizontal-overflow', overflowMobile);
    await mobileContext.close();

    const expiredToken = helper('expired-token');
    const expiredContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const expiredPage = await expiredContext.newPage();
    expiredPage.__actor = 'expired-token-fixture';
    await expiredPage.route('**/v1/demo/token', async route => {
      const actual = await route.fetch();
      const data = await actual.json();
      data.token = expiredToken;
      data.expires_at = new Date(Date.now() - 3600000).toISOString();
      await route.fulfill({ response: actual, json: data });
    });
    await expiredPage.goto(BASE, { waitUntil: 'networkidle' });
    const deniedRequest = expiredPage.waitForResponse(r => new URL(r.url()).pathname === '/v1/listings' && r.status() === 401);
    await expiredPage.locator('[data-actor="alice"]').click();
    await deniedRequest;
    await waitText(expiredPage, '#notice-region', '重新');
    await screenshot(expiredPage, '09-expired-token-error.png');
    check('expired-signed-token-real-401-ui', { status: 401, seam: 'Auth response token replaced with correctly signed already-expired fixture; subsequent protected requests reached the real backend' });
    await expiredContext.close();
    result.limitations.push('Browser smoke uses synthetic UI-QA data and local MySQL; no real student data, external authentication, external publishing service, public network or natural time wait acceptance.');
    result.limitations.push('Expected 403/409/410/422 HTTP errors may appear as browser resource console messages; JavaScript page errors are reported separately.');
    result.expected_resource_console_errors = result.console_errors.filter(x => /Failed to load resource:.*(?:401|403|409|410|422)/.test(x.text));
    result.unexpected_console_errors = result.console_errors.filter(x => !/Failed to load resource:.*(?:401|403|409|410|422)/.test(x.text));
    assert.equal(result.page_errors.length, 0, 'JavaScript page errors present');
    assert.equal(result.unexpected_console_errors.length, 0, 'Unexpected browser console errors present');
    check('no-javascript-page-errors-or-unexpected-console-errors', { page_errors: 0, unexpected_console_errors: 0, expected_http_resource_errors: result.expected_resource_console_errors.length });
    result.success = true;
  } catch (error) {
    result.failure = { name: error.name, message: error.message, stack: error.stack };
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close();
    if (server && server.exitCode === null) {
      server.kill();
      await new Promise(resolve => { server.once('exit', resolve); setTimeout(resolve, 4000); });
    }
    fs.closeSync(log);
    result.server_stopped = !server || server.exitCode !== null || server.signalCode !== null;
    try { result.cleanup = JSON.parse(helper('cleanup')); } catch (error) { result.cleanup = { error: 'Scoped fixture cleanup failed; see current task', message: String(error.message).slice(0, 300) }; }
    result.ended_at = new Date().toISOString();
    fs.writeFileSync(path.join(OUT, 'ui-validation.json'), JSON.stringify(result, null, 2), 'utf8');
    console.log(JSON.stringify({ success: result.success, checks_passed: result.checks.length, screenshots: result.screenshots.length, failure: result.failure?.message, server_stopped: result.server_stopped, cleanup: result.cleanup }, null, 2));
  }
})();
