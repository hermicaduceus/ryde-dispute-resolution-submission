"""W16 independent literal expectations and existing test seams. Never imported by app."""
import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
from tests.w23_support import Server as BaseServer, ORG_DIR, SYNTH_DIR, judge_payload
from tests.support import ScriptedLLM
from tests.test_party_surface import _record, _run, _slot_advocate

ROOT = Path(__file__).resolve().parent.parent
DRIVER = {
    "route_deviation": (
        ("route_shown_to_driver", "What route did the app show you, and roughly how long was it?", "open"),
        ("route_agreed_with_rider", "Did you and the rider agree to take a different route?", "yes_no"),
        ("rider_requested_stop", "Did the rider ask you to stop anywhere along the way?", "yes_no"),
        ("safety_concern", "At any point were you worried for your safety?", "yes_no")),
    "no_show_charge": (
        ("driver_waiting_place", "Where did you wait, and for roughly how long?", "open"),
        ("driver_contacted_rider", "Did you try to call or message the rider?", "yes_no"),
        ("safety_concern", "At any point were you worried for your safety?", "yes_no"))}
RIDER = {
    "route_deviation": (
        ("expected_route", "What route did the app show you, and roughly how long was it?", "open"),
        ("was_route_agreed", "Did you and the driver agree to take a different route?", "yes_no"),
        ("asked_driver_to_stop", "Did you ask the driver to stop anywhere along the way?", "yes_no"),
        ("safety_concern", "At any point were you worried for your safety?", "yes_no")),
    "no_show_charge": (
        ("where_were_you", "Where were you when the trip was meant to start?", "open"),
        ("did_driver_contact_you", "Did the driver try to contact you?", "yes_no"),
        ("safety_concern", "At any point were you worried for your safety?", "yes_no"))}
BANK = {
    "route_deviation": ("route_shown", "route_discussed", "stops_or_changes", "road_conditions", "pickup_dropoff"),
    "no_show_charge": ("waiting_place", "driver_contact", "arrival_time", "cancel_reason")}
FORM = 'About the form question "%s": could you tell us a little more?'
BLANK = 'We didn\'t get an answer to "%s". Could you tell us?'
INVALID_PAGE = "This filing page could not be loaded. Please return to the help page and try again."
DRIVER_CATEGORIES = ["A question about the route I took", "A no-show or waiting fee", "A cleaning fee or damage report", "A safety incident", "Something else"]
RIDER_CATEGORIES = ["My trip went the wrong way", "I was charged for a trip that did not happen", "Property damage or a mess left behind", "A safety incident", "Something else"]
RIDER_CATEGORY_IDS = ["route_deviation", "no_show_charge", "property_damage_mess", "safety_incident", "other"]
DRIVER_CATEGORY_IDS = ["route_deviation", "no_show_charge", "property_damage_mess", "safety_incident", "other"]
DESCRIPTION_ERROR = "Please tell us what happened before sending."
AMOUNT_ERROR = "The amount must be between 0 and 500 SGD."

class Server(BaseServer):
    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(10)
        if self.thread.is_alive():
            raise AssertionError("server did not stop")
        self.tmp.cleanup()

def answers(category, role="driver", blank=False):
    return {k: "" if blank else ("No" if kind == "yes_no" else "At the booked place, about five and a half minutes.")
            for k, label, kind in (DRIVER if role == "driver" else RIDER).get(category, ())}

def filing(category="no_show_charge", trip="T-NS0201", role="driver", **extra):
    body = {"category": category, "trip_id": trip, "filed_by": role,
            "description": "Please review this trip from my perspective.", "claim_amount_sgd": None,
            "answers": answers(category, role)}
    body.update(extra)
    return body

def record(category="route_deviation", pack=ORG_DIR, intake=None, replies=None):
    rec = copy.deepcopy(_record(pack, "RD-0103.json" if category == "route_deviation" else "NS-0201.json"))
    organiser = "dispute_ticket" in rec
    (rec["dispute_ticket"] if organiser else rec)["filed_by"] = "driver"
    block = rec.setdefault("ryde_extensions", {}) if organiser else rec
    block["intake"] = answers(category) if intake is None else intake
    block.pop("follow_up_answers", None)
    if replies is not None:
        block["follow_up_answers"] = replies
    return rec

def script(rider=(), driver=(), judge=None):
    return ScriptedLLM({"rider_advocate": _slot_advocate(rider), "driver_advocate": _slot_advocate(driver),
                        "judge": judge if judge is not None else judge_payload("no action", 0, ("NS-2", "NS-3"), .95)})

