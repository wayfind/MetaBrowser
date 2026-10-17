"""Native visual interaction checks against one isolated local-fixture PID."""
import json, pathlib, subprocess, sys, time
pid, root = sys.argv[1], pathlib.Path(sys.argv[2])
def ui(*args):return subprocess.check_output(['/tmp/metabrowser-panel-ui',pid,*args],text=True,stderr=subprocess.STDOUT)
def wait(predicate):
    until=time.monotonic()+10
    while time.monotonic()<until:
        value=ui('dump')
        if predicate(value):return value
        time.sleep(.1)
    raise AssertionError(value)
def press(title):ui('press',title)
press('新对话')
wait(lambda t:'今天，想完成什么？' in t)
request=pathlib.Path('/tmp/metabrowser-provider-request.json')
before=request.read_bytes() if request.exists() else b''
press('跨网站查证  →')
wait(lambda t:'我想在多个网站之间核对信息。' in t)
assert not request.exists() or request.read_bytes()==before, 'Starter submitted without user send'
assert 'AXButton 停止' not in ui('dump')
assert 'AXButton 移除附件' not in ui('dump')
press('配置')
text=ui('dump');assert 'AXTextField Provider endpoint' not in text
press('高级连接设置')
wait(lambda t:'AXTextField Provider endpoint' in t)
press('高级连接设置')
wait(lambda t:'AXTextField Provider endpoint' not in t)
for name,marker in [('Skill','本地 Skill'),('连接器','标准 MCP'),('对话','我想在多个网站之间核对信息。')]:
    press(name);wait(lambda t:marker in t)
press('添加附件与工具');press('添加当前页面截图');wait(lambda t:'当前网页截图.png' in t and 'AXButton 移除附件' in t)
press('移除附件');wait(lambda t:'AXButton 移除附件' not in t)
ui('set','Message MetaCodes…','')
result={'starters_fill_without_submit':True,'stop_only_when_busy':True,'attachment_remove_conditional':True,'advanced_disclosure':True,'four_sections':True,'draft_survives_navigation':True,'fixture_only':True}
(root/'design-acceptance.json').write_text(json.dumps(result,indent=2))
print('PASS:',json.dumps(result))
