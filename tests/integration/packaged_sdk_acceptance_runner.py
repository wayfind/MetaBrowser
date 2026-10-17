"""Run the real packaged browser/SDK against owned loopback fixtures only."""
import argparse,hashlib,http.server,json,os,secrets,socket,subprocess,tempfile,threading,time
from pathlib import Path
from capability_fixture import Handler

p=argparse.ArgumentParser(description=__doc__)
for n in ('app','manifest','ui-helper','output'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();app=a.app.resolve(strict=True);here=Path(__file__).resolve().parent;project=here.parents[1]
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
subprocess.run(['python3',str(project/'scripts/app-manifest.py'),str(app),'--check',str(a.manifest)],check=True)
subprocess.run(['python3',str(project/'scripts/check-agentcore-bundle.py'),str(app/'Contents/Resources/agentcore')],check=True)
for port in (18794,18796):
 with socket.socket() as s:s.bind(('127.0.0.1',port))
root=Path(tempfile.mkdtemp(prefix='metabrowser-packaged-sdk-')).resolve()
(root/'.metabrowser-owned-fixture').write_text('packaged-sdk-loopback')
workspace=root/'workspace';skill=workspace/'.agents/skills/ui-fixture';skill.mkdir(parents=True)
(skill/'SKILL.md').write_text('---\nname: ui-fixture\ndescription: Native UI local fixture\n---\nReply with ui-skill-fixture $ARGUMENTS\n')
mcp=root/'mcp.json';mcp.write_text(json.dumps({'revision':1,'servers':[{'name':'fixture','url':'http://127.0.0.1:18794/mcp','tools':['echo']}]}))
token=secrets.token_hex(32)
env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
env.update(METABROWSER_API_KEY='fixture',METABROWSER_PROVIDER='openai',METABROWSER_MODEL='gpt-4.1-mini',METABROWSER_ENDPOINT='http://127.0.0.1:18794/v1/chat/completions',METABROWSER_WORKSPACE=str(workspace),METABROWSER_IDENTITY_HOME=str(root/'identities'),METABROWSER_CONVERSATION_HOME=str(root/'conversations'),METABROWSER_ACCOUNT_HOME=str(root/'account'),METABROWSER_MCP_CONFIG=str(mcp),METABROWSER_AGENT_PORT='18796',METABROWSER_AGENT_TOKEN=token)
sources=[Path(__file__).resolve(),here/'capability_fixture.py',here/'native_redesign_test.py']
report={'root':str(root),'completed':False,'clean_shutdown':False,'paid_model_calls':0,'fixture_only':True,'full_scope_complete':False,'framework_sha256':digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),'plugin_sha256':digest(app/'Contents/Frameworks/libmetabrowser_metacodes.dylib'),'manifest_sha256':digest(a.manifest),'probe_sha256':{str(f):digest(f) for f in sources}}
def save():
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n');a.output.chmod(0o600)
server=http.server.ThreadingHTTPServer(('127.0.0.1',18794),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();process=None
try:
 with a.output.with_suffix('.runtime.log').open('w') as log:
  os.fchmod(log.fileno(),0o600)
  command=[str(app/'Contents/MacOS/Chromium'),'--user-data-dir='+str(root/'browser'),'--use-mock-keychain','--disable-component-update','--disable-background-networking','--no-first-run','--no-default-browser-check','--hide-crash-restore-bubble','--metacodes-demo-prompt=redesign-first-turn','http://127.0.0.1:18794/?acceptance=local']
  process=subprocess.Popen(command,env=env,stdout=log,stderr=log,start_new_session=True);report['pid']=process.pid;save()
  for _ in range(120):
   assert process.poll() is None,'Owned SDK browser exited'
   result=subprocess.run([str(a.ui_helper),str(process.pid),'dump'],capture_output=True,text=True,timeout=10)
   if result.returncode==0 and 'Local capability fixture' in result.stdout and 'AXButton 停止' not in result.stdout:break
   time.sleep(.25)
  else:raise TimeoutError('Owned SDK fixture readiness')
  test=subprocess.run(['python3',str(here/'native_redesign_test.py'),str(process.pid),str(root)],capture_output=True,text=True,timeout=240)
  (root/'native-test-process.json').write_text(json.dumps({'exit_code':test.returncode,'stdout':test.stdout,'stderr':test.stderr},indent=2));report['test_exit_code']=test.returncode
  assert test.returncode==0,test.stderr[-4000:]
  report['checks']=json.loads((root/'native-acceptance.json').read_text());assert all(report['checks'].values())
  subprocess.run([str(a.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=15)
  process.wait(timeout=25);assert process.returncode==0
  assert all(digest(Path(n))==h for n,h in report['probe_sha256'].items())
  report.update(completed=True,clean_shutdown=True)
except BaseException as error:report['error']=str(error);raise
finally:
 if process and process.poll() is None:process.terminate();process.wait(timeout=20)
 server.shutdown();server.server_close();save()
print(json.dumps({'completed':report['completed'],'checks':report.get('checks'),'paid_model_calls':0,'full_scope_complete':False}))
