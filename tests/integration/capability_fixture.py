"""Test-only provider and MCP endpoints. No paid service or production credentials."""
import http.server, json, pathlib, sys, time
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*_): pass
    def send_json(self,value,status=200):
        data=json.dumps(value).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path=='/v1/models':return self.send_json({'data':[{'id':'gpt-4.1-mini','capabilities':{'image_input':{'supported':True}}},{'id':'gpt-5.2','capabilities':{'effort':{level:{'supported':True} for level in ['minimal','low','medium','high','xhigh']}}}]})
        page=b'''<!doctype html><title>Native browser fixture</title><h1>Browser fixture</h1><label>Name<input aria-label="Name" id="name"></label><button onclick="document.querySelector('h1').textContent='Action verified'">Apply</button>'''
        self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(page)));self.end_headers();self.wfile.write(page)
    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path=='/api/oauth/device/code':
            assert request.get('client_id')=='metacodes'
            return self.send_json({'device_code':'fixture-device','user_code':'TEST-1234','verification_uri':'http://127.0.0.1:18794/device','expires_in':30,'interval':1})
        if self.path=='/api/oauth/token':
            return self.send_json({'access_token':'fixture-account-token','refresh_token':'fixture-refresh-token','token_type':'Bearer','expires_in':3600,'gateway_url':'http://127.0.0.1:18794','models_url':'http://127.0.0.1:18794/v1/models'})
        if self.path=='/mcp': return self.send_json(mcp_response(request))
        if self.path=='/mcp-sse':
            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
            self.wfile.write(b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info","data":"fixture notification"}}\n\n')
            self.wfile.write(('event: message\ndata: '+json.dumps(mcp_response(request))+'\n\n').encode());self.wfile.flush();time.sleep(3);return
        if 'contents' in request:
            assert 'gemini' in request.get('model','gemini')
            return self.events([{'candidates':[{'content':{'role':'model','parts':[{'text':'provider-gemini-verified'}]},'finishReason':'STOP'}],'usageMetadata':{'promptTokenCount':1,'candidatesTokenCount':1}}])
        if 'input' in request:
            assert request.get('model')=='gpt-4.1-mini'
            return self.events([{'type':'response.created','response':{'id':'r','status':'in_progress'}},{'type':'response.output_item.added','output_index':0,'item':{'id':'m','type':'message','role':'assistant','content':[]}},{'type':'response.output_text.delta','item_id':'m','output_index':0,'delta':'provider-responses-verified'},{'type':'response.completed','response':{'id':'r','status':'completed','usage':{'input_tokens':1,'output_tokens':1}}}])
        if 'anthropic-version' in self.headers:
            assert request.get('model')=='claude-sonnet-4-5'
            return self.events([{'type':'message_start','message':{'id':'m','role':'assistant','model':request['model'],'usage':{'input_tokens':1,'output_tokens':1}}},{'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}},{'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'provider-anthropic-verified'}},{'type':'content_block_stop','index':0},{'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':1}},{'type':'message_stop'}])
        pathlib.Path('/tmp/metabrowser-provider-request.json').write_text(json.dumps(request))
        messages=request.get('messages',[])
        tools={t['function']['name'] for t in request.get('tools',[]) if t.get('type')=='function'}
        def synthetic_image_result(message):
            content=message.get('content')
            return isinstance(content,list) and content and content[0].get('text','').startswith('Image result of tool call ')
        selected=[(i,m) for i,m in enumerate(messages) if m.get('role')=='user' and not synthetic_image_result(m)]
        start,user=selected[-1] if selected else (-1,{})
        prompt=str(user.get('content',''))
        results=[m for m in messages[start+1:] if m.get('role')=='tool'];last=str(results[-1].get('content','')) if results else ''
        calls=[]; text='Local capability fixture: complete'
        def call(name,args):
            assert name in tools,(name,sorted(tools));calls.append({'index':0,'id':f'call_{len(results)}','type':'function','function':{'name':name,'arguments':json.dumps(args)}})
        if 'coding-fixture' in prompt:
            if not results:call('Write',{'file_path':'agent-result.txt','content':'real SDK file tool\n'})
            elif len(results)==1:call('Read',{'file_path':'agent-result.txt'})
            elif len(results)==2:call('Bash',{'command':'printf native-shell-result','timeout':5000})
            else:text='Local capability fixture: coding verified '+last
        elif 'mcp-fixture' in prompt:
            name=next((t for t in tools if t.startswith('mcp__')),'')
            if not results:call(name,{'text':'native-mcp-roundtrip'})
            else:text='Local capability fixture: MCP verified '+last
        elif 'browser-fixture' in prompt:
            assert len(results)<10,'Browser fixture exceeded its bounded retry limit'
            snapshot=json.loads(last) if results else {}
            acted=any(json.loads(m['content']).get('status')=='dispatched' for m in results)
            if 'error' in snapshot and 'Accessibility initializing' in last:
                call('browser_wait',{'condition':'element','name':'Apply','role':'button','timeout_ms':3000})
            elif 'nodes' not in snapshot:call('browser_observe',{})
            elif 'Action verified' in last:text='Local capability fixture: native browser action verified'
            elif acted:call('browser_observe',{})
            else:
                button=next(n for n in snapshot['nodes'] if n.get('name')=='Apply')
                call('browser_act',{'observation_id':snapshot['observation_id'],'target':button['ref'],'op':'click'})
        elif 'visual-fixture' in prompt:
            if not results:call('browser_observe',{'mode':'visual'})
            else:
                assert any('image_url' in str(m.get('content','')) for m in messages[start+1:]),'Image was not sent to the provider'
                assert 'coordinate_space' in str(messages[start+1:]),'Browser image metadata was not sent to the provider'
                text='Local capability fixture: tool image reached provider'
        elif 'delegate-fixture' in prompt:
            if not results:call('browser_status',{})
            elif len(results)==1:
                context=json.loads(last)
                call('browser_execute',{'tab_id':context['tab_id'],'document_id':context['document_id'],'steps':[{'op':'fill','name':'Name','role':'textField','text':'native-plan','expect_text':'native-plan'},{'op':'click','name':'Apply','role':'button','expect_text':'Action verified'}]})
            else:
                result=json.loads(last);assert result['status']=='local_goal_completed' and len(result['checks'])==2,last
                text='Local capability fixture: bounded local goal verified'
        if 'cancel-check' in prompt:text='cancel-check stream '*100
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
        try:
            if calls:
                chunks=[{'tool_calls':calls}];finish='tool_calls'
            else:
                chunks=[{'content':text[i:i+32]} for i in range(0,len(text),32)];finish='stop'
            for delta in chunks:
                self.wfile.write(('data: '+json.dumps({'id':'fixture','object':'chat.completion.chunk','choices':[{'index':0,'delta':delta,'finish_reason':None}]})+'\n\n').encode());self.wfile.flush()
                if 'cancel-check' in prompt:time.sleep(.1)
            self.wfile.write(('data: '+json.dumps({'id':'fixture','choices':[{'index':0,'delta':{},'finish_reason':finish}]})+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):pass
    def events(self,events):
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
        for event in events:self.wfile.write(('data: '+json.dumps(event)+'\n\n').encode())
        self.wfile.flush()
def mcp_response(request):
    method=request.get('method');ident=request.get('id')
    if ident is None:return {}
    if method=='initialize': result={'protocolVersion':request['params']['protocolVersion'],'capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}}
    elif method=='tools/list':result={'tools':[{'name':'echo','description':'Local test echo','inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}]}
    elif method=='tools/call':result={'content':[{'type':'text','text':request['params']['arguments']['text']}]}
    else:return {'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Unknown method'}}
    return {'jsonrpc':'2.0','id':ident,'result':result}
if __name__=='__main__':
    if '--stdio' in sys.argv:
        if '--assert-no-network-sockets' in sys.argv:
            import os,stat
            for descriptor in range(3,1024):
                try: mode=os.fstat(descriptor).st_mode
                except OSError:continue
                assert not stat.S_ISSOCK(mode),'MCP child inherited an unrelated network descriptor'
        for line in sys.stdin:
            request=json.loads(line)
            if 'id' in request:
                print(json.dumps({'jsonrpc':'2.0','method':'notifications/message','params':{'level':'info','data':'fixture notification'}}),flush=True)
                print(json.dumps(mcp_response(request)),flush=True)
    else:http.server.ThreadingHTTPServer(('127.0.0.1',18794),Handler).serve_forever()
