"""Verify native identity lifecycle on an SDK-free fixture application.

Requires an existing two-identity fixture recorded in out/evidence/
identity-final-qa.private.json (both set to America/New_York), compiled native
AX helpers in /tmp, and no other fixture probe server on port 18832.
Never uses the real user profile or a model provider.
"""
import json,pathlib,subprocess,os,time,signal,uuid
base=pathlib.Path.cwd();e=base/'out/evidence';s=json.loads((e/'identity-final-qa.private.json').read_text());root=pathlib.Path(s['root']);home=root/'identities';app=base/'out/identity-timezone-standalone-test/MetaBrowser.app/Contents/MacOS/Chromium'
assert not (app.parents[1]/'Frameworks/libmetabrowser_metacodes.dylib').exists(), 'Lifecycle fixture must not load the SDK'
assert not (app.parents[1]/'Resources/agentcore').exists(), 'Lifecycle fixture must not load AgentCore'
assert (root/'profile/.browser-broker-fixture-profile').exists()
entries={p.parent.name:json.loads(p.read_text()) for p in home.glob('*/identity.json')};ids=sorted(entries);assert len(ids)==2
logs=(e/'identity-lifecycle.private.log').open('w');os.chmod(logs.name,0o600)
env={k:v for k,v in os.environ.items() if not k.startswith(('METABROWSER_','OPENAI_','ANTHROPIC_','TINYKG_'))};env.update(METABROWSER_IDENTITY_HOME=str(home),METABROWSER_ACCOUNT_HOME=str(root/'account'),METABROWSER_CONVERSATION_HOME=str(root/'conversations'),METABROWSER_WORKSPACE=str(root/'workspace'))
parent=subprocess.Popen([str(app),'--user-data-dir='+str(root/'profile'),'--no-first-run','--no-default-browser-check','--hide-crash-restore-bubble','about:blank'],env=env,stdout=logs,stderr=logs,start_new_session=True)
ui_env=dict(os.environ,METABROWSER_UI_NO_ACTIVATE='1');children=[]
def wait(check,desc,seconds=25):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  v=check()
  if v:return v
  time.sleep(.15)
 raise AssertionError(desc)
def ui(pid,*args,activate=False):
 return subprocess.check_output(['/tmp/metabrowser-panel-ui' if activate else '/tmp/metabrowser-profile-ui',str(pid),*args],env=ui_env if not activate else os.environ,text=True,stderr=subprocess.PIPE)
def processes():
 rows=[]
 for line in subprocess.check_output(['ps','-axo','pid=,stat=,command='],text=True).splitlines():
  fields=line.strip().split(None,2)
  if len(fields)==3:rows.append((int(fields[0]),fields[1],fields[2]))
 return rows
def child(identity):
 token='--user-data-dir='+str(home/identity/'browser')
 return next((p for p,stat,cmd in processes() if str(app) in cmd and token in cmd.split() and '--type=' not in cmd and not stat.startswith('Z')),None)
def open_profile(identity):
 ui(parent.pid,'press','浏览器身份列表');time.sleep(.25);ui(parent.pid,'press',entries[identity]['name']);wait(lambda: 'AXTextField 浏览器身份名称 '+entries[identity]['name'] in ui(parent.pid,'dump').splitlines(),'selection commit');ui(parent.pid,'press','打开身份');p=wait(lambda:child(identity),'child start');children.append(p);return p
def probe(pid):
 wait(lambda:'AXTextField 地址和搜索栏' in ui(pid,'dump'), 'child address bar ready')
 run=str(uuid.uuid4());file=e/'identity-timezone-reports'/f'{run}.json';ui(pid,'navigate',f'http://127.0.0.1:18832/?run={run}',activate=True);wait(file.exists,'report',30);data=json.loads(file.read_text());assert 'error' not in data,data
 for k in ('window','iframe','dedicated','module','nested','shared','service'):
  assert data['report'][k]['timezone']=='America/New_York' and data['report'][k]['winter']==300 and data['report'][k]['summer']==240
 return file.name,data['report']['canvas']
server=None
try:
 server=subprocess.Popen(['python3','tests/integration/identity_timezone_probe.py','--output',str(e/'identity-timezone-reports')],stdout=logs,stderr=logs)
 wait(lambda:'AXButton 登录 Metask ' in ui(parent.pid,'dump'),'parent ready');ui(parent.pid,'press','登录 Metask',activate=True);time.sleep(.25);ui(parent.pid,'press','账户设置');wait(lambda:'身份时区' in ui(parent.pid,'dump') and '正在读取' not in ui(parent.pid,'dump'),'settings ready');time.sleep(.4)
 first=open_profile(ids[0]);a=probe(first)
 # Reactivate the parent's settings once, before opening the menu.
 ui(parent.pid,'dump',activate=True);time.sleep(.3)
 second=open_profile(ids[1]);b=probe(second);assert a[1]!=b[1],'distinct profile canvas'
 assert parent.poll() is None, 'parent alive before close'
 os.kill(second,signal.SIGTERM);wait(lambda:all(p!=second for p,_,_ in processes()),'closed child reaped')
 assert parent.poll() is None, 'parent must remain alive after child close'
 ui(parent.pid,'dump',activate=True);time.sleep(.3)
 second=open_profile(ids[1]);c=probe(second);assert b[1]==c[1],'stable canvas after restart'
 result={'passed':True,'seven_realm_timezone_dst':True,'distinct_profiles_canvas':True,'cold_restart_stable_canvas_timezone':True,'closed_child_reaped':True,'sdk_present':False,'paid_model_calls':0,'reports':[a[0],b[0],c[0]]};(e/'identity-global-final-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
finally:
 for pid in set(children):
  if any(p==pid and str(app) in cmd for p,_,cmd in processes()):
   try:os.kill(pid,signal.SIGTERM)
   except ProcessLookupError:pass
 time.sleep(.5);parent.terminate();parent.wait(timeout=15)
 if server and server.poll() is None:server.terminate();server.wait(timeout=5)
