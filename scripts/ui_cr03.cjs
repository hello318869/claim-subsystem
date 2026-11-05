/* CR-03 real-browser read/pagination/privacy regression only.
 * Starts its own dev server on 18082. Fixtures are unique UI-QA rows in claim_dev.
 * Reads .env only through app configuration; never writes tokens or live codes.
 */
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.CLAIM_PLAYWRIGHT_MODULE || String.raw`C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1030-493-0_26.1030.493.0_x64__3k8sg7r9htsxt\dependencies\node\node_modules\playwright`);
const ROOT = path.resolve(__dirname, '..');
const PYTHON = process.env.CLAIM_PYTHON || String.raw`C:\Users\asus\AppData\Local\Programs\Python\Python311\python.exe`;
const PREFIX = process.env.CLAIM_UI_PREFIX || `UI-QA-CR03-${Date.now()}-`;
const ONLY_CASE = process.env.CLAIM_UI_CASE || null;
const PORT = 18082;
const BASE = `http://127.0.0.1:${PORT}`;
const OUT = path.join(ROOT, 'evidence', 'ui-cr03');
const env = { ...process.env, APP_ENV: 'dev' }; delete env.DATABASE_URL;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return {promise,resolve}; };
fs.mkdirSync(OUT, {recursive:true});
const report = { started_at:new Date().toISOString(), fixture_prefix:PREFIX, database:'claim_dev', mysql_port:33307,
  app_port:PORT, real_http:true, only_case:ONLY_CASE, tests:[], screenshots:[], api_events:[], console_events:[], page_errors:[],
  request_failures:[], favicon_requests:[], limitations:[], success:false };
