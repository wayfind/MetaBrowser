"""Native packaged-window acceptance. Explicit fixture PID and isolated workspace."""
import json, pathlib, subprocess, sys, time

pid, root = sys.argv[1], pathlib.Path(sys.argv[2])
helper = '/tmp/metabrowser-panel-ui'
def ui(*args):
    return subprocess.check_output([helper,pid,*args],text=True,stderr=subprocess.STDOUT)
def wait(label, predicate, seconds=15):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        text=ui('dump')
        if predicate(text):return text
        time.sleep(.1)
    raise AssertionError(label+'\n'+text)
def press(title):ui('press',title)
def send(text):ui('set','Message MetaCodes…',text);press('发送')
def complete(marker):
    return wait(marker,lambda s:marker in s and 'AXButton 停止' not in s)
def governed(marker):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        text=ui('dump')
        if 'AXButton 允许本次操作' in text:press('允许本次操作')
        if marker in text and 'AXButton 停止' not in text:return
        time.sleep(.1)
    raise AssertionError('Governed task incomplete: '+marker+'\n'+text)

complete('Local capability fixture')
if 'native browser action verified' not in ui('dump'):
    send('browser-fixture')
    wait('mutation approval',lambda s:'AXButton 允许本次操作' in s)
    press('允许本次操作')
    complete('native browser action verified')
send('visual-fixture');complete('tool image reached provider')
send('coding-fixture');governed('coding verified')
assert (root/'workspace/agent-result.txt').exists()
press('连接器');press('应用连接配置')
wait('explicit MCP configuration',lambda s:'服务目录已更新' in s)
press('对话');send('mcp-fixture');governed('MCP verified')
press('Skill');press('刷新 Skill')
wait('same-runtime Skill catalogue',lambda s:'AXButton 停止' not in s)
press('选择 Skill');wait('workspace Skill choice',lambda s:'AXMenuItem ui-fixture' in s);press('ui-fixture')
wait('committed Skill selection',lambda s:'AXPopUpButton 选择 Skill ui-fixture' in s)
press('授权此 Skill');wait('Skill grant',lambda s:'已授权选中的 Skill' in s)
press('运行选中的 Skill');complete('运行 Skill · ui-fixture')
request=json.loads(pathlib.Path('/tmp/metabrowser-provider-request.json').read_text())
assert 'ui-skill-fixture' in str(request['messages'])
press('添加附件与工具');press('添加当前页面截图');wait('typed screenshot attachment',lambda s:'当前网页截图.png' in s)
send('native-attachment-check');complete('native-attachment-check')
request=json.loads(pathlib.Path('/tmp/metabrowser-provider-request.json').read_text())
assert 'image_url' in str(request['messages'])
send('cancel-check native redesign')
wait('actual streaming',lambda s:'cancel-check stream' in s)
press('停止');wait('cancel terminal',lambda s:'已停止' in s or 'AXButton 停止' not in s)
send('after-stop-redesign');complete('after-stop-redesign')
press('新对话');wait('independent tab',lambda s:'AXButton 对话 2' in s)
send('independent-tab-redesign');complete('independent-tab-redesign')
ui('set','Message MetaCodes…','draft-preserved-redesign')
time.sleep(.5)
press('对话 1')
text=ui('dump');assert 'after-stop-redesign' in text and 'independent-tab-redesign' not in text
press('关闭对话 2');press('历史')
wait('durable history',lambda s:'AXButton independent-tab-redesign' in s)
press('independent-tab-redesign')
text=wait('reopened history',lambda s:'draft-preserved-redesign' in s)
assert 'independent-tab-redesign' in text
press('连接器');press('刷新连接状态')
wait('real MCP readback',lambda s:'个工具' in s)
press('对话')
result={'native_browser_action':True,'permission':True,'visual_tool':True,'coding':True,'mcp':True,'skill_same_runtime':True,'typed_attachment':True,'cancel_and_continue':True,'independent_tabs':True,'history_reopen':True,'draft':True,'fixture_only':True}
(root/'native-acceptance.json').write_text(json.dumps(result,indent=2))
print('PASS:',json.dumps(result))
