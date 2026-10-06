/* W30 review repair: deterministic real-browser race and error-card checks.
 * Run with PUPPETEER_MODULE / BROWSER_EXECUTABLE, BASE_URL and OUTPUT_JSON.
 * No submissions, backend writes, or timing races. Each held request is released explicitly.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const puppeteer = require(process.env.PUPPETEER_MODULE || 'puppeteer');
const [base, output] = process.argv.slice(2);
const report = {passed:false, cases:[], errors:[]};
(async()=>{
  const browser = await puppeteer.launch({headless:true,
    executablePath:process.env.BROWSER_EXECUTABLE, args:['--no-sandbox']});
  try {
    for (const file of ['index.html','driver-filing.html']) {
      for (const stale of ['success','failure']) for (const state of ['pending','settled']) {
        const page = await browser.newPage();
        page.on('pageerror', e=>report.errors.push(String(e)));
        await page.setViewport({width:390,height:844});
        await page.setRequestInterception(true);
        const held = [];
        page.on('request', r=>r.url().includes('/api/trips') ? held.push(r) : r.continue());
        await page.goto(base+'/party/'+file,{waitUntil:'domcontentloaded'});
        // Record landing calls as well as the actual browser geometry.
        await page.evaluate(()=>{
          window.tripLandings=[];
          const original=Element.prototype.scrollIntoView;
          Element.prototype.scrollIntoView=function(o){
            if(this.id==='step-trip') window.tripLandings.push(o.block);
            return original.call(this,o);
          };
        });
        await page.waitForSelector('#category-options .option-card');
        await page.click('#category-options .option-card:first-child');
        await page.click('#category-next');
        const waitHeld = async n=>{
          const start=Date.now();
          while(held.length<n){assert.ok(Date.now()-start<5000,'request was not issued'); await new Promise(r=>setTimeout(r,10));}
        };
        await waitHeld(1);
        await page.click('#trip-back');
        await page.click('#category-options .option-card:nth-child(2)');
        await page.click('#category-next');
        await waitHeld(2);
        const respond = async (index, bad=false)=>{
          const r=held[index];
          const body=bad ? {error:'old failure'} : {trips:Array.from({length:index===0?2:5},(_,i)=>({
            trip_id:(index===0?'OLD-':'NEW-')+i,label:(index===0?'Old trip ':'New trip ')+i,date:'2026',kind_label:'Ride',fare_sgd:6.61}))};
          const finished=page.waitForResponse(response=>response.url()===r.url());
          await r.respond({status:bad?500:200,contentType:'application/json',body:JSON.stringify(body)});
          const response=await finished; await response.text();
          // Give the fetch promise and render continuation two animation frames to settle.
          await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
        };
        if(state==='settled'){
          await respond(1);
          await page.waitForFunction(()=>document.querySelectorAll('#trip-options .trip-card').length===5);
          await page.click('#trip-options .trip-card:first-child');
        }
        const snapshot = ()=>page.evaluate(()=>({
          text:document.getElementById('trip-options').textContent,
          selected:document.querySelector('#trip-options .selected')?.textContent || null,
          nextDisabled:document.getElementById('trip-next').disabled,
          error:document.getElementById('trip-error').textContent,
          errorHidden:document.getElementById('trip-error').hidden,
          landings:window.tripLandings.slice(), scrollY
        }));
        const before=await snapshot();
        await respond(0,stale==='failure');
        const after=await snapshot();
        assert.deepEqual(after,before,'superseded '+stale+' must not change the '+state+' view');
        if(state==='pending'){
          await respond(1);
          await page.waitForFunction(()=>document.querySelectorAll('#trip-options .trip-card').length===5);
          assert.equal((await snapshot()).landings.length,1);
        }
        report.cases.push({file,stale,state,before,after});
        await page.close();
      }
      // The current failure must show the heading, error and Back after Continue
      // from a scrolled category card, including the short landscape viewport.
      for (const [width,height] of [[390,844],[800,320]]) {
        const page=await browser.newPage();
        await page.setViewport({width,height});
        await page.setRequestInterception(true);
        let retry=false, retryRequest, releaseRetry;
        const retryHeld=new Promise(resolve=>{releaseRetry=resolve;});
        page.on('request',r=>{
          if(!r.url().includes('/api/trips')) return r.continue();
          if(retry){retryRequest=r;releaseRetry();return;}
          return r.respond({status:500,contentType:'application/json',
            body:JSON.stringify({error:'Trip service unavailable'})});
        });
        await page.goto(base+'/party/'+file,{waitUntil:'domcontentloaded'});
        await page.waitForSelector('#category-options .option-card');
        await page.click('#category-options .option-card:first-child');
        await page.evaluate(()=>document.getElementById('category-next').scrollIntoView({block:'center'}));
        await page.click('#category-next');
        await page.waitForFunction(()=>!document.getElementById('trip-error').hidden &&
          document.getElementById('step-trip').getBoundingClientRect().top>=0);
        const result=await page.evaluate(()=>{
          const rect=id=>{const r=document.getElementById(id).getBoundingClientRect();return {top:r.top,bottom:r.bottom};};
          return {card:rect('step-trip'),error:rect('trip-error'),back:rect('trip-back'),vh:innerHeight,
            nextDisabled:document.getElementById('trip-next').disabled};
        });
        assert.ok(result.card.top>=0,'error-card heading visible');
        assert.ok(result.error.top>=0 && result.error.bottom<=result.vh,'error message visible');
        assert.ok(result.back.top>=0 && result.back.bottom<=result.vh,'Back visible');
        assert.equal(result.nextDisabled,true);
        retry=true;
        await page.click('#trip-back');
        await page.click('#category-next'); // no re-pick to hide the prior error
        await retryHeld;
        const loadingErrorHidden=await page.$eval('#trip-error',e=>e.hidden);
        assert.equal(loadingErrorHidden,true,'starting a retry hides its previous error');
        await retryRequest.respond({status:200,contentType:'application/json',body:JSON.stringify({trips:[{
          trip_id:'RETRY',label:'Retry trip',date:'2026',kind_label:'Ride',fare_sgd:6.61}]})});
        await page.waitForSelector('#trip-options .trip-card');
        const successErrorHidden=await page.$eval('#trip-error',e=>e.hidden);
        assert.equal(successErrorHidden,true,'successful retry does not show the previous error');
        report.cases.push({file,width,height,errorState:result,retry:{loadingErrorHidden,successErrorHidden}});
        await page.close();
      }
    }
    assert.deepEqual(report.errors,[]);
    report.passed=true;
  } catch(e){report.error=String(e); process.exitCode=1;}
  finally{await browser.close();fs.writeFileSync(output,JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,cases:report.cases.length,error:report.error}));}
})().catch(e=>{console.error(e);process.exitCode=1;});
