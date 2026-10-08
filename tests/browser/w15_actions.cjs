/* Real-browser W15 action-bar contract. Requires Puppeteer and a live mock server.
 * PUPPETEER_MODULE optionally points at an existing installation. No app writes.
 * Run: PUPPETEER_MODULE=/path/to/puppeteer BROWSER_EXECUTABLE=/path/to/browser
 *      node tests/browser/w15_actions.cjs BASE_URL OUTPUT_JSON
 *
 * W35 correction (the app did not change): since W30 (d50a891, the operator-approved one-screen
 * filing frame) the options and fields live in a region that scrolls inside the step,
 * so a card scrolled out of that region still has a layout box under the action bar
 * while nobody can see or click it there. Each control is now measured by the part
 * of it its scroll containers actually show; a control with no visible part is out
 * of this check (the W30 scripts pin that the region scrolls to it). The assertions
 * themselves are unchanged and apply to every visible part.
 */
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const base = process.argv[2] || 'http://127.0.0.1:55817';
const output = process.argv[3];
if (!output) throw new Error('OUTPUT_JSON is required');
fs.mkdirSync(path.dirname(output),{recursive:true});
const modes = process.env.W15_CSS_OVERRIDE ? ['override'] : ['shipped'];
const viewports = [[360,900],[390,844],[600,900],[601,900],[1200,600],[1200,900]];
const report = {views:[], errors:[], passed:false};
(async () => {
  const browser = await puppeteer.launch({headless:true,
    ...(process.env.BROWSER_EXECUTABLE ? {executablePath:process.env.BROWSER_EXECUTABLE} : {}),
    args:['--no-sandbox']});
  try {
    for (const mode of modes) for (const file of ['driver-filing.html','index.html']) {
      for (const [width,height] of viewports) {
        const page = await browser.newPage();
        const view = {mode,file,width,height,stages:[]};
        report.views.push(view);
        page.on('pageerror',e=>report.errors.push(String(e)));
        await page.setViewport({width,height});
        if(process.env.W15_CSS_OVERRIDE){
          await page.setRequestInterception(true);
          page.on('request',r=>r.url().endsWith('/party/party.css') ? r.respond({
            status:200,contentType:'text/css',body:fs.readFileSync(process.env.W15_CSS_OVERRIDE,'utf8')
          }) : r.continue());
        }
        await page.goto(base+'/party/'+file,{waitUntil:'networkidle0'});
        await page.evaluate(()=>document.fonts.ready);
        async function check(stage,selector){
          const probe = await page.evaluate(selector=>{
            const step=document.querySelector(selector);
            const bar=step.querySelector('.step-actions');
            const b=bar.getBoundingClientRect(),s=getComputedStyle(bar);
            // The part of an element its scrolling ancestors show (body and html scroll
            // the viewport, so they never clip here).
            const shown=e=>{
              const r=e.getBoundingClientRect();
              let top=r.top,bottom=r.bottom,left=r.left,right=r.right;
              for(let a=e.parentElement;a&&a!==document.body&&a!==document.documentElement;a=a.parentElement){
                const st=getComputedStyle(a);
                if(st.overflowY==='visible'&&st.overflowX==='visible')continue;
                const q=a.getBoundingClientRect();
                top=Math.max(top,q.top);bottom=Math.min(bottom,q.bottom);
                left=Math.max(left,q.left);right=Math.min(right,q.right);
              }
              return {top,bottom,left,right};
            };
            const controls=[...step.querySelectorAll('.option-card,.field,.choice-button')]
              .filter(e=>e.getBoundingClientRect().height>0).map(e=>{
                const r=shown(e);
                if(r.bottom-r.top<1||r.right-r.left<1)return null;
                const x=(r.left+r.right)/2,y=(r.top+r.bottom)/2;
                const hit=document.elementFromPoint(x,y);
                return {text:e.textContent.trim(),bottom:r.bottom,
                  covered:r.left<b.right&&r.right>b.left&&r.top<b.bottom&&r.bottom>b.top,
                  visibleCenter:y>=0&&y<innerHeight&&x>=0&&x<innerWidth,
                  clickable:!!hit&&(hit===e||e.contains(hit)),hit:hit?.id||hit?.className};
              }).filter(Boolean);
            const visible=[...document.querySelectorAll('#form-steps > .step')].filter(e=>!e.hidden).map(e=>e.id);
            return {position:s.position,bottom:s.bottom,barTop:b.top,controls,visible,
              overflow:document.documentElement.scrollWidth-innerWidth};
          },selector);
          view.stages.push({stage,...probe});
          assert.deepEqual(probe.visible,[selector.slice(1)],'only the active step is visible');
          assert.ok(probe.overflow<=0,'no horizontal overflow');
          for(const c of probe.controls){
            assert.equal(c.covered,false,'action bar overlaps '+c.text);
            assert.ok(c.bottom<=probe.barTop,'action bar must follow '+c.text);
            if(c.visibleCenter)assert.equal(c.clickable,true,'control center hits '+c.hit);
          }
          assert.equal(probe.position,'static','action bar must remain in normal flow');
          assert.equal(probe.bottom,'auto','no obsolete sticky bottom offset');
          return probe;
        }
        const category=await check('category','#step-category');
        // Exercise a genuinely visible option with a pointer BEFORE any scroll.
        const first=category.controls.find(c=>c.visibleCenter);
        if(first){
          const selected=await page.evaluate(text=>{
            const els=[...document.querySelectorAll('#category-options .option-card')];
            return els.findIndex(e=>e.textContent.trim()===text);
          },first.text);
          await page.click('#category-options .option-card:nth-child('+(selected+1)+')');
          assert.equal(await page.$eval('#category-options .option-card:nth-child('+(selected+1)+')',e=>e.classList.contains('selected')),true);
          assert.equal(await page.$eval('#category-next',e=>e.disabled),false);
          view.directInitialClick=first.text;
        }
        await page.click('#category-options .option-card:nth-child(2)');
        await page.click('#category-next');
        await page.waitForSelector('#step-trip:not([hidden])');
        await page.waitForSelector('#trip-options .option-card');
        await check('trip','#step-trip');
        await page.click('#trip-options .option-card');
        await page.click('#trip-next');
        await page.waitForSelector('#step-details:not([hidden])');
        await check('details','#step-details');
        if(width===360&&file==='driver-filing.html'){
          await page.screenshot({path:path.join(path.dirname(output),'actions-driver-360.png'),fullPage:true});
        }
        await page.close();
      }
    }
    assert.deepEqual(report.errors,[]);
    report.passed=true;
  } catch(e){report.error=String(e);process.exitCode=1;}
  finally{
    await browser.close();
    fs.mkdirSync(path.dirname(output),{recursive:true});
    fs.writeFileSync(output,JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify({passed:report.passed,views:report.views.length,
      stages:report.views.reduce((n,v)=>n+v.stages.length,0),error:report.error,output}));
  }
})().catch(e=>{console.error(e);process.exitCode=1;});
