/* W20 parent real-browser gate. Existing Puppeteer conventions, no installs.
 * PUPPETEER_MODULE=... BROWSER_EXECUTABLE=... node tests/browser/w20_intake_contract.cjs BASE_URL OUTPUT_JSON
 * GETs intercepted; POSTs recorded and never reach backend. 390px and desktop.
 */
const assert=require('node:assert/strict'),fs=require('node:fs');
const puppeteer=require(process.env.PUPPETEER_MODULE||'puppeteer');
const [base,output]=process.argv.slice(2);
const report={passed:false,cases:[],errors:[]};
(async()=>{const browser=await puppeteer.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE,args:['--no-sandbox']});
try{for(const file of ['index.html','driver-filing.html'])for(const width of [390,1280])for(const category of [0,1]){
const page=await browser.newPage(),posts=[];page.on('pageerror',e=>report.errors.push(String(e)));
await page.setViewport({width,height:844});await page.setRequestInterception(true);
page.on('request',r=>{if(r.url().includes('/api/trips'))return r.respond({status:200,contentType:'application/json',body:JSON.stringify({trips:['A','B'].map(trip_id=>({trip_id,label:trip_id}))})});if(r.method()==='POST'){posts.push(JSON.parse(r.postData()));return r.respond({status:400,contentType:'application/json',body:JSON.stringify({error:'instrument refusal'})});}return r.continue();});
await page.goto(base+'/party/'+file,{waitUntil:'networkidle0'});
await page.evaluate(i=>document.querySelectorAll('#category-options button')[i].click(),category);await page.click('#category-next');await page.waitForSelector('#trip-options .trip-card');await page.click('#trip-options .trip-card');await page.click('#trip-next');
const snapshot=()=>page.evaluate(()=>({trip:[...document.querySelectorAll('#trip-options .selected')].map(n=>n.textContent),rows:[...document.querySelectorAll('#question-list textarea')].map(n=>({value:n.value,hidden:n.hidden})),choices:[...document.querySelectorAll('#question-list .choice-button')].map(n=>({selected:n.classList.contains('selected'),pressed:n.getAttribute('aria-pressed')})),description:document.getElementById('description').value,amount:document.getElementById('claim-amount').value}));
await page.evaluate(()=>{document.getElementById('description').value='kept';document.getElementById('claim-amount').value='12.34';document.querySelectorAll('#question-list .choice-options').forEach((n,i)=>n.children[i%2].click());document.querySelectorAll('#question-list textarea').forEach(n=>n.value='kept 😀 '+n.getAttribute('data-elaborate-for'));});
const initial=await snapshot();for(let n=0;n<3;n++){await page.click('#details-back');await page.waitForSelector('#trip-options .selected');await page.click('#trip-next');assert.deepEqual(await snapshot(),initial,'Back/Continue lost draft');}
for(const selector of ['textarea[data-question-key]','textarea[data-elaborate-for]'])for(const n of [1999,2000,2001]){
await page.evaluate(({selector,n})=>{document.querySelectorAll('#question-list textarea').forEach(e=>e.value='kept');const e=document.querySelector('#question-list '+selector);e.value='😀'.repeat(selector.includes('elaborate')?n-6:n);if(selector.includes('elaborate'))document.querySelector('.choice-button[data-question-key="'+e.getAttribute('data-elaborate-for')+'"][data-choice="Yes"]').click();e.value='😀'.repeat(selector.includes('elaborate')?n-6:n);}, {selector,n});
const before=posts.length;await page.click('#details-submit');await new Promise(r=>setTimeout(r,50));assert.equal(posts.length-before,n>2000?0:1);
if(n>2000){assert.equal(await page.$eval('#details-error',e=>e.textContent),'Intake answers must be at most 2000 characters.');assert.equal(await page.$eval('#question-list '+selector,e=>Array.from(e.value).length),selector.includes('elaborate')?n-6:n);}
}
report.cases.push({file,width,category});await page.close();}assert.deepEqual(report.errors,[]);report.passed=true;}finally{await browser.close();fs.writeFileSync(output,JSON.stringify(report,null,2));}})().catch(e=>{console.error(e);process.exit(1);});
