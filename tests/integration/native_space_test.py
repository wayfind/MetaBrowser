"""Exercise actual native geometry and tab lifecycle in an isolated fixture."""
import json,pathlib,re,subprocess,sys,time
pid,root=sys.argv[1],pathlib.Path(sys.argv[2])
helper='/tmp/metabrowser-panel-ui'
def ui(*args):return subprocess.check_output([helper,pid,*map(str,args)],text=True,stderr=subprocess.STDOUT)
def wait(predicate):
    end=time.monotonic()+12
    while time.monotonic()<end:
        value=ui('dump')
        if predicate(value):return value
        time.sleep(.1)
    raise AssertionError(value)
def tabs(text=None):return re.findall(r'^AXButton 对话 (\d+) ',text or ui('dump'),re.M)
def press(name):ui('press',name)
def bounds(name):
    rows=json.loads(ui('bounds',name));assert rows,name;return rows[0]
def settle_height(expected):
    end=time.monotonic()+8
    while time.monotonic()<end:
        b=bounds('Message MetaCodes…')
        if abs(b['height']-expected)<=1:return b
        time.sleep(.1)
    raise AssertionError(b)
request=pathlib.Path('/tmp/metabrowser-provider-request.json')
before=request.read_bytes() if request.exists() else b''
window=bounds('AXWindow')
press('新对话');n=len(tabs());ui('set','Message MetaCodes…','space-active-draft')
press('关闭对话 1')
wait(lambda t:len(tabs(t))==n-1 and 'space-active-draft' in t)
active=n-1
press('新对话');n=len(tabs());ui('set','Message MetaCodes…','space-background-draft')
press('对话 '+str(active));wait(lambda t:'space-active-draft' in t)
press('关闭对话 '+str(n));wait(lambda t:len(tabs(t))==n-1 and 'space-active-draft' in t)
ui('set','Message MetaCodes…','short');short=settle_height(22)
ui('set','Message MetaCodes…','\n'.join('line '+str(i) for i in range(9)));long=settle_height(112)
ui('set','Message MetaCodes…','');settle_height(22)
tab=bounds('对话 1');close=bounds('关闭对话 1');panel_close=bounds('关闭侧边栏')
assert abs(panel_close['y']-tab['y'])<=2,(tab,panel_close)
assert close['width']>=24 and close['height']>=28,close
assert abs(close['y']-tab['y'])<=1 and 0<=close['x']-(tab['x']+tab['width'])<=2,(tab,close)
ui('resize',int(window['width']),600)
wait(lambda _:bounds('AXWindow')['height']<=601)
short_window=bounds('AXWindow');input_box=bounds('Message MetaCodes…');send=bounds('发送')
assert 0<=send['y']-(input_box['y']+input_box['height'])<=8,(input_box,send)
assert bounds('发送')['x']>bounds('模型与推理强度')['x']
assert abs(bounds('上下文用量')['y']+bounds('上下文用量')['height']/2-(send['y']+send['height']/2))<=2
for box in [input_box,send,bounds('关闭侧边栏')]:
    assert short_window['y']<=box['y'] and box['y']+box['height']<=short_window['y']+short_window['height'],(short_window,box)
window_id=ui('window').strip();subprocess.run(['screencapture','-x','-l',window_id,str(root/'space-short-window.png')],check=True)
ui('resize',int(window['width']),int(window['height']))
ui('set','Message MetaCodes…','space-close-reopen-draft')
if '取消固定到工具栏' not in ui('dump'):press('固定到工具栏')
wait(lambda t:'取消固定到工具栏' in t)
press('关闭侧边栏');wait(lambda t:'Message MetaCodes…' not in t)
press('MetaCodes - 已固定' if 'MetaCodes - 已固定' in ui('dump') else 'MetaCodes');wait(lambda t:'space-close-reopen-draft' in t)
# Eight tabs must keep the selected item visible without a second scrollbar row.
while len(tabs())<8:
    count=len(tabs());press('新对话');wait(lambda t:len(tabs(t))==count+1)
wait(lambda _:bounds('关闭对话 8')['x']+bounds('关闭对话 8')['width']<=bounds('历史')['x']+1)
assert not bounds('新对话')['enabled']
assert bounds('关闭对话 8')['x']>=bounds('AXWindow')['x']
# Closing the final conversation must create a usable new one, not an empty panel.
for _ in range(len(tabs())-1):
    count=len(tabs());press('对话 1');press('关闭对话 1');wait(lambda t:len(tabs(t))==count-1)
press('关闭对话 1');wait(lambda t:'今天，想完成什么？' in t and 'space-close-reopen-draft' not in t)
assert len(tabs())==1
press('配置');press('高级连接设置');assert 'AXTextField Model gpt-4.1-mini' in ui('dump');press('对话')
assert not request.exists() or request.read_bytes()==before,'Layout actions submitted an inference request'
for record in (root/'conversations').glob('*.json'):
    stored=json.loads(record.read_text());assert 'private_controls' not in stored and 'oauth_key' not in stored
result={'private_controls_stay_in_memory':True,'single_toolbar_row':True,'close_target_contained':True,'close_target_size':[close['width'],close['height']],'inactive_close_preserves_active':True,'eight_tabs_selected_visible':True,'tab_limit_enforced':True,'last_tab_preserves_model':True,'composer_short':short['height'],'composer_long_cap':long['height'],'short_window_controls_visible':True,'pin_close_reopen_draft':True,'last_tab_remains_usable':True,'inference_request_sent':False,'toolbar_bounds':{'tab':tab,'sidebar_close':panel_close},'short_window':short_window}
(root/'space-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS:',json.dumps(result))
