"""Isolated OAuth issuer; exercises the actual native transport and macOS Keychain.

Never approves a real account, calls a paid model, or stores real credentials.
"""
import base64, ctypes, hashlib, http.server, json, os, pathlib, tempfile, threading
import urllib.parse as url, urllib.request as request, urllib.error, time, sys, subprocess, concurrent.futures

class Issuer(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    generation=0; refreshes=0; invokes=0; revoke_fail=False; refresh_fail=False
    reject_once=False; challenge=None; redirect=None; refresh_used=set(); exchanges=0
    user401generation=-1; userBarrier=None; empty_next=False
    def log_message(self,*_): pass
    def send(self,status,body=None,content_type='application/json'):
        data=b'' if body is None else (body if isinstance(body,bytes) else json.dumps(body).encode())
        self.send_response(status);self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def bearer(self): return self.headers.get('Authorization')==f'Bearer fixture-access-{Issuer.generation}'
    def do_GET(self):
        if self.path.startswith('/custom/authorize?') and '--serve' in sys.argv:
            # Explicit local-only UI fixture. Never used with a real issuer.
            p={k:v[0] for k,v in url.parse_qs(url.urlparse(self.path).query).items()}
            assert p['client_id']=='metabrowser' and p['scope']=='read model:invoke'
            Issuer.challenge=p['code_challenge'];Issuer.redirect=p['redirect_uri']
            self.send_response(303);self.send_header('Location',p['redirect_uri']+'?'+url.urlencode({'code':'fixture-once-code','state':p['state']}));self.send_header('Content-Length','0');self.end_headers()
        elif self.path=='/.well-known/oauth-authorization-server':
            self.send_response(301);self.send_header('Location','/canonical/oauth-metadata');self.send_header('Content-Length','0');self.end_headers()
        elif self.path=='/canonical/oauth-metadata':
            self.send(200,dict(issuer=site,authorization_endpoint=site+'/custom/authorize',
                token_endpoint=site+'/custom/token',revocation_endpoint=site+'/custom/revoke',
                userinfo_endpoint=site+'/custom/user',device_authorization_endpoint=site+'/custom/device',
                code_challenge_methods_supported=['S256'],token_endpoint_auth_methods_supported=['none']))
        elif self.path=='/custom/user':
            if self.headers.get('Authorization')==f'Bearer fixture-access-{Issuer.user401generation}':
                Issuer.userBarrier.wait(10)
                return self.send(401,{'error':'invalid_token'})
            if not self.bearer(): return self.send(401,{'error':'invalid_token'})
            self.send(200,dict(sub='fixture-stable-sub',name='本地协议测试',email='fixture@example.invalid',client_id='metabrowser'))
        elif self.path=='/gateway/v1/models':
            assert self.bearer()
            self.send(200,{'data':[
                {'id':'explicit-unknown-must-not-fallback','capabilities':{'endpoints':{'chat_completions':{'supported':True,'status':'unknown'}},'input':{'text':{'supported':True}},'output':{'text':{'supported':True}}}},
                {'id':'unsupported-name-do-not-guess','capabilities':{'endpoints':{'chat_completions':{'supported':False,'status':'unknown'}}}},
                {'id':'fixture-text','capabilities':{'endpoints':{'chat_completions':{'supported':True,'status':'supported','input':['text','image'],'output':['text']}}}},
                {'id':'fixture-anthropic','capabilities':{'endpoints':{'messages':{'supported':True,'status':'supported','input':['text'],'output':['text']}}}},
                {'id':'fixture-responses','capabilities':{'endpoints':{'responses':{'supported':True,'status':'supported','input':['text'],'output':['text']}}}},
                {'id':'fixture-production-schema','capabilities':{'endpoints':{'chat_completions':{'supported':True}},'input':{'text':{'supported':True}},'output':{'text':{'supported':True}}}},
            ]})
        else: self.send(404,{'error':'unknown'})
    def do_POST(self):
        p=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path=='/custom/token':
            assert p['client_id']=='metabrowser' and 'client_secret' not in p
            if p['grant_type']=='authorization_code':
                assert p['code']=='fixture-once-code' and p['redirect_uri']==Issuer.redirect
                challenge=base64.urlsafe_b64encode(hashlib.sha256(p['code_verifier'].encode()).digest()).rstrip(b'=').decode()
                assert challenge==Issuer.challenge and len(p['code_verifier'])>=43
                Issuer.exchanges+=1
            elif p['grant_type']=='refresh_token':
                assert p['refresh_token']==f'fixture-refresh-{Issuer.generation}'
                assert p['refresh_token'] not in Issuer.refresh_used
                Issuer.refresh_used.add(p['refresh_token']);Issuer.refreshes+=1
                if Issuer.refresh_fail:return self.send(503,{'error':'temporarily_unavailable'})
            elif p['grant_type']=='urn:ietf:params:oauth:grant-type:device_code':
                assert p['device_code']=='fixture-device-secret'
            else: raise AssertionError(p)
            Issuer.generation+=1
            self.send(200,dict(access_token=f'fixture-access-{Issuer.generation}',refresh_token=f'fixture-refresh-{Issuer.generation}',
                expires_in=3600,token_type='bearer',scope='read model:invoke',gateway_url=site+'/gateway',models_url=site+'/gateway/v1/models'))
        elif self.path=='/custom/device':
            assert p=={'client_id':'metabrowser','scope':'read model:invoke'}
            self.send(200,dict(device_code='fixture-device-secret',user_code='TEST-ONLY',verification_uri=site+'/verify',expires_in=30,interval=1))
        elif self.path=='/custom/revoke':
            assert p=={'token':f'fixture-refresh-{Issuer.generation}','client_id':'metabrowser','token_type_hint':'refresh_token'}
            self.send(503 if Issuer.revoke_fail else 200,{'error':'temporarily_unavailable'} if Issuer.revoke_fail else None)
        elif self.path=='/gateway/v1/chat/completions':
            Issuer.invokes+=1
            if Issuer.reject_once:Issuer.reject_once=False;return self.send(401,{'error':{'code':'token_expired'}})
            assert self.bearer() and p['model']=='fixture-text'
            if Issuer.empty_next:
                Issuer.empty_next=False
                return self.send(200,b'data: [DONE]\n\n','text/event-stream')
            self.send(200,b'data: {"choices":[{"delta":{"content":"fixture-only"}}],"usage":null}\n\ndata: {"choices":[{"delta":{"content":"-with-usage"},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":17}}\n\ndata: [DONE]\n\n','text/event-stream')
        elif self.path=='/gateway/v1/messages':
            assert self.bearer() and p['model']=='fixture-anthropic'
            events=[{'type':'message_start','message':{'id':'fixture','role':'assistant','model':p['model'],'usage':{'input_tokens':1,'output_tokens':1}}},
                {'type':'content_block_start','index':0,'content_block':{'type':'text','text':''}},
                {'type':'content_block_delta','index':0,'delta':{'type':'text_delta','text':'fixture-only'}},
                {'type':'content_block_stop','index':0},{'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':1}},{'type':'message_stop'}]
            self.send(200,b''.join(('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n').encode() for e in events),'text/event-stream')
        elif self.path=='/gateway/v1/responses':
            assert self.bearer() and p['model']=='fixture-responses'
            events=[{'type':'response.created','response':{'id':'fixture','status':'in_progress'}},
                {'type':'response.output_item.added','output_index':0,'item':{'id':'m','type':'message','role':'assistant','content':[]}},
                {'type':'response.output_text.delta','item_id':'m','output_index':0,'delta':'fixture-only'},
                {'type':'response.completed','response':{'id':'fixture','status':'completed','usage':{'input_tokens':1,'output_tokens':1}}}]
            self.send(200,b''.join(('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n').encode() for e in events),'text/event-stream')
        else:self.send(404,{'error':'unknown'})

