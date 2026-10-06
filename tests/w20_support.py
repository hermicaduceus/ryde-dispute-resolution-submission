"""W20 runtime driver; independent expectations come from W16 literal tables."""
import json
import os
import shutil
import subprocess
from pathlib import Path
from tests.w16_support import DOM, RIDER, DRIVER
ROOT = Path(__file__).resolve().parents[1]
HARNESS = DOM + r'''
const opts=JSON.parse(process.env.W20);
doc.getElementById('form-steps').setAttribute('data-filed-by',opts.role);
['step-trip','step-details','outcome','details-error'].forEach(id=>doc.getElementById(id).hidden=true);
const calls=[];const tick=()=>new Promise(r=>setTimeout(r,0));
const fetch=(url,o)=>{calls.push({url,method:o.method,body:o.body?JSON.parse(o.body):null});return o.method==='GET'?Promise.resolve({ok:true,json:()=>Promise.resolve({trips:['A','B'].map(trip_id=>({trip_id,label:trip_id}))})}):new Promise(()=>{});};
(async()=>{
vm.runInNewContext(fs.readFileSync(process.env.PARTY_JS,'utf8'),{document:doc,window:{scrollTo(){}},fetch,Promise,setTimeout,encodeURIComponent,JSON,Array,Number,isFinite,String});
const list=doc.getElementById('question-list');
function snapshot(){return {trip:doc.getElementById('trip-options').children.filter(n=>n.classList.contains('selected')).map(n=>n.textContent),disabled:doc.getElementById('trip-next').disabled,visible:['step-category','step-trip','step-details'].map(id=>!doc.getElementById(id).hidden),rows:list.children.map(f=>{const c=f.children[1],e=f.children[2];return {key:c.id.replace(/^answer-/,''),value:c.value,choices:c.children.map(b=>({choice:b.dataset.choice,selected:b.classList.contains('selected'),pressed:b.getAttribute('aria-pressed')})),explanation:e?e.value:null,explanationHidden:e?e.hidden:null};}),description:doc.getElementById('description').value,amount:doc.getElementById('claim-amount').value};}
doc.getElementById('category-options').children[opts.category].click();doc.getElementById('category-next').click();await tick();await tick();doc.getElementById('trip-options').children[0].click();doc.getElementById('trip-next').click();
const snapshots=[];
for(const op of opts.ops){
 if(op[0]==='id')doc.getElementById(op[1]).click();
 if(op[0]==='trip'){const n=doc.getElementById('trip-options').children[op[1]];if(n)n.click();}
 if(op[0]==='category')doc.getElementById('category-options').children[op[1]].click();
 if(op[0]==='choice')list.querySelector('.choice-button[data-question-key="'+op[1]+'"][data-choice="'+op[2]+'"]').click();
 if(op[0]==='open')list.querySelector('textarea[data-question-key="'+op[1]+'"]').value=op[2];
 if(op[0]==='explain')list.querySelector('textarea[data-elaborate-for="'+op[1]+'"]').value=op[2];
 if(op[0]==='value')doc.getElementById(op[1]).value=op[2];
 if(op[0]==='submit')doc.getElementById('details-form').fire('submit');
 await tick();await tick();if(op[0]==='snapshot')snapshots.push(snapshot());
}
process.stdout.write(JSON.stringify({calls,snapshots,error:doc.getElementById('details-error').textContent,errorVisible:!doc.getElementById('details-error').hidden,final:snapshot()}));
})().catch(e=>{process.stderr.write(String(e.stack||e));process.exit(1);});
'''
def drive(role, category, ops):
    node = shutil.which('node')
    assert node, 'Node required'
    env = dict(os.environ, PARTY_JS=str(ROOT/'ui/party/party.js'), W20=json.dumps(dict(role=role,category=category,ops=ops)))
    result = subprocess.run([node,'-e',HARNESS],env=env,text=True,capture_output=True,timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)
SCOPES = [(role,category,trip,table[category]) for role,table in [('rider',RIDER),('driver',DRIVER)] for category,trip in [('route_deviation','T-RD0103'),('no_show_charge','T-NS0201')]]
