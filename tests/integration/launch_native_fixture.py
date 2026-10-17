"""QA launcher only. No real account, real provider or paid API requests."""
import json, os, pathlib, secrets, tempfile, urllib.request
root=pathlib.Path(__file__).resolve().parents[2]
assert urllib.request.urlopen('http://127.0.0.1:18794/v1/models',timeout=2).status==200
qa=pathlib.Path(tempfile.mkdtemp(prefix='metabrowser-native-acceptance-'))
(root/'out/evidence/redesign-qa-root.txt').write_text(str(qa))
work=qa/'workspace';work.mkdir()
skill=work/'.agents/skills/ui-fixture';skill.mkdir(parents=True)
(skill/'SKILL.md').write_text('---\nname: ui-fixture\ndescription: Native UI local fixture\n---\nReply with ui-skill-fixture $ARGUMENTS\n')
mcp=qa/'mcp.json';mcp.write_text(json.dumps({'revision':1,'servers':[{'name':'fixture','url':'http://127.0.0.1:18794/mcp','tools':['echo']}]}))
token=secrets.token_hex(32);(qa/'agent-token').write_text(token);(qa/'agent-token').chmod(0o600)
env=os.environ.copy()
env.update(METABROWSER_API_KEY='fixture',METABROWSER_PROVIDER='openai',METABROWSER_MODEL='gpt-4.1-mini',METABROWSER_ENDPOINT='http://127.0.0.1:18794/v1/chat/completions',METABROWSER_WORKSPACE=str(work),METABROWSER_CONVERSATION_HOME=str(qa/'conversations'),METABROWSER_ACCOUNT_HOME=str(qa/'account'),METABROWSER_MCP_CONFIG=str(mcp),METABROWSER_AGENT_PORT='18796',METABROWSER_AGENT_TOKEN=token)
app=root/'out/macos-arm64/MetaBrowser.app/Contents/MacOS/Chromium'
print('Local fixture PID:',os.getpid(),flush=True)
os.execve(app,[str(app),'--user-data-dir='+str(qa/'profile'),'--disable-component-update','--disable-background-networking','--no-first-run','--no-default-browser-check','--hide-crash-restore-bubble','--metacodes-demo-prompt=redesign-first-turn','http://127.0.0.1:18794/?acceptance=local'],env)
