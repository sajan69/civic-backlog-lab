const {chromium}=require('playwright');
const {spawn}=require('node:child_process');
const {once}=require('node:events');
const readline=require('node:readline');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
(async()=>{
 const child=spawn(process.env.PYTHON_EXECUTABLE||'python',['tests/browser/server.py'],{stdio:['ignore','pipe','pipe']});
 let stderr=''; child.stderr.on('data',data=>stderr+=data);
 const lines=readline.createInterface({input:child.stdout});
 const timeout=setTimeout(()=>{console.error('Server startup timed out',stderr);child.kill();process.exit(1)},20000);
 let browser;
 try{
  const [url]=await Promise.race([once(lines,'line'),once(child,'exit').then(()=>{throw new Error(stderr)})]);clearTimeout(timeout);
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE,args:['--no-sandbox','--disable-dev-shm-usage','--disable-gpu']}: {})});
  const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',()=>errors.push('Unexpected script dialog'));
  await page.goto(url);await page.locator('#report').waitFor({state:'visible'});
  assert.match(await page.locator('#fraction').innerText(),/40.0%/);
  await page.selectOption('#horizon','30');assert.match(await page.locator('#fraction').innerText(),/66.7%/);
  assert.match(await page.locator('#denominator').innerText(),/2 closed within 30 days \/ 3 eligible/);
  await page.fill('#agency','nypd');assert.equal(await page.locator('#agencies tr').count(),1);
  await page.fill('#agency','no such agency');assert.equal(await page.locator('#agencies tr').count(),0);
  await page.fill('#agency','');assert.equal(await page.locator('#agencies img').count(),0);
  assert.match(await page.locator('#agencies').innerText(),/<IMG SRC=X ONERROR=ALERT\(1\)>/);
  for(const format of ['json','csv']){
   const pending=page.waitForEvent('download');await page.click('#'+format);const download=await pending;
   const content=await fs.readFile(await download.path(),'utf8');
   if(format==='json') assert.equal(JSON.parse(content).summary.cohort_rows,12);
   else assert.match(content,/'=SUM\(1,1\)/);
  }
  await page.click('summary');assert.equal(await page.locator('#provenance').isVisible(),true);
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await fs.mkdir('artifacts',{recursive:true});await page.screenshot({path:'artifacts/dashboard-mobile.png',fullPage:true});
  await page.setViewportSize({width:1280,height:900});await page.screenshot({path:'artifacts/dashboard.png',fullPage:true});
  assert.equal(await page.evaluate(()=>location.hash),'');
  await page.reload();assert.match(await page.locator('#message').innerText(),/Reopen/);
  assert.deepEqual(errors,[]);console.log('Browser checks passed: horizons, filters, safe labels, downloads, provenance, mobile and token lifecycle.');
 }finally{clearTimeout(timeout);if(browser)await browser.close();lines.close();child.kill();}
})().catch(error=>{console.error(error);process.exitCode=1});