# Reuse the existing tested minimal DOM, not another DOM framework.
from tests.test_session_sixteen import _HARNESS
DOM = _HARNESS.split("const posted = [];")[0]
# Existing minimal DOM did not reflect label.htmlFor into the for attribute.
DOM = DOM.replace("  n.classList =", '  Object.defineProperty(n, "htmlFor", {get:()=>n._attrs.for || "",set:v=>{n._attrs.for=String(v);}});\n  n.classList =')
DRIVE = DOM + r'''
const opts = JSON.parse(process.env.DRIVE);
if (opts.role !== null) doc.getElementById("form-steps").setAttribute("data-filed-by", opts.role);
["step-trip","step-details","outcome","outcome-questions","category-error","trip-error","details-error","answers-error"].forEach(id=>doc.getElementById(id).hidden=true);
const calls=[];
let postCount=0;
const tick=()=>new Promise(r=>setTimeout(r,0));
const fetch=(url,o)=>{
  calls.push({url,method:o.method,body:o.body?JSON.parse(o.body):null});
  if(o.method==="GET") return Promise.resolve({ok:true,json:()=>Promise.resolve({trips:[{trip_id:"TRIP-X",label:"Trip",date:"2026",kind_label:"Ride",fare_sgd:6.61,charge_label:"fee"}]})});
  postCount++;
  if(opts.pending) return new Promise(()=>{});
  let view=postCount===1 ? (opts.view || {run_id:"run-first",dispute_id:"PF-DEMO",status:"needs_info",message:"<img src=x onerror=evil()>",questions:["First question?","Second question?"]}) : {run_id:"run-second",dispute_id:"PF-DEMO",status:"under_review",message:"Safe fixed message",questions:[]};
  return Promise.resolve({ok:true,json:()=>Promise.resolve(view)});
};
(async()=>{
vm.runInNewContext(fs.readFileSync(process.env.PARTY_JS,"utf8"),{document:doc,window:{scrollTo(){}},fetch,Promise,setTimeout,encodeURIComponent,JSON,Array,Number,isFinite,String});
const categories=doc.getElementById("category-options").children.map(c=>c.textContent);
async function choose(i){ const card=doc.getElementById("category-options").children[i]; if(!card)return false; card.click(); doc.getElementById("category-next").click(); await tick(); await tick(); const trip=doc.getElementById("trip-options").children[0]; if(!trip)return false; trip.click(); doc.getElementById("trip-next").click(); return true; }
function rows(){return doc.getElementById("question-list").children.map(f=>{const l=f.children[0],c=f.children[1],e=f.children[2];return {key:c.id.replace(/^answer-/,""),label:l.textContent,kind:c.tagName==="TEXTAREA"?"open":"yes_no",for:l.htmlFor,role:c.role,labelledBy:c.getAttribute("aria-labelledby"),labelId:l.id,pressed:c.children.map(x=>x.getAttribute("aria-pressed")),elaboration:e?e.getAttribute("aria-label"):null};});}
if(opts.role!==null && opts.role!=="driver" && opts.role!=="rider"){
  doc.getElementById("category-next").click(); doc.getElementById("details-form").fire("submit"); await tick();
  process.stdout.write(JSON.stringify({calls,categories,error:doc.getElementById("category-error").textContent,errorVisible:!doc.getElementById("category-error").hidden && !doc.getElementById("step-category").hidden && !doc.getElementById("form-steps").hidden}));return;
}
await choose(opts.category||0);
const initial=rows(), visible=["step-category","step-trip","step-details"].map(id=>!doc.getElementById(id).hidden);
const list=doc.getElementById("question-list");
for(const [op,key,arg] of (opts.steps||[])){
 const sel=op==="click"?'.choice-button[data-question-key="'+key+'"][data-choice="'+arg+'"]':op==="type"?'textarea[data-elaborate-for="'+key+'"]':'textarea[data-question-key="'+key+'"]';
 const n=list.querySelector(sel); if(!n)continue; if(op==="click")n.click();else n.value=arg;
}
let reset=null;
if(opts.switchCategory!==undefined){doc.getElementById("details-back").click();doc.getElementById("trip-back").click();doc.getElementById("category-options").children[opts.switchCategory].click();reset={tripDisabled:doc.getElementById("trip-next").disabled,tripCount:doc.getElementById("trip-options").children.length};await choose(opts.switchCategory);}
const finalRows=rows();
doc.getElementById("description").value=opts.description===undefined?"Driver submission":opts.description;
doc.getElementById("claim-amount").value=opts.amount||"";
doc.getElementById("details-form").fire("submit");await tick();await tick();
let ownBox=null,missingReplyPosts=null,replyDisabled=null;
if(opts.reply){const boxes=doc.getElementById("question-boxes");if(boxes.children.length){boxes.children[0].children[2].click();ownBox=boxes.querySelectorAll("textarea").map(x=>x.value);doc.getElementById("answers-submit").click();await tick();missingReplyPosts=postCount;boxes.querySelectorAll("textarea").forEach((x,i)=>{if(i)x.value="Reply "+i;});doc.getElementById("answers-submit").click();replyDisabled=doc.getElementById("answers-submit").disabled;await tick();await tick();}}
process.stdout.write(JSON.stringify({calls,categories,initial,finalRows,visible,reset,ownBox,missingReplyPosts,replyDisabled,title:doc.getElementById("outcome-title").textContent,message:doc.getElementById("outcome-message").textContent,reference:doc.getElementById("outcome-reference").textContent,detailsError:doc.getElementById("details-error").textContent,submitDisabled:doc.getElementById("details-submit").disabled}));
})().catch(e=>{process.stderr.write(String(e.stack||e));process.exit(1);});
'''

def drive(role=None, **options):
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node required")
    env = dict(os.environ, PARTY_JS=str(ROOT / "ui/party/party.js"), DRIVE=json.dumps(dict(role=role, **options)))
    result = subprocess.run([node, "-e", DRIVE], env=env, text=True, capture_output=True, timeout=20)
    if result.returncode:
        raise AssertionError("driven page failed: " + result.stderr)
    return json.loads(result.stdout)