server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Issuer)
site=f'http://127.0.0.1:{server.server_port}'
os.environ['METASK_SITE_URL']=site;os.environ['METABROWSER_OAUTH_CLIENT_ID']='metabrowser'
threading.Thread(target=server.serve_forever,daemon=True).start()
if '--serve' in sys.argv:
    pathlib.Path('/tmp/metabrowser-oauth-ui-site').write_text(site)
    print('LOCAL DUMMY OAUTH UI FIXTURE:',site,flush=True)
    try: threading.Event().wait()
    except KeyboardInterrupt: server.shutdown()
    sys.exit(0)
lib=ctypes.CDLL(str(pathlib.Path(os.environ.get('METABROWSER_HOST_TEST_PLUGIN', 'zig-out/lib/libmetabrowser_metacodes.dylib')).resolve()))
Event=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint64)
lib.mb_mc_account.argtypes=[ctypes.c_char_p,ctypes.c_uint32,Event,ctypes.c_void_p]
lib.mb_mc_account.restype=ctypes.c_uint32
class Config(ctypes.Structure):
    _fields_=[('size',ctypes.c_uint32),('abi',ctypes.c_uint32),
        ('endpoint',ctypes.c_char_p),('model',ctypes.c_char_p),('key',ctypes.c_char_p),('workspace',ctypes.c_char_p),
        ('event',Event),('context',ctypes.c_void_p),('provider',ctypes.c_uint32),('protocol',ctypes.c_uint32),
        ('shell',ctypes.c_uint32),('turns',ctypes.c_uint32),('request',ctypes.c_void_p),('home',ctypes.c_char_p),('checkpoint',ctypes.c_char_p)]
