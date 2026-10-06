"""Extend the existing runtime DOM seam with controlled trip reload outcomes."""
import json
import os
import shutil
import subprocess
from tests.w20_support import HARNESS, ROOT

OLD_FETCH = "const fetch=(url,o)=>{calls.push({url,method:o.method,body:o.body?JSON.parse(o.body):null});return o.method==='GET'?Promise.resolve({ok:true,json:()=>Promise.resolve({trips:['A','B'].map(trip_id=>({trip_id,label:trip_id}))})}):new Promise(()=>{});};"
NEW_FETCH = """let manual=false,trips=['A','B'];const pending=[];
const fetch=(url,o)=>{
 calls.push({url,method:o.method,body:o.body?JSON.parse(o.body):null});
 if(o.method!=='GET')return new Promise(()=>{});
 const list=trips===null?null:trips.slice();
 const response=()=>list===null
   ? {ok:false,json:()=>Promise.resolve({error:'Trips unavailable'})}
   : {ok:true,json:()=>Promise.resolve({trips:list.map(trip_id=>({trip_id,label:trip_id}))})};
 if(!manual)return Promise.resolve(response());
 return new Promise(resolve=>pending.push(()=>resolve(response())));
};"""
OP = " if(op[0]==='id')doc.getElementById(op[1]).click();"
assert HARNESS.count(OLD_FETCH)==1
assert HARNESS.count(OP)==1
RELOAD_HARNESS=HARNESS.replace(OLD_FETCH,NEW_FETCH).replace(OP,OP+"""
 if(op[0]==='manual')manual=op[1];
 if(op[0]==='trips')trips=op[1];
 if(op[0]==='resolve'){const f=pending.splice(op[1]||0,1)[0];if(f)f();}
""")

def drive(role,category,ops):
    node=shutil.which('node')
    assert node, 'Node required'
    env=dict(os.environ,PARTY_JS=str(ROOT/'ui/party/party.js'),W20=json.dumps(dict(role=role,category=category,ops=ops)))
    result=subprocess.run([node,'-e',RELOAD_HARNESS],env=env,text=True,capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)
