"""Reusable Node fake-DOM driver for W23 B2 console acceptance tests."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NODE = "[USER_HOME]/.hermes/tools/node-26.7.0-darwin-arm64/bin/node"

HARNESS = r'''
const fs=require("fs"),vm=require("vm");
function node(tag){
 const n={tagName:String(tag).toUpperCase(),children:[],parentNode:null,hidden:false,disabled:false,checked:false,open:false,
 type:"",value:"",name:"",id:"",htmlFor:"",maxLength:0,step:"",min:"",files:[],_text:"",_attrs:{},_cls:[],_l:{}};
 Object.defineProperty(n,"textContent",{get:()=>n._text+n.children.map(c=>c.textContent).join(""),set:v=>{n._text=v==null?"":String(v);n.children=[];}});
 Object.defineProperty(n,"className",{get:()=>n._cls.join(" "),set:v=>n._cls=String(v).split(/\s+/).filter(Boolean)});
 n.classList={add:c=>{if(!n._cls.includes(c))n._cls.push(c)},remove:c=>n._cls=n._cls.filter(x=>x!==c),contains:c=>n._cls.includes(c)};
 n.dataset={}; n.setAttribute=(k,v)=>{n._attrs[k]=String(v);if(k==="id")n.id=String(v);if(k==="name")n.name=String(v);if(k==="value")n.value=String(v);};
 n.getAttribute=k=>k==="id"?n.id:k==="name"?n.name:k==="value"?n.value:k==="for"?n.htmlFor:(k in n._attrs?n._attrs[k]:null);
 n.appendChild=c=>{n.children.push(c);c.parentNode=n;if(c.id)ids[c.id]=c;return c};n.removeChild=c=>{n.children=n.children.filter(x=>x!==c);return c};
 Object.defineProperty(n,"firstChild",{get:()=>n.children[0]||null});
 n.addEventListener=(e,h)=>(n._l[e]=n._l[e]||[]).push(h);
 n.fire=e=>(n._l[e]||[]).forEach(h=>h({preventDefault(){},target:n}));
 n.click=()=>{if(!n.disabled)n.fire("click")};
 n.all=()=>{let out=[];(function w(x){x.children.forEach(c=>{out.push(c);w(c)})})(n);return out};
 function match(c,s){if(s.startsWith("#"))return c.id===s.slice(1);let checked=s.endsWith(":checked");if(checked)s=s.slice(0,-8);let am=s.match(/\[([^=\]]+)(?:=["']?([^\]"']+)["']?)?\]/);if(am){s=s.replace(am[0],"");let val=c[am[1]]||c.getAttribute(am[1]);if(am[2]!==undefined&&String(val)!==am[2])return false;if(am[2]===undefined&&val==null)return false}let parts=s.split(".");let tag=parts.shift();if(tag&&c.tagName!==tag.toUpperCase())return false;if(!parts.every(x=>c.classList.contains(x)))return false;return !checked||c.checked;}
 n.querySelectorAll=s=>n.all().filter(c=>match(c,s));n.querySelector=s=>n.querySelectorAll(s)[0]||null;return n;
}
const ids={}; const ROOT=node("body");
const doc={createElement:t=>node(t),getElementById:id=>{if(!ids[id]){ids[id]=node(id.includes("picker")?"input":"div");ids[id].id=id;ROOT.appendChild(ids[id])}return ids[id]},querySelector:s=>ROOT.querySelector(s),querySelectorAll:s=>ROOT.querySelectorAll(s)};
["case-picker","run-folder-picker","load-status","payload-status","case-workspace","loaded-file","metadata-list","grievance-content","evidence-content","claims-content","policy-content","resolution-content","events-content","queue-refresh","queue-status","queue-content","overrides-status","overrides-content","decision-section","decision-content"].forEach(x=>doc.getElementById(x));
ids["case-workspace"].hidden=true;ids["decision-section"].hidden=true;
const scenario=JSON.parse(process.env.SCENARIO), requests=[], counters={};
function responseFor(url){let seq=scenario.routes[url]||scenario.routes["*"];if(!seq)return {reject:true};let i=counters[url]||0;counters[url]=i+1;return seq[Math.min(i,seq.length-1)];}
const fetch=(url,opts)=>{opts=opts||{};requests.push({url:String(url),method:opts.method||"GET",body:opts.body?JSON.parse(opts.body):null});let r=responseFor(String(url));if(r.reject)return Promise.reject(new Error("offline"));return Promise.resolve({ok:r.status===undefined?r.ok!==false:r.status>=200&&r.status<300,status:r.status||200,json:()=>Promise.resolve(r.body)});};
const tick=()=>new Promise(r=>setTimeout(r,0));
function byClass(c){return ROOT.all().filter(n=>n.classList.contains(c))}
function snap(n){return {tag:n.tagName,id:n.id,className:n.className,text:n.textContent,hidden:n.hidden,disabled:n.disabled,checked:n.checked,value:n.value,type:n.type,name:n.name,htmlFor:n.htmlFor,maxLength:n.maxLength,step:n.step,min:n.min,attrs:n._attrs,dataset:n.dataset,children:n.children.map(snap)}}
(async()=>{vm.runInNewContext(fs.readFileSync(process.env.APP_JS,"utf8"),{document:doc,window:{},fetch,Promise,setTimeout,encodeURIComponent,JSON,Array,Number,String,isFinite,Math,Object,Error});await tick();await tick();
 for(const a of (scenario.actions||[])){let n;if(a.id)n=ids[a.id]||doc.getElementById(a.id);else n=byClass(a.className)[a.index||0];if(a.op==="click")n.click();else if(a.op==="submit")n.fire("submit");else if(a.op==="toggle"){n.open=true;n.fire("toggle")}else if(a.op==="set"){n.value=a.value}else if(a.op==="check"){ROOT.all().filter(x=>x.name===n.name).forEach(x=>x.checked=false);n.checked=true;n.fire("change")}else if(a.op==="pick"){n.files=[{name:a.name||"case_file.json",webkitRelativePath:a.path===undefined?"picked/case_file.json":a.path,text:()=>Promise.resolve(JSON.stringify(a.body))}];n.fire("change")}await tick();await tick();await tick();}
 process.stdout.write(JSON.stringify({ids:Object.fromEntries(Object.entries(ids).map(([k,v])=>[k,snap(v)])),requests,classes:Object.fromEntries(["queue-row","queue-category","queue-safety","queue-amount","queue-held","queue-waiting","queue-open","overrides-approved","override-group","override-entry","decision-note","human-decision-record","confirm-warning","decision-result","event-row","event-payload","payload-json","payload-error"].map(c=>[c,byClass(c).map(snap)]))}));
})().catch(e=>{process.stderr.write(String(e.stack||e));process.exit(1)});
'''

def drive(routes, actions=()):
    scenario = {"routes": routes, "actions": list(actions)}
    env = dict(os.environ, APP_JS=str(REPO / "ui" / "app.js"), SCENARIO=json.dumps(scenario))
    result = subprocess.run([NODE, "-e", HARNESS], env=env, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise AssertionError("app.js harness failed: " + result.stderr)
    return json.loads(result.stdout)


def ok(body):
    return {"status": 200, "body": body}


def bad(status=503, body=None):
    return {"status": status, "body": body or {}}


def case_file(outcome="withheld", fare=112.56, event=False):
    return {"run_id":"RUN / 7","dispute_id":"DISP-7","category":"route_deviation","generated_at":"2026-10-01T00:00:00Z","intake":{},"evidence_pack":{"fare":{"charged_sgd":fare}},"claims":{},"policy":{},"resolution":{"outcome":outcome,"party_message":"waiting","withheld_candidate":{"action":"refund","recommended_amount_sgd":55.16,"confidence":0.9,"explanation":"x"}},"events":[{"seq":9,"ts":"now","type":"judge.ruling_withheld","from":"judge","to":"system","summary":"held","payload_ref":"payloads/0009-judge-ruling-withheld.json"}] if event else []}


def queue_row(**changes):
    row={"run_id":"RUN / 7","dispute_id":"DISP-7","category":"route_deviation","safety":False,"amount_sgd":55.16,"amount_source":"proposed","waiting_seconds":59,"held_by":["ESC-4"],"proposed":{"action":"refund","amount_sgd":55.16},"can_approve":True}
    row.update(changes);return row


def base_routes(rows=None, groups=None, approved=0):
    return {"/api/review/queue":[ok({"cases":[] if rows is None else rows})],"/api/review/overrides":[ok({"approved_count":approved,"groups":[] if groups is None else groups})]}
