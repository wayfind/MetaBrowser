"""Exercise native prompt menus and prove reasoning reaches a loopback provider."""
import json, pathlib, subprocess, sys, time

pid, root = sys.argv[1], pathlib.Path(sys.argv[2])
def ui(*args):
    return subprocess.check_output(['/tmp/metabrowser-panel-ui', pid, *args], text=True, stderr=subprocess.STDOUT)
def wait(predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        value = ui('dump')
        if predicate(value): return value
        time.sleep(.1)
    raise AssertionError(value)
def press(label): ui('press', label)
def idle(text): return 'AXButton 停止' not in text
def selected(): wait(lambda t: idle(t) and 'AXMenuItem' not in t)
def send(text, model, effort):
    ui('set', 'Message MetaCodes…', text)
    wait(lambda _: json.loads(ui('bounds', '发送'))[0]['enabled'])
    press('发送')
    deadline = time.monotonic()+15
    while time.monotonic()<deadline:
        request = json.loads(pathlib.Path('/tmp/metabrowser-provider-request.json').read_text())
        if (request.get('model')==model and text in str(request.get('messages', []))
                and (request.get('reasoning_effort')==effort or request.get('reasoning', {}).get('effort')==effort or request.get('thinking', {}).get('type')==effort)):
            wait(idle); return request
        time.sleep(.1)
    raise AssertionError({'model':request.get('model'), 'reasoning_effort':request.get('reasoning_effort')})

wait(idle)
press('添加附件与工具')
menu = wait(lambda t: '上传图片…' in t)
for item in ['上传附件…', '添加当前页面截图', '使用 Skill…', '使用 MCP 连接器…']:
    assert item in menu, item
press('使用 MCP 连接器…'); wait(lambda t: '标准 MCP' in t)
press('对话'); press('添加附件与工具'); press('使用 Skill…')
wait(lambda t: '本地 Skill' in t and idle(t))
press('对话'); press('配置')
if 'AXTextField Model' not in ui('dump'): press('高级连接设置')
ui('set', 'Model', 'gpt-5.2')
press('对话'); press('模型与推理强度')
menu=wait(lambda t: 'AXMenuItem 推理强度' in t)
assert '刷新模型能力与上下文' not in menu
press('推理强度'); choices=wait(lambda t: '深入' in t)
for label in ['最低','轻量','标准','深入','最高']:assert label in choices
assert 'AXMenuItem 关闭' not in choices
press('深入'); selected()
request = send('composer-reasoning-check-'+str(time.time_ns()), 'gpt-5.2', 'high')
assert request['model'] == 'gpt-5.2'
assert request.get('reasoning_effort') == 'high' or request.get('reasoning', {}).get('effort') == 'high', request.keys()
assert 'composer-reasoning-check' in str(request['messages'])
press('配置'); ui('set', 'Model', 'MiniMax-M3'); press('对话')
press('模型与推理强度'); wait(lambda t: 'AXMenuItem 推理强度' in t)
press('推理强度')
choices = wait(lambda t: '自适应' in t and '开启思考' in t)
for label in ['关闭', '自适应', '开启思考']: assert label in choices
assert 'AXMenuItem 标准' not in choices and 'AXMenuItem 最高' not in choices
press('自适应'); selected()
request = send('composer-minimax-check-'+str(time.time_ns()), 'MiniMax-M3', 'adaptive')
assert request['model'] == 'MiniMax-M3' and request['thinking']['type'] == 'adaptive'
assert 'reasoning_effort' not in request
press('配置'); ui('set', 'Model', 'kimi-k3'); press('对话')
press('模型与推理强度'); wait(lambda t:'AXMenuItem 推理强度' in t);press('推理强度')
choices=wait(lambda t:'最高' in t)
assert 'AXMenuItem 标准' not in choices
press('最高');selected()
request=send('composer-kimi-check-'+str(time.time_ns()), 'kimi-k3', 'max')
assert request['reasoning_effort']=='max'
flow=ui('dump')
assert '\nAXStaticText 你\n' not in flow and '\nAXStaticText Metask\n' not in flow
ring=json.loads(ui('bounds','上下文用量'))[0]
assert 26<=ring['width']<=40 and ring['height']>=26
press('上下文用量'); menu=wait(lambda t: 'AXMenuItem 压缩上下文' in t)
assert '刷新上下文用量' not in menu
assert [line.strip() for line in menu.splitlines() if line.startswith('AXMenuItem ') and line[len('AXMenuItem '):].strip()]==['AXMenuItem 压缩上下文']
ui('cancel-menu'); selected()
window = ui('window').strip()
subprocess.run(['screencapture', '-x', '-l', window, str(root/'composer-final.png')], check=True)
result = {'plus_menu': True, 'skill_and_mcp_navigation': True, 'model_reasoning_menu': True,
          'reasoning_reaches_provider': True, 'catalogue_five_levels': True,
          'minimax_three_states': True, 'kimi_three_levels_max_on_wire': True,
          'used_context_ring': True, 'no_role_headings': True,
          'context_compact_only_menu': True, 'fixture_only': True}
(root/'composer-acceptance.json').write_text(json.dumps(result, indent=2)+'\n')
print('PASS:', json.dumps(result))