lib.mb_mc_create.argtypes=[ctypes.POINTER(Config)];lib.mb_mc_create.restype=ctypes.c_void_p
lib.mb_mc_run.argtypes=[ctypes.c_void_p,ctypes.c_uint64,ctypes.c_char_p];lib.mb_mc_destroy.argtypes=[ctypes.c_void_p]
if '--restore-child' in sys.argv:
    saved=json.loads(pathlib.Path(sys.argv[-1],'config.json').read_text())
    os.environ['METASK_SITE_URL']=saved['site']
    kinds=[]
    @Event
    def child_event(_,kind,data,size):kinds.append(kind)
    status=lib.mb_mc_account(sys.argv[-1].encode(),1,child_event,None)
    assert status==0 and 8 in kinds,(status,kinds)
    server.shutdown();sys.exit(0)

def get_status(uri):
    try:
        with request.urlopen(uri,timeout=5) as r:return r.status
    except urllib.error.HTTPError as e:return e.code

with tempfile.TemporaryDirectory(prefix='metabrowser-oauth-contract-') as directory:
    root=directory.encode(); events=[]; callbacks=[]
    def callback(uri):
        p={k:v[0] for k,v in url.parse_qs(url.urlparse(uri).query).items()}
        assert p['client_id']=='metabrowser' and p['scope']=='read model:invoke' and p['code_challenge_method']=='S256'
        redirect=url.urlsplit(p['redirect_uri'])
        assert redirect.scheme=='http' and redirect.hostname=='localhost' and redirect.path=='/auth/metask/callback' and redirect.port is not None
        Issuer.challenge=p['code_challenge'];Issuer.redirect=p['redirect_uri']
        # Rejected state does not consume the callback listener or token grant.
        assert get_status(p['redirect_uri']+'?code=bad&state=wrong')==400
        assert get_status(p['redirect_uri']+'?code=bad&state='+p['state']+'&state=duplicate')==400
        assert get_status(p['redirect_uri']+'?'+url.urlencode({'code':'fixture-once-code','state':p['state']}))==200
    @Event
    def event(_,kind,data,size):
        raw=ctypes.string_at(data,size).decode();obj=json.loads(raw) if kind!=9 else raw;events.append((kind,obj))
        if kind==6 and obj.get('flow')=='pkce':
            t=threading.Thread(target=lambda:callback(obj['uri']));callbacks.append(t);t.start()
    def operation(op):
        events.clear();status=lib.mb_mc_account(root,op,event,None)
        for t in callbacks:t.join(10)
        return status,list(events)
    def invoke(account,cap=None,model='fixture-text',origin=None):
        headers={'Authorization':'Bearer '+(account['local_capability'] if cap is None else cap),'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        q=request.Request(account['endpoint'],json.dumps({'model':model,'stream':True,'messages':[{'role':'user','content':'fixture only'}]}).encode(),headers)
        try:
            with request.urlopen(q,timeout=10) as r:return r.status,r.read()
        except urllib.error.HTTPError as e:return e.code,e.read()
    try:
        status,e=operation(0);assert status==0,e
        account=next(v for k,v in e if k==8)
        assert account['sub']=='fixture-stable-sub' and account['model']=='fixture-text' and account['provider']=='openai'
        assert len(account['models'])==4 and 'access_token' not in account and 'refresh_token' not in account
        assert any(m['id']=='fixture-production-schema' for m in account['models'])
        assert not any(m['id']=='explicit-unknown-must-not-fallback' for m in account['models'])
        assert Issuer.exchanges==1
        assert sorted(p.name for p in pathlib.Path(directory).iterdir())==['oauth.lock']
        assert invoke(account,cap='wrong')[0]==401
        assert invoke(account,origin='https://untrusted.invalid')[0]==400
        catalogue_url=account['endpoint'].rsplit('/v1/',1)[0]+'/v1/models'
        catalogue_request=request.Request(catalogue_url,headers={'Authorization':'Bearer '+account['local_capability'],'X-Metacodes-Model-Endpoint':'chat_completions'})
        catalogue=json.load(request.urlopen(catalogue_request))
        image_model=next(m for m in catalogue['data'] if m['id']=='fixture-text')
        assert image_model['capabilities']['image_input']['supported'] is True
        assert not any(m['id']=='explicit-unknown-must-not-fallback' for m in catalogue['data'])
        assert invoke(account,model='unsupported-name-do-not-guess')[0]==400
        assert invoke(account)[0]==200
        Issuer.reject_once=True;before=Issuer.invokes
        code,body=invoke(account);assert code==200 and b'fixture-only' in body
        assert Issuer.refreshes==1 and Issuer.invokes-before==2
        # The actual pinned AgentCore SDK consumes the relay's stream, rather
        # than bypassing it in a test-only HTTP client.
        sdk_events=[]
        @Event
        def sdk_event(_,kind,data,size):sdk_events.append((kind,ctypes.string_at(data,size)))
        config=Config(ctypes.sizeof(Config),2,account['endpoint'].encode(),b'fixture-text',account['local_capability'].encode(),root,sdk_event,None,2,0,2,4,None,root,None)
        session=lib.mb_mc_create(ctypes.byref(config));assert session,sdk_events
        try:
            assert lib.mb_mc_run(session,1,b'local OAuth transport fixture')==0,sdk_events
            assert any(k==0 and b'fixture-only' in v for k,v in sdk_events),sdk_events
            assert any(k==0 and b'-with-usage' in v for k,v in sdk_events),sdk_events
            assert any(k==4 and b'\"output_tokens\":17' in v for k,v in sdk_events),sdk_events
            sdk_events.clear();Issuer.empty_next=True
            assert lib.mb_mc_run(session,2,b'empty response fixture')==0
            assert any(k==2 for k,v in sdk_events),sdk_events
            assert any(k==3 and v==b'Empty model response' for k,v in sdk_events),sdk_events
        finally:lib.mb_mc_destroy(session)
        for model,provider,protocol in [('fixture-anthropic',1,0),('fixture-responses',2,1)]:
            selected=next(m for m in account['models'] if m['id']==model);sdk_events.clear()
            config.model=model.encode();config.endpoint=(account['endpoint'].split('/v1/')[0]+selected['path']).encode();config.provider=provider;config.protocol=protocol
            session=lib.mb_mc_create(ctypes.byref(config));assert session,sdk_events
            try:
                assert lib.mb_mc_run(session,1,b'local OAuth protocol fixture')==0,sdk_events
                assert any(k==0 and b'fixture-only' in v for k,v in sdk_events),sdk_events
            finally:lib.mb_mc_destroy(session)
        # Independent processes coordinate only via flock, not a shared mutex.
        pathlib.Path(directory,'config.json').write_text(json.dumps({'site':site,'client_id':'metabrowser'}))
        Issuer.user401generation=Issuer.generation;Issuer.userBarrier=threading.Barrier(2);before=Issuer.refreshes
        def restore_child(_):return subprocess.run([sys.executable,__file__,'--restore-child',directory],capture_output=True,timeout=25)
        with concurrent.futures.ThreadPoolExecutor(2) as pool:children=list(pool.map(restore_child,range(2)))
        assert all(p.returncode==0 for p in children),[(p.returncode,p.stderr.decode()[-500:]) for p in children]
        assert Issuer.refreshes==before+1
        Issuer.user401generation=-1
        status,e=operation(1);assert status==0 and any(k==8 for k,_ in e),e
        status,e=operation(2);assert status==0 and next(v for k,v in e if k==10)['revoked'] is True,e
        assert invoke(account)[0]==401
        status,e=operation(1);assert status==0 and e==[(11,{})],e
        status,e=operation(3);assert status==0 and any(k==8 for k,_ in e),e
        assert invoke(account)[0]==401 # An older login capability cannot adopt the new grant.
        account=next(v for k,v in e if k==8)
        Issuer.refresh_fail=True;Issuer.reject_once=True;before=Issuer.refreshes
        assert invoke(account)[0]==401 and Issuer.refreshes==before+1
        assert invoke(account)[0]==401 and Issuer.refreshes==before+1
        Issuer.refresh_fail=False
        status,e=operation(3);assert status==0,e
        Issuer.revoke_fail=True
        status,e=operation(2);assert status==0 and next(v for k,v in e if k==10)['revoked'] is False,e
        status,e=operation(1);assert status==0 and e==[(11,{})],e
        # Cancellation stops the loopback callback wait promptly.
        @Event
        def cancel_event(_,kind,data,size):
            if kind==6:lib.mb_mc_login_cancel()
        start=time.monotonic();assert lib.mb_mc_account(root,0,cancel_event,None)==1
        assert time.monotonic()-start<3
        print('PASS: PKCE/state/duplicates, discovered paths, scopes/client_id, identity/model metadata, real Keychain without plaintext, actual SDK over OAuth relay (Chat/Anthropic/Responses), cross-process single refresh/rotation, ambiguous-refresh no retry, revoke empty 200/failure cleanup, restore and cancellation')
    finally:
        lib.mb_mc_account(root,2,event,None)
        server.shutdown()
