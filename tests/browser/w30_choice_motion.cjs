/* Page-3 Yes/No: real pointer motion, selected state, both roles and categories.
 * W30_CSS_OVERRIDE is scratch-only CSS injection for reference/revert proof.
 */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const puppeteer=require(process.env.PUPPETEER_MODULE||'puppeteer');
const [base,output]=process.argv.slice(2);fs.mkdirSync(path.dirname(output),{recursive:true});
const report={passed:false,views:[],errors:[]};
(async()=>{
 const browser=await puppeteer.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE,args:['--no-sandbox']});
 try{
  for(const file of ['index.html','driver-filing.html'])for(const [width,height] of [[390,844],[1200,600]])for(const category of [1,2]){
   const page=await browser.newPage(),view={file,width,height,category,checks:[]};report.views.push(view);
   page.on('pageerror',e=>report.errors.push(String(e)));await page.setViewport({width,height});
   if(process.env.W30_CSS_OVERRIDE){await page.setRequestInterception(true);page.on('request',r=>new URL(r.url()).pathname.endsWith('/party.css')?r.respond({status:200,contentType:'text/css',body:fs.readFileSync(process.env.W30_CSS_OVERRIDE,'utf8')}):r.continue());}
   await page.goto(base+'/party/'+file,{waitUntil:'networkidle0'});await page.evaluate(()=>document.fonts.ready);
   const categorySel='#category-options .option-card:nth-child('+category+')';
   await page.hover(categorySel);await page.waitForFunction(s=>getComputedStyle(document.querySelector(s)).transform==='matrix(1, 0, 0, 1, 0, -2)',{},categorySel);
   const matching=await page.$eval(categorySel,e=>{const s=getComputedStyle(e);return {transition:s.transition,shadow:s.boxShadow};});
   await page.click(categorySel);await page.click('#category-next');await page.waitForSelector('#trip-options .trip-card');
   await page.click('#trip-options .trip-card:first-child');await page.click('#trip-next');await page.waitForSelector('#step-details:not([hidden]) .choice-button');
   const count=await page.$$eval('#step-details .choice-button',a=>a.length);assert.ok(count>=2&&count%2===0);
   const selected='#step-details .choice-options:first-of-type .choice-button';
   for(const reduced of [false,true]){
    await page.emulateMediaFeatures([{name:'prefers-reduced-motion',value:reduced?'reduce':'no-preference'}]);
    for(let i=0;i<count;i++){
     const sel='#step-details .choice-button';
     await page.mouse.move(0,0);await page.waitForFunction(i=>getComputedStyle(document.querySelectorAll('#step-details .choice-button')[i]).transform==='none',{},i);
     const b=(await page.$$(sel))[i];await b.evaluate(e=>e.scrollIntoView({block:'center'}));
     const rest=await b.evaluate(e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {top:r.top,width:r.width,height:r.height,transition:s.transition,bg:s.backgroundColor,radius:s.borderRadius};});
     const r=await b.boundingBox();await page.mouse.move(r.x+r.width/2,r.y+r.height/2);
     await page.waitForFunction(({i,reduced})=>getComputedStyle(document.querySelectorAll('#step-details .choice-button')[i]).transform===(reduced?'none':'matrix(1, 0, 0, 1, 0, -2)'),{timeout:1500}, {i,reduced}).catch(()=>{});
     assert.equal(await b.evaluate(e=>getComputedStyle(e).transform),reduced?'none':'matrix(1, 0, 0, 1, 0, -2)','Yes/No hover lift must settle to the intended transform');
     const hover=await b.evaluate(e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect(),h=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return {top:r.top,width:r.width,height:r.height,transition:s.transition,shadow:s.boxShadow,bg:s.backgroundColor,radius:s.borderRadius,hit:h===e||e.contains(h)};});
     assert.ok(Math.abs(hover.top-rest.top-(reduced?0:-2))<0.1,'measured hover lift');
     assert.equal(hover.transition,reduced?'none':matching.transition);assert.equal(hover.shadow,matching.shadow);assert.equal(hover.width,rest.width);assert.equal(hover.height,rest.height);assert.equal(hover.radius,rest.radius);assert.equal(hover.bg,rest.bg);assert.equal(hover.hit,true);
     view.checks.push({i,reduced,rest,hover});
    }
    // Both selected answers still lift, while aria-pressed stays exclusive.
    for(const choice of ['Yes','No']){
     const b=await page.$('#step-details .choice-button[data-choice="'+choice+'"]');await b.click();
     assert.equal(await b.evaluate(e=>e.getAttribute('aria-pressed')),'true');
     assert.equal(await b.evaluate(e=>e.parentElement.querySelectorAll('[aria-pressed="true"]').length),1);
     await page.waitForFunction(({choice,reduced})=>getComputedStyle(document.querySelector('#step-details .choice-button[data-choice="'+choice+'"]')).transform===(reduced?'none':'matrix(1, 0, 0, 1, 0, -2)'),{}, {choice,reduced});
     const state=await b.evaluate(e=>{const s=getComputedStyle(e);return {border:s.borderWidth,color:s.borderColor,weight:s.fontWeight,transform:s.transform};});assert.equal(state.border,'3px');assert.equal(state.color,'rgb(233, 56, 100)');assert.equal(state.weight,'600');view.checks.push({choice,reduced,state});
    }
   }
   await page.mouse.move(0,0);await page.emulateMediaFeatures([{name:'prefers-reduced-motion',value:'no-preference'}]);
   await page.focus('#step-details .choice-button');await page.keyboard.press('Tab');
   const keyboard=await page.evaluate(()=>({choice:document.activeElement.classList.contains('choice-button'),outline:getComputedStyle(document.activeElement).outlineStyle}));assert.equal(keyboard.choice,true);assert.equal(keyboard.outline,'solid');
   for(const id of ['details-back','details-submit'])assert.equal(await page.$eval('#'+id,e=>getComputedStyle(e).transform),'none','action buttons unchanged');
   if(width===390&&category===1)await page.screenshot({path:path.join(path.dirname(output),file.replace('.html','')+'-choice.png')});
   await page.close();
  }
  assert.deepEqual(report.errors,[]);report.passed=true;
 }catch(e){report.error=String(e.stack||e);process.exitCode=1;}
 finally{await browser.close();fs.writeFileSync(output,JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,views:report.views.length,error:report.error}));}
})().catch(e=>{console.error(e);process.exitCode=1;});
