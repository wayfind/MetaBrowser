"""Actual pinned SDK host-contract tests. Local fixture only; no paid providers."""
import base64, ctypes as C, http.server, json, os, pathlib, tempfile, threading
# Match native side_panel_hook.cc: non-built-in model capabilities come from
# the local fixture catalog, not a model-name heuristic. No paid endpoint.
os.environ["METACODES_MODEL_CATALOG_PROBE"] = "1"
LIB = C.CDLL(str(pathlib.Path(os.environ.get('METABROWSER_HOST_TEST_PLUGIN', 'zig-out/lib/libmetabrowser_metacodes.dylib')).resolve()))
libc=C.CDLL(None);libc.malloc.argtypes=[C.c_size_t];libc.malloc.restype=C.c_void_p
Event=C.CFUNCTYPE(None,C.c_void_p,C.c_uint32,C.c_void_p,C.c_uint64)
Request=C.CFUNCTYPE(C.c_uint32,C.c_void_p,C.c_uint32,C.c_char_p,C.c_void_p,C.c_uint64,C.POINTER(C.c_void_p),C.POINTER(C.c_uint64))
class Config(C.Structure):
 _fields_=[('size',C.c_uint32),('abi',C.c_uint32),('endpoint',C.c_char_p),('model',C.c_char_p),('key',C.c_char_p),('workspace',C.c_char_p),('event',Event),('context',C.c_void_p),('provider',C.c_uint32),('protocol',C.c_uint32),('shell',C.c_uint32),('turns',C.c_uint32),('request',Request),('home',C.c_char_p),('checkpoint',C.c_char_p)]
