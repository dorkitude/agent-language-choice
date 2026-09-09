const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const path=require('node:path');
const os=require('node:os');
const fs=require('node:fs');
const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'alc-dashboard-check-'));
if(!process.argv[2])throw new Error('Usage: node verify_report.cjs /path/to/report.html');
(async()=>{const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[],network=[];
page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))network.push(r.url())});await page.context().setOffline(true);
await page.goto(pathToFileURL(path.resolve(process.argv[2])).href);
assert.equal(await page.locator('#matrix button').count(),85);assert.equal(await page.evaluate(()=>Object.keys(Chart.instances).length),3);assert.equal(await page.evaluate(()=>JSON.parse(document.querySelector('#experiment-data').textContent).cells.length),85);
await page.selectOption('#model','gpt-5.6-terra');assert.equal(await page.locator('#matrix button').count(),17);
await page.selectOption('#target','rust-stdlib');assert.equal(await page.locator('#matrix button').count(),1);await page.locator('#matrix button').click();assert.match(await page.locator('#detailMeta').innerText(),/100\/100/);
const downloadEvent=page.waitForEvent('download');await page.click('#download');const download=await downloadEvent;await download.saveAs(path.join(scratch,'download.json'));assert.equal(JSON.parse(fs.readFileSync(path.join(scratch,'download.json'),'utf8')).cells.length,85);
await page.selectOption('#model','all');await page.selectOption('#target','all');await page.screenshot({path:path.join(scratch,'desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:844});await page.waitForTimeout(250);await page.screenshot({path:path.join(scratch,'mobile.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
assert.deepEqual(errors,[]);assert.deepEqual(network,[]);console.log(JSON.stringify({cells:85,charts:3,offline:true,filter:true,download:true,mobileOverflow:false,errors},null,2));await browser.close()})().catch(e=>{console.error(e);process.exit(1)})
