"""Native A2A lifecycle; local fixture only. Requires explicit test token."""
import json,os,time,urllib.request,uuid
url=os.environ.get('METABROWSER_AGENT_URL','http://127.0.0.1:18795')+'/a2a'
headers={'Authorization':'Bearer '+os.environ['METABROWSER_AGENT_TOKEN'],'Content-Type':'application/json','A2A-Version':'1.0'}
def rpc(method,params):
    req=urllib.request.Request(url,headers=headers,data=json.dumps({'jsonrpc':'2.0','id':str(uuid.uuid4()),'method':method,'params':params}).encode())
    return json.load(urllib.request.urlopen(req,timeout=10))
message={'messageId':str(uuid.uuid4()),'role':'ROLE_USER','parts':[{'text':'cancel-check fixture lifecycle'}]}
task=rpc('SendMessage',{'message':message})['result']['task'];ident=task['id']
assert rpc('SendMessage',{'message':message})['result']['task']['id']==ident
other={**message,'parts':[{'text':'different text'}]}
assert 'error' in rpc('SendMessage',{'message':other})
for _ in range(100):
    task=rpc('GetTask',{'id':ident})['result']
    if task.get('artifacts'):break
    time.sleep(.05)
assert task.get('artifacts'),'No actual stream before cancel'
time.sleep(float(os.environ.get('METABROWSER_CANCEL_DELAY','0')))
assert rpc('CancelTask',{'id':ident})['result']['metadata']['cancelRequested']
for _ in range(200):
    task=rpc('GetTask',{'id':ident})['result']
    if task['status']['state']=='TASK_STATE_CANCELED':break
    time.sleep(.05)
assert task['status']['state']=='TASK_STATE_CANCELED',task['status']
print('PASS: native A2A message idempotency, conflict rejection, real streamed task and terminal cancellation')
