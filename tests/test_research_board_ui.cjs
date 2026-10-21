// Browser regression fixture; no installed services, bots, or models are contacted.
const {chromium}=require('playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const assets=path.resolve(__dirname,'../team/shared/board-ui');
const tasks=['t-author','t-librarian','t-experimenter','t-reviewer'].map((id,i)=>({id,assignee:['research-lead','research-librarian','research-experimenter','research-reviewer'][i],status:'done',column:'done',after:[],outputs:[{path:'notes/example.md',available:true}],attempt:'1',report:'Saved test output.'}));
const projects=[{id:'reports',name:'reports',test:false,tasks:[]},
 {id:'old',name:'_selftest-20261021-233702',test:true,tasks,check:{outcome:'incomplete',phase:'설치 확인이 중단되었습니다.'}},
 {id:'new',name:'_selftest-20261022-001122',test:true,tasks,check:{outcome:'passed',phase:'최종 설치 검증을 통과했습니다.'}}];
const server=http.createServer((req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(u.pathname==='/api/projects'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({projects:projects.filter(p=>u.searchParams.get('tests')==='1'||!p.test),workspace:'Fixture workspace',updated:new Date().toISOString(),service:{updated:new Date().toISOString(),children:[{state:'running'}]}}));}
 if(u.pathname==='/api/output')return res.end('Example output preview');
 const name={'/':'index.html','/app.js':'app.js','/app.css':'app.css'}[u.pathname];
 if(!name){res.statusCode=404;return res.end();}
 res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(path.join(assets,name)));
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const base=`http://127.0.0.1:${server.address().port}/`;
  await page.goto(base+'?view=checks&project=_selftest-20261021-233702');
  await page.waitForFunction(()=>document.querySelectorAll('.card').length===4);
  assert.match(await page.locator('#name').innerText(),/2026-10-21 23:37:02/);
  assert.match(await page.locator('#banner').innerText(),/설치 확인 미완료/);
  assert.match(await page.locator('[data-status=done] h3').innerText(),/4/);
  await page.locator('.card').first().click();await page.locator('#outputs button').click();
  await page.waitForFunction(()=>document.querySelector('#preview').textContent==='Example output preview');
  await page.locator('#close').click();
  await page.locator('#research-view').click();await page.waitForFunction(()=>document.querySelector('#name').textContent==='reports');
  assert.equal(await page.locator('.card').count(),0);
  await page.locator('#checks-view').click();await page.waitForFunction(()=>document.querySelector('#name').textContent.includes('2026-10-22'));
  assert.match(await page.locator('#banner').innerText(),/설치 확인 통과/);
  await page.locator('#projects button').last().click();await page.reload();await page.waitForFunction(()=>document.querySelector('#name').textContent.includes('2026-10-21'));
  if(process.env.BOARD_SCREENSHOT)await page.screenshot({path:process.env.BOARD_SCREENSHOT,fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.locator('.card').count(),4);
  await page.goto(base+'?view=checks&project=_selftest-20990101-000000');
  await page.waitForFunction(()=>document.querySelector('#name').textContent==='Requested project is not available yet');
  assert.equal(await page.locator('.card').count(),0);
  assert.deepEqual(errors,[]);
  console.log('PASS: exact test links, separate sections, latest check, incomplete vs done, persistent selection, outputs, mobile, missing project, no JavaScript errors');
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);server.close();process.exitCode=1;});