let server, browser, phase='setup', created=false, sequence=0;
const tokens={};
function helper(action) {
  return JSON.parse(cp.execFileSync(PYTHON,[path.join(ROOT,'scripts','ui_fixture.py'),action,'--prefix',PREFIX],{cwd:ROOT,env,windowsHide:true,encoding:'utf8'}));
}
async function api(actor,suffix,method='GET',body) {
  const response=await fetch(`${BASE}/v1${suffix}`,{method,headers:{Authorization:`Bearer ${tokens[actor]}`,'Content-Type':'application/json','Idempotency-Key':`${PREFIX}${++sequence}`},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data=await response.json();
  report.api_events.push({actor,method,path:suffix,status:response.status,...(Number.isFinite(data.total)?{total:data.total}:{}),...(data.id?{resource_id:data.id}:{}),...(response.status>=400?{error_code:data.code}:{})});
  return {status:response.status,data};
}
async function allClaims(actor,role) {
  const items=[];let total=0;
  for(let page=1;page<=100;page++) {
    const r=await api(actor,`/claims?role=${role}&page=${page}&page_size=100`);assert.equal(r.status,200);
    items.push(...r.data.items);total=r.data.total;if(items.length>=total)break;
  }
  assert.equal(items.length,total);return {items,total};
}
async function test(id,name,fn) {
  if(ONLY_CASE && ONLY_CASE!==id)return;
  phase=id;
  try { const detail=await fn();report.tests.push({id,name,passed:true,detail}); }
  catch(error) { report.tests.push({id,name,passed:false,error:error.message,stack:error.stack}); }
}
function observe(page,label) {
  page.on('console',message=>{if(message.type()==='error')report.console_events.push({phase,context:label,text:message.text()});});
  page.on('pageerror',error=>report.page_errors.push({phase,context:label,message:error.message}));
  page.on('requestfailed',request=>report.request_failures.push({phase,context:label,path:new URL(request.url()).pathname,error:request.failure()?.errorText}));
  page.on('request',request=>{if(new URL(request.url()).pathname==='/favicon.ico')report.favicon_requests.push({phase,context:label});});
}
async function countsReady(page) {
  await page.waitForFunction(()=>['applicant','finder'].every(role=>document.getElementById(`claims-count-${role}`).dataset.countState==='ready'));
}
async function visibleCounts(page) {
  return page.evaluate(()=>Object.fromEntries(['applicant','finder'].map(role=>[role,{text:document.getElementById(`claims-count-${role}`).textContent,state:document.getElementById(`claims-count-${role}`).dataset.countState}])));
}
async function listIds(page) {return page.locator('#claims-list [data-claim-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.claimId));}
async function group(page,role) {
  await page.locator(`#claims-filter-${role}`).click();
  await page.waitForFunction(role=>document.getElementById(`claims-filter-${role}`).getAttribute('aria-pressed')==='true',role);
  await page.waitForFunction(()=>document.getElementById('claims-list').getAttribute('aria-busy')==='false');
}
async function screenshot(page,name) {
  await page.evaluate(()=>{document.activeElement?.blur();document.getElementById('claims-section').scrollIntoView({behavior:'instant',block:'start'});});
  const file=path.join(OUT,name);await page.screenshot({path:file,animations:'disabled'});
  report.screenshots.push({filename:name,path:file,scope:'actual claims group panel viewport; no handover codes fetched'});
}
async function chooseIdentity(page,actor) {
  await page.locator(`[data-actor="${actor}"]`).click();
  await page.waitForFunction(actor=>document.getElementById('session-status').textContent.includes(`当前演示身份：${actor}`),actor);
  await countsReady(page);
  await page.waitForFunction(()=>document.getElementById('claims-list').getAttribute('aria-busy')==='false');
}

(async()=>{
  const fd=fs.openSync(path.join(OUT,'server.log'),'a');
  const files=['web/index.html','web/app.js','web/styles.css'];
  report.source_sha256=Object.fromEntries(files.map(file=>[file,sha(fs.readFileSync(path.join(ROOT,file)))]));
  try {
    const seed=helper('seed-cr03');created=true;report.fixture_seed=seed;
    server=cp.spawn(PYTHON,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port',String(PORT)],{cwd:ROOT,env,windowsHide:true,stdio:['ignore',fd,fd]});
    report.server_pid=server.pid;
    let ready=false;
    for(let i=0;i<75;i++){try{const r=await fetch(`${BASE}/health`);if(r.ok){ready=true;break;}}catch{}await delay(200);}
    await delay(100);assert.ok(ready&&server.exitCode===null,'Dedicated dev server did not start');
    for(const actor of ['alice','bob','finder','outsider']) {
      const r=await fetch(`${BASE}/v1/demo/token`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor})});
      assert.equal(r.status,200);tokens[actor]=(await r.json()).token;
    }
    report.fixture_claims=[];
    for(let i=1;i<=23;i++) {
      const r=await api('alice','/claims','POST',{item_id:`${PREFIX}F-PAGE-${String(i).padStart(2,'0')}`,evidence_text:`${PREFIX}分页验证私有证据 ${i}`});
      assert.equal(r.status,201);report.fixture_claims.push({actor:'alice',claim_id:r.data.id,item_id:r.data.item_id});
    }
    for(const suffix of ['F-OWN-01','F-OWN-02','F-BOB-EXTRA']) {
      const r=await api('bob','/claims','POST',{item_id:PREFIX+suffix,evidence_text:`${PREFIX}Bob分组验证`});assert.equal(r.status,201);
      report.fixture_claims.push({actor:'bob',claim_id:r.data.id,item_id:r.data.item_id});
    }
    report.fixture_note='26 listing snapshots seeded; all 26 claims were created through real POST /v1/claims, not inserted or edited to fabricate counts.';
    const truth={};for(const actor of ['alice','bob','outsider']){truth[actor]={};for(const role of ['applicant','finder','all'])truth[actor][role]=await allClaims(actor,role);}
    browser=await chromium.launch({executablePath:String.raw`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`,headless:true});
    report.browser_version=browser.version();
    const context=await browser.newContext({viewport:{width:1440,height:1050}});const page=await context.newPage();observe(page,'desktop');
    await page.goto(BASE,{waitUntil:'networkidle'});await chooseIdentity(page,'alice');
    await test('RG-01','默认分组',async()=>{
      assert.equal(await page.locator('#claims-filter-applicant').getAttribute('aria-pressed'),'true');
      const ids=await listIds(page);const expected=truth.alice.applicant.items.slice(0,20).map(x=>x.id);assert.deepEqual(ids,expected);
      await screenshot(page,'01-default-applicant-group.png');return {active_group:'applicant',first_page_ids_match_api:true};
    });
    await test('RG-02','两组计数准确',async()=>{
      const counts=await visibleCounts(page);assert.equal(Number(counts.applicant.text),truth.alice.applicant.total);assert.equal(Number(counts.finder.text),truth.alice.finder.total);
      return {ui:counts,api:{applicant:truth.alice.applicant.total,finder:truth.alice.finder.total}};
    });
    await test('RG-03','快速切组与迟到响应隔离',async()=>{
      for(let i=0;i<3;i++){await page.locator('#claims-filter-finder').click();await page.locator('#claims-filter-applicant').click();}
      await group(page,'finder');
      const readyGate=deferred(),release=deferred(),done=deferred();let held=false;
      const pattern='**/v1/claims?**';
      const handler=async route=>{const u=new URL(route.request().url());const r=await route.fetch();if(!held&&u.searchParams.get('role')==='applicant'&&u.searchParams.get('page_size')==='20'){held=true;readyGate.resolve();await release.promise;try{await route.fulfill({response:r});}finally{done.resolve();}}else await route.fulfill({response:r});};
      await page.route(pattern,handler);
      try {
        await page.locator('#claims-filter-applicant').click();await readyGate.promise;
        await group(page,'finder');const before=await listIds(page);release.resolve();await done.promise;await delay(200);
        assert.equal(await page.locator('#claims-filter-finder').getAttribute('aria-pressed'),'true');
        assert.deepEqual(await listIds(page),truth.alice.finder.items.map(x=>x.id));assert.deepEqual(await listIds(page),before);
      } finally {release.resolve();await page.unroute(pattern,handler);}
      return {quick_round_trips:3,delayed_real_applicant_response_did_not_overwrite_finder:true};
    });
    await test('RG-04','分页与切组重置',async()=>{
      await group(page,'applicant');assert.ok(truth.alice.applicant.total>20);await page.locator('#claims-next').click();
      await page.waitForFunction(()=>document.getElementById('claims-page-status').textContent.startsWith('第 2 页'));
      assert.deepEqual(await listIds(page),truth.alice.applicant.items.slice(20,40).map(x=>x.id));
      await group(page,'finder');assert.ok((await page.locator('#claims-page-status').innerText()).startsWith('第 1 页'));
      await screenshot(page,'02-finder-group.png');return {applicant_total:truth.alice.applicant.total,page_two_exact:true,switch_resets_page:1};
    });
    await test('RG-05','空组说明',async()=>{
      assert.equal(truth.outsider.all.total,0,'Existing outsider data prevents the intended empty-fixture scenario');await chooseIdentity(page,'outsider');
      assert.ok((await page.locator('#claims-list').innerText()).includes('暂无我发起的申请'));await group(page,'finder');
      assert.ok((await page.locator('#claims-list').innerText()).includes('暂无我收到的申请'));assert.equal((await visibleCounts(page)).finder.text,'0');
      await screenshot(page,'03-empty-group.png');return {actual_api_total:0,explicit_empty_states:true,zero_only_after_successful_total:true};
    });
    await test('RG-06','身份变化清空计数和私有内容',async()=>{
      await chooseIdentity(page,'alice');await group(page,'applicant');await page.locator(`#claims-list [data-claim-id="${truth.alice.applicant.items[0].id}"]`).click();
      await page.locator('#claim-detail-content').waitFor({state:'visible'});
      const gate=deferred(),release=deferred();let held=false;const pattern='**/v1/demo/token';
      const handler=async route=>{const r=await route.fetch();if(!held){held=true;gate.resolve();await release.promise;}await route.fulfill({response:r});};
      await page.route(pattern,handler);
      try {
        await page.locator('[data-actor="bob"]').click();await gate.promise;
        const immediate=await visibleCounts(page);assert.equal(immediate.applicant.text,'—');assert.equal(immediate.finder.text,'—');assert.ok(await page.locator('#claim-workspace').isHidden());
        assert.ok(!(await page.locator('#claims-list').innerText()).includes(PREFIX));release.resolve();
        await page.waitForFunction(()=>document.getElementById('session-status').textContent.includes('当前演示身份：bob'));await countsReady(page);
        await page.waitForFunction(()=>document.getElementById('claims-list').getAttribute('aria-busy')==='false');
        const counts=await visibleCounts(page);assert.equal(Number(counts.applicant.text),truth.bob.applicant.total);assert.equal(Number(counts.finder.text),truth.bob.finder.total);
      }finally{release.resolve();await page.unroute(pattern,handler);}
      await chooseIdentity(page,'outsider');assert.deepEqual(await listIds(page),[]);return {identity_sequence:['alice','bob','outsider'],immediate_counts:'—',private_workspace_hidden:true};
    });
    await test('RG-07','第三方无详情或消息权限',async()=>{
      const claimId=report.fixture_claims[0].claim_id;const detail=await api('outsider',`/claims/${claimId}`);const messages=await api('outsider',`/claims/${claimId}/messages`);
      assert.equal(detail.status,403);assert.equal(messages.status,403);assert.equal(truth.outsider.all.total,0);assert.deepEqual(await listIds(page),[]);
      return {detail_http:403,messages_http:403,outsider_list_total:0};
    });
    await test('RG-08','界面无混合入口且all兼容',async()=>{
      const roles=await page.locator('#claims-filters [data-claim-role]').evaluateAll(nodes=>nodes.map(n=>n.dataset.claimRole));assert.deepEqual(roles,['applicant','finder']);
      const all=await api('alice','/claims?role=all&page=1&page_size=100');assert.equal(all.status,200);
      const ownSet=new Set(truth.alice.all.items.map(x=>x.id));assert.ok(all.data.items.every(x=>ownSet.has(x.id)));
      return {ui_roles:roles,all_http:200,all_contains_only_related_ids:true};
    });
    await test('RG-09','计数失败占位与恢复',async()=>{
      await chooseIdentity(page,'alice');const pattern='**/v1/claims?**';const blocker=route=>route.abort('internetdisconnected');await page.route(pattern,blocker);
      const observations={};
      try {
        await group(page,'finder');await page.waitForFunction(()=>document.getElementById('claims-list').textContent.includes('加载失败'));
        observations.after_failed_switch=await visibleCounts(page);
        await page.locator('#refresh-claims').click();
        await page.waitForFunction(()=>['applicant','finder'].every(role=>document.getElementById(`claims-count-${role}`).textContent==='—'),null,{timeout:10000});
        observations.after_failed_refresh=await visibleCounts(page);
        observations.failure_list_text=await page.locator('#claims-list').innerText();
        await screenshot(page,'04-count-unavailable-error.png');
      }finally{await page.unroute(pattern,blocker);}
      const recoveryArrived=deferred(),releaseRecovery=deferred(),recoveryDone=deferred();const recoveryRequests=[];let completedRecovery=0;
      const recoveryHandler=async route=>{const u=new URL(route.request().url());const actual=await route.fetch();recoveryRequests.push({role:u.searchParams.get('role'),page:u.searchParams.get('page'),page_size:u.searchParams.get('page_size'),status:actual.status()});if(recoveryRequests.length>=3)recoveryArrived.resolve();await releaseRecovery.promise;await route.fulfill({response:actual});completedRecovery+=1;if(completedRecovery>=3)recoveryDone.resolve();};
      await page.route(pattern,recoveryHandler);const recoveryStart=Date.now();
      try {
        await page.evaluate(()=>{for(let i=0;i<5;i++)window.dispatchEvent(new Event('online'));});
        await Promise.race([recoveryArrived.promise,delay(10000).then(()=>{throw new Error('Online recovery did not issue the expected genuine HTTP requests within 10s');})]);
        assert.equal(recoveryRequests.length,3,'Repeated online events duplicated the in-flight refresh');
        releaseRecovery.resolve();await recoveryDone.promise;
        await page.waitForFunction(()=>['applicant','finder'].every(role=>document.getElementById(`claims-count-${role}`).dataset.countState==='ready'),null,{timeout:10000});
        await page.waitForFunction(()=>document.getElementById('claims-list').getAttribute('aria-busy')==='false',null,{timeout:10000});
        observations.after_restore_without_click=await visibleCounts(page);observations.automatic_recovery=true;
        observations.recovery_elapsed_ms=Date.now()-recoveryStart;observations.online_events_dispatched=5;observations.recovery_requests=recoveryRequests;
      } finally {releaseRecovery.resolve();await page.unroute(pattern,recoveryHandler);}
      report.rg09_observations=observations;
      assert.equal(observations.after_failed_refresh.applicant.text,'—','Failed refresh applicant count must be unavailable');assert.equal(observations.after_failed_refresh.finder.text,'—','Failed refresh finder count must be unavailable');
      assert.equal(observations.after_failed_switch.finder.text,'—','After switching while requests fail, previous ready count is still presented instead of unavailable');
      assert.ok(observations.automatic_recovery,'Restoring connectivity requires explicit refresh; no automatic recovery was observed');
      assert.equal(Number(observations.after_restore_without_click.applicant.text),truth.alice.applicant.total);assert.equal(Number(observations.after_restore_without_click.finder.text),truth.alice.finder.total);
      await screenshot(page,'07-online-recovered-counts.png');
      const fallbackContext=await browser.newContext({viewport:{width:1440,height:1050}});const fallbackPage=await fallbackContext.newPage();observe(fallbackPage,'valid-total-fallback');
      const countBlocker=route=>{const u=new URL(route.request().url());return u.searchParams.get('page_size')==='1'?route.abort('internetdisconnected'):route.continue();};
      await fallbackPage.route(pattern,countBlocker);await fallbackPage.goto(BASE,{waitUntil:'networkidle'});await fallbackPage.locator('[data-actor="alice"]').click();
      await fallbackPage.waitForFunction(()=>document.getElementById('claims-list').getAttribute('aria-busy')==='false'&&document.getElementById('claims-count-applicant').dataset.countState==='ready'&&document.getElementById('claims-count-finder').textContent==='—',null,{timeout:10000});
      observations.valid_list_total_fallback=await visibleCounts(fallbackPage);assert.equal(Number(observations.valid_list_total_fallback.applicant.text),truth.alice.applicant.total);assert.equal(observations.valid_list_total_fallback.finder.text,'—');
      await screenshot(fallbackPage,'08-valid-list-total-fallback.png');
      await fallbackPage.unroute(pattern,countBlocker);await fallbackPage.evaluate(()=>window.dispatchEvent(new Event('online')));
      await fallbackPage.waitForFunction(()=>['applicant','finder'].every(role=>document.getElementById(`claims-count-${role}`).dataset.countState==='ready'),null,{timeout:10000});
      observations.fallback_after_online=await visibleCounts(fallbackPage);assert.equal(Number(observations.fallback_after_online.finder.text),truth.alice.finder.total);await fallbackContext.close();
      return observations;
    });
    await test('RG-10','两组不重叠且并集等于all',async()=>{
      const a=truth.alice.applicant.items.map(x=>x.id),f=truth.alice.finder.items.map(x=>x.id),all=truth.alice.all.items.map(x=>x.id);
      const union=[...new Set([...a,...f])];assert.equal(a.filter(x=>f.includes(x)).length,0);assert.deepEqual([...union].sort(),[...all].sort());
      return {applicant:a.length,finder:f.length,intersection:0,union:union.length,all:all.length};
    });
    if(!ONLY_CASE||ONLY_CASE==='SCREENSHOTS'){phase='mobile';const mobileContext=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});const mobile=await mobileContext.newPage();observe(mobile,'mobile');
    await mobile.goto(BASE,{waitUntil:'networkidle'});await chooseIdentity(mobile,'alice');
    const size=await mobile.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));assert.ok(size.document<=size.viewport);
    await screenshot(mobile,'05-mobile-390-group.png');report.mobile={passed:true,...size};await mobileContext.close();}
    phase='final-clean-page';const finalContext=await browser.newContext({viewport:{width:1440,height:1050}});const finalPage=await finalContext.newPage();observe(finalPage,'final-clean-page');
    await finalPage.goto(BASE,{waitUntil:'networkidle'});await chooseIdentity(finalPage,'alice');await screenshot(finalPage,'06-final-group-overview.png');
    report.final_clean_page={console_errors:report.console_events.filter(x=>x.context==='final-clean-page').length,page_errors:report.page_errors.filter(x=>x.context==='final-clean-page').length,favicon_requests:report.favicon_requests.filter(x=>x.context==='final-clean-page').length};
    assert.deepEqual(report.final_clean_page,{console_errors:0,page_errors:0,favicon_requests:0});
    const failures=report.console_events.filter(x=>x.phase!=='RG-09');report.unexpected_console_errors=failures;assert.equal(failures.length,0);assert.equal(report.page_errors.length,0);
    report.source_unchanged=files.every(file=>report.source_sha256[file]===sha(fs.readFileSync(path.join(ROOT,file))));assert.ok(report.source_unchanged);
    report.limitations.push('Only grouping/read/pagination/privacy/failure handling was rechecked; the prior 15 core-write UI scenarios were not repeated.');
    report.limitations.push('RG-03 delays genuine HTTP responses without changing business payloads; RG-06 delays the genuine token response; RG-09 injects browser network failures and then an online event.');
    report.success=report.tests.length===(ONLY_CASE==='SCREENSHOTS'?0:ONLY_CASE?1:10)&&report.tests.every(t=>t.passed);
    if(!report.success)process.exitCode=1;
    await finalContext.close();await context.close();
  }catch(error){report.fatal_error={name:error.name,message:error.message};process.exitCode=1;}
  finally {
    if(browser)await browser.close();
    if(server&&server.exitCode===null){server.kill();await new Promise(resolve=>{server.once('exit',resolve);setTimeout(resolve,4000);});}
    fs.closeSync(fd);report.server_stopped=!server||server.exitCode!==null||server.signalCode!==null;
    if(created){try{report.cleanup=helper('cleanup');}catch(error){report.cleanup={error:String(error.message).slice(0,300)};}}
    report.ended_at=new Date().toISOString();
    fs.writeFileSync(path.join(ROOT,'evidence','ui-cr03-validation.json'),JSON.stringify(report,null,2),'utf8');
    console.log(JSON.stringify({success:report.success,tests:report.tests.map(t=>({id:t.id,passed:t.passed,error:t.error})),fatal_error:report.fatal_error,final_clean_page:report.final_clean_page,screenshots:report.screenshots.length,server_stopped:report.server_stopped,cleanup:report.cleanup},null,2));
  }
})();