LIB.mb_mc_create.argtypes=[C.POINTER(Config)];LIB.mb_mc_create.restype=C.c_void_p
LIB.mb_mc_run_input.argtypes=[C.c_void_p,C.c_uint64,C.c_char_p]
LIB.mb_mc_control.argtypes=[C.c_void_p,C.c_char_p,C.c_char_p,C.POINTER(C.c_void_p),C.POINTER(C.c_uint64)]
LIB.mb_mc_free.argtypes=[C.c_void_p,C.c_uint64];LIB.mb_mc_destroy.argtypes=[C.c_void_p]
requests=[];events=[];ui=[];host=[];ui_status=1
class Provider(http.server.BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  assert self.path=='/v1/models'
  payload=json.dumps({'data':[{'id':name,'capabilities':{'image_input':{'supported':True}}} for name in ['glm-5.3-flash','MiniMax-M3']]}).encode()
  self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
 def do_POST(self):
  body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(body)
  messages=body['messages'];last=next((i for i in range(len(messages)-1,-1,-1) if messages[i]['role']=='user'),0)
  prompt=str(messages[last].get('content',''));results=[m for m in messages[last+1:] if m['role']=='tool']
  delta={'content':'host-contract-ok'};finish='stop'
  if not results and ('cancel-ui' in prompt or 'fatal-ui' in prompt):
   args=json.dumps({'file_path':str(work/'test-output.txt'),'content':'test-only'})
   delta={'tool_calls':[{'index':0,'id':'w','type':'function','function':{'name':'Write','arguments':args}}]};finish='tool_calls'
  elif not results and 'read-host' in prompt:
   delta={'tool_calls':[{'index':0,'id':'r','type':'function','function':{'name':'browser_tabs','arguments':'{}'}}]};finish='tool_calls'
  payload=('data: '+json.dumps({'choices':[{'index':0,'delta':delta,'finish_reason':None}]})+'\n\ndata: '+json.dumps({'choices':[{'index':0,'delta':{},'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n').encode()
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
@Event
def event(_,kind,p,n):events.append((kind,C.string_at(p,n)))
@Request
def request(_,kind,name,p,n,out,length):
 if kind==0:ui.append(json.loads(C.string_at(p,n)));return ui_status
 host.append(name.decode());payload=b'{"tabs":[]}'
 ptr=libc.malloc(len(payload));C.memmove(ptr,payload,len(payload));out[0]=ptr;length[0]=len(payload);return 0
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Provider)
threading.Thread(target=server.serve_forever,daemon=True).start()
def control(session,op,args=''):
 out=C.c_void_p();length=C.c_uint64();status=LIB.mb_mc_control(session,op.encode(),args.encode(),C.byref(out),C.byref(length));data=C.string_at(out,length.value) if out else b'';LIB.mb_mc_free(out,length);return status,(json.loads(data) if data else None)
def run(session,id,record):
 events.clear();status=LIB.mb_mc_run_input(session,id,json.dumps(record).encode());return status,list(events)
with tempfile.TemporaryDirectory(prefix='metabrowser-host-contract-') as directory:
 work=pathlib.Path(directory);skill=work/'.agents/skills/local-contract';skill.mkdir(parents=True)
 (skill/'SKILL.md').write_text('---\nname: local-contract\ndescription: Local host fixture\n---\nlocal-skill-contract $ARGUMENTS\n')
 cfg=Config(C.sizeof(Config),2,f'http://127.0.0.1:{server.server_port}/v1/chat/completions'.encode(),b'gpt-4.1-mini',b'fixture',str(work).encode(),event,None,2,0,2,4,request,str(work).encode(),None)
 session=LIB.mb_mc_create(C.byref(cfg));assert session,events
 try:
  status,ev=run(session,1,{'text':'context-check','context_blocks':[{'label':'currentDate','text':'Today is 2026-10-15.'}]});assert status==0,ev
  assert 'You are MetaBrowser' in str(requests[-1]['messages'])
  assert 'Today is 2026-10-15.' in str(requests[-1]['messages'])
  assert any(k==12 and json.loads(v)['session_id'] for k,v in ev)
  assert any(k==13 and json.loads(v)['lifecycle']=='idle' for k,v in ev)
  ui.clear();status,ev=run(session,2,{'text':'read-host'});assert status==0 and host==['browser_tabs'] and not ui,(status,ui,host)
  status,ev=run(session,3,{'text':'cancel-ui'});assert status==0 and ui,ev
  assert not (work/'test-output.txt').exists()
  assert control(session,'describe')[1]['lifecycle']=='idle'
  status,ev=run(session,4,{'text':'after-cancel'});assert status==0 and any(k==0 for k,v in ev),ev
  png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aB5kAAAAASUVORK5CYII='
  status,ev=run(session,5,{'kind':'multimodal','parts':[{'kind':'text','text':'image-check'},{'kind':'image','media_type':'image/png','data':png}]});assert status==0,ev
  assert 'image_url' in str(requests[-1]['messages'])
  status,catalog=control(session,'skills');assert status==0,catalog
  selected=next(s for s in catalog['skills'] if s['invocation_name']=='local-contract')
  assert control(session,'skill_grant',selected['skill_id'])[0]==0
  status,ev=run(session,6,{'kind':'skill','skill_id':selected['skill_id'],'catalog_revision':catalog['catalog_revision'],'arguments_json':'{"values":["fixture-arg"]}'});assert status==0,ev
  assert 'local-skill-contract' in str(requests[-1]['messages']) and 'fixture-arg' in str(requests[-1]['messages'])
  checkpoint=str(work/'committed.checkpoint');assert control(session,'checkpoint',checkpoint)[0]==0
  ui_status=2;status,ev=run(session,7,{'text':'fatal-ui'});assert status!=0,ev
  assert any(k==13 and json.loads(v)['lifecycle']=='poisoned' for k,v in ev),ev
  assert run(session,8,{'text':'must-not-run'})[0]!=0
 finally:LIB.mb_mc_destroy(session)
 cfg.checkpoint=checkpoint.encode();session=LIB.mb_mc_create(C.byref(cfg));assert session,events
 try:
  status,ev=run(session,1,{'text':'restored-context'});assert status==0,ev
  assert any(k==13 and json.loads(v)['run_id']>6 for k,v in ev)
 finally:LIB.mb_mc_destroy(session)
# Actual production model identifiers must pass native SDK image preflight too.
with tempfile.TemporaryDirectory(prefix='metabrowser-image-contract-') as directory:
 cfg.workspace=directory.encode();cfg.home=directory.encode();cfg.checkpoint=None
 for model in [b'glm-5.3-flash',b'MiniMax-M3']:
  cfg.model=model;session=LIB.mb_mc_create(C.byref(cfg));assert session
  try:
   status,ev=run(session,1,{'kind':'multimodal','parts':[{'kind':'text','text':'image-check'},{'kind':'image','media_type':'image/png','data':png}]});assert status==0,(model,status,ev)
  finally:LIB.mb_mc_destroy(session)
server.shutdown()
print('PASS: native identity/context/events, read policy, reusable UI cancellation, multimodal wire, granted typed Skill, poison isolation and committed checkpoint recovery')
