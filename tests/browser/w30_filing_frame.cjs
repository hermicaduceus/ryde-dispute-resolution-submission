/* Shared filing frame: real geometry, all three steps, both roles, live resize.
 * W30_TREE_OVERRIDE serves HTML/CSS from a private reference/mutation tree.
 * Dispute responses below are explicitly deterministic test fixtures, not live rulings.
 */
const assert=require('node:assert/strict');
const fs=require('node:fs'), path=require('node:path');
const puppeteer=require(process.env.PUPPETEER_MODULE||'puppeteer');
const [base,output]=process.argv.slice(2);
fs.mkdirSync(path.dirname(output),{recursive:true});
const report={passed:false,views:[],errors:[]};
const sizes=[[320,740],[360,480],[390,844],[460,800],[600,900],[800,320],[1200,600],[1200,900]];
(async()=>{
 const browser=await puppeteer.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE,args:['--no-sandbox']});
 try{
  for(const file of ['index.html','driver-filing.html'])for(const [width,height] of sizes){
   const page=await browser.newPage(),view={file,width,height,checks:[]};report.views.push(view);
   page.on('pageerror',e=>report.errors.push(String(e)));
   await page.setViewport({width,height});await page.setRequestInterception(true);
   page.on('request',r=>{
    const url=new URL(r.url());
    if(url.pathname==='/api/disputes'&&r.method()==='POST')return r.respond({status:200,contentType:'application/json',body:JSON.stringify({run_id:'layout-fixture',dispute_id:'FIXTURE-REF',status:'under_review',message:'Your case is still under review.',questions:[]})});
    if(process.env.W30_TREE_OVERRIDE&&['/'+file,'/party.css'].some(s=>url.pathname.endsWith(s))){
     const p=path.join(process.env.W30_TREE_OVERRIDE,'ui','party',path.basename(url.pathname));
     return r.respond({status:200,contentType:p.endsWith('.css')?'text/css':'text/html',body:fs.readFileSync(p,'utf8')});
    }return r.continue();
   });
   await page.goto(base+'/party/'+file,{waitUntil:'networkidle0'});await page.evaluate(()=>document.fonts.ready);
   assert.ok(await page.$('.filing-fine-print'),'demo notices moved to a bottom footer');
   async function check(stage){
    const g=await page.evaluate(()=>{
     const rect=e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height};};
     const header=document.querySelector('.party-header'),footer=document.querySelector('.filing-fine-print');
     const step=[...document.querySelectorAll('#form-steps > .step')].filter(e=>!e.hidden);
     const s=step[0],bar=s.querySelector('.step-actions'),region=s.id==='step-trip'?s.querySelector('#trip-options'):s.querySelector('.filing-fields');
     const hit=e=>{const r=e.getBoundingClientRect(),h=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return !!h&&(h===e||e.contains(h));};
     return {vh:innerHeight,vw:innerWidth,header:rect(header),title:rect(header.querySelector('h1')),intro:rect(header.querySelector('.intro')),
      headerScroll:header.scrollTop,headerClient:header.clientHeight,headerFull:header.scrollHeight,
      links:[...header.querySelectorAll('a')].map(e=>({text:e.textContent,...rect(e),hit:hit(e)})),
      footer:footer?rect(footer):null,footerStyle:footer?{font:getComputedStyle(footer).fontSize,color:getComputedStyle(footer).color}:null,
      footerNotes:footer?[...footer.querySelectorAll('.demo-note')].map(e=>({text:e.textContent,bg:getComputedStyle(e).backgroundColor,border:getComputedStyle(e).borderWidth})):[],
      card:rect(s),bar:rect(bar),region:rect(region),regionClient:region.clientHeight,regionFull:region.scrollHeight,
      buttons:[...bar.querySelectorAll('button')].map(e=>({id:e.id,...rect(e),hit:hit(e)})),
      visible:step.map(e=>e.id),overflow:document.documentElement.scrollWidth-innerWidth,bodyOverflow:getComputedStyle(document.body).overflow,scrollY};
    });
    view.checks.push({stage,...g});
    assert.equal(g.visible.length,1,'one active step');assert.ok(g.overflow<=0,'no horizontal overflow');
    assert.ok(g.header.top>=0&&g.header.bottom<=g.card.top+1,'header above rather than covered by card');
    assert.ok(g.title.height>0&&g.title.top>=g.header.top-1&&g.title.bottom<=g.header.bottom+1,'title visible on entry');
    assert.ok(g.footer&&g.footer.top>=g.card.bottom-1&&g.footer.bottom<=g.vh+1,'fine print below form');
    assert.ok(parseFloat(g.footerStyle.font)>=12&&parseFloat(g.footerStyle.font)<=13,'readable fine print');
    for(const note of g.footerNotes){assert.equal(note.bg,'rgba(0, 0, 0, 0)');assert.equal(note.border,'0px');}
    assert.equal(g.footerNotes.length,file==='index.html'?1:2,'retain demo limitations');
    assert.ok(g.region.height>20,'usable scroll region');assert.ok(g.region.bottom<=g.bar.top+1,'actions do not overlap content');
    for(const b of g.buttons){assert.ok(b.top>=0&&b.bottom<=g.vh,'actions visible after '+stage);assert.equal(b.hit,true,'action centre is clickable');assert.ok(g.vh-b.bottom<=g.footer.height+55,'actions anchored above fine print');}
    assert.equal(g.bodyOverflow,'hidden');assert.equal(g.scrollY,0,'entry never scrolls header off screen');
    if(g.vh>=700){
     assert.ok(g.intro.bottom<=g.header.bottom+1,'intro visible on ordinary screen');
     for(const l of g.links){assert.ok(l.top>=g.header.top&&l.bottom<=g.header.bottom+1,'all navigation visible on ordinary screen');assert.equal(l.hit,true);assert.ok(l.height>=44);}
    }
    return g;
   }
   async function resize(stage){for(const h of [320,480,700,900,height]){await page.setViewport({width,height:h});await check(stage+'-resize-'+h);}}
   await check('category');await resize('category');
   await page.click('#category-options .option-card:first-child');await page.click('#category-next');
   await page.waitForSelector('#trip-options .trip-card');await check('trip');await resize('trip');
   await page.evaluate(()=>{const l=document.querySelector('#trip-options');l.scrollTop=l.scrollHeight;});
   await check('trip-end');
   await page.evaluate(()=>{document.querySelector('#trip-options .trip-card').click();});
   await page.click('#trip-next');await check('details');await resize('details');
   // Keyboard focus must reveal each details field inside its own scrolling content.
   await page.focus('#claim-amount');
   const reached=await page.evaluate(()=>{const f=document.querySelector('#claim-amount'),p=f.closest('.filing-fields');const r=f.getBoundingClientRect(),l=p.getBoundingClientRect();return {inside:r.top>=l.top-1&&r.bottom<=l.bottom+1,scroll:p.scrollTop,field:{top:r.top,bottom:r.bottom,height:r.height},region:{top:l.top,bottom:l.bottom,height:l.height}};});
   view.lastFieldProbe=reached;
   assert.equal(reached.inside,true,'last details input reachable without moving actions');
   await page.evaluate(()=>document.activeElement.blur());
   await page.click('#details-back');await page.waitForSelector('#trip-options .trip-card');await check('trip-back-from-details');
   // On short panes, every header link and all fine print remain keyboard-reachable.
   for(const idx of [0,1,file==='driver-filing.html'?2:1]){
    await page.evaluate(i=>document.querySelectorAll('.party-header a')[i].focus(),idx);
    const reachable=await page.evaluate(()=>{const r=document.activeElement.getBoundingClientRect(),h=document.querySelector('.party-header').getBoundingClientRect();return r.top>=h.top-1&&r.bottom<=h.bottom+1;});
    assert.equal(reachable,true,'header navigation reachable on short panes');
   }
   await page.evaluate(()=>{document.querySelector('.party-header').scrollTop=0;document.activeElement.blur();const f=document.querySelector('.filing-fine-print');f.scrollTop=f.scrollHeight;});
   const fine=await page.evaluate(()=>{const f=document.querySelector('.filing-fine-print'),p=f.lastElementChild,r=p.getBoundingClientRect(),l=f.getBoundingClientRect();return r.bottom<=l.bottom+1;});
   assert.equal(fine,true,'last fine-print line reachable');
   await page.evaluate(()=>document.querySelector('.filing-fine-print').scrollTop=0);
   await page.screenshot({path:path.join(path.dirname(output),file.replace('.html','')+'-'+width+'x'+height+'.png')});
   await page.evaluate(()=>document.querySelector('#trip-options .trip-card').click());
   await page.click('#trip-next');
   await page.waitForSelector('#step-details:not([hidden])');
   await page.$eval('#description',e=>e.value='Layout fixture description');
   await page.click('#details-submit');await page.waitForSelector('#outcome:not([hidden])');
   assert.equal(await page.$eval('body',e=>getComputedStyle(e).overflow),'visible','receipt restores page scrolling');
   if(file==='driver-filing.html')assert.ok(await page.$eval('#outcome',e=>e.textContent.includes('Save your reference number.')));
   await page.close();
  }
  assert.deepEqual(report.errors,[]);report.passed=true;
 }catch(e){report.error=String(e.stack||e);process.exitCode=1;}
 finally{await browser.close();fs.writeFileSync(output,JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,views:report.views.length,checks:report.views.reduce((n,v)=>n+v.checks.length,0),error:report.error}));}
})().catch(e=>{console.error(e);process.exitCode=1;});
