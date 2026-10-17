"""Actual packaged Zig plugin/SDK; isolated loopback provider, no paid calls."""
import http.server,json,os,pathlib,subprocess,sys,tempfile,threading
root=pathlib.Path(__file__).resolve().parents[2]
requests=[]
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        data=json.dumps({'data':[{'id':'gpt-4.1-mini','max_input_tokens':1000000,'max_tokens':131072}]}).encode()
        self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append(value)
        summary='Summarize this conversation for compaction:' in str(value.get('messages'))
        text='COMPACTED_TASK_ANCHOR: continue the user task.' if summary else 'ack'
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        for delta,finish in [({'content':text},None),({},'stop')]:
            self.wfile.write(('data: '+json.dumps({'id':'fixture','choices':[{'index':0,'delta':delta,'finish_reason':finish}]})+'\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n');self.wfile.flush()
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
plugin=pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else root/'out/macos-arm64/MetaBrowser.app/Contents/Frameworks/libmetabrowser_metacodes.dylib'
with tempfile.TemporaryDirectory(prefix='metabrowser-compact-') as tmp:
    binary=pathlib.Path(tmp)/'test'
    subprocess.run(['clang','-I'+str(root/'chromium/metabrowser'),str(root/'tests/integration/compact_plugin_test.c'),'-o',str(binary)],check=True)
    run=subprocess.run([str(binary),str(plugin),f'http://127.0.0.1:{server.server_port}/v1/chat/completions',tmp],text=True,capture_output=True,timeout=90,env={**os.environ,'METACODES_MODEL_CATALOG_PROBE':'1'})
    if run.returncode:raise AssertionError(run.stderr)
    stages={row['stage']:row['result'] for row in map(json.loads,run.stdout.splitlines())}
server.shutdown()
before=stages['before']['inference']['context_tokens'];after=stages['after']['inference']['context_tokens']
inference=stages['before']['inference']
assert inference['context_window']==1000000,inference
assert inference['context_output_reserve']==131072,inference
assert inference['context_limit']==868928,inference
assert before/inference['context_limit']<.01,inference
assert after<before,(before,after)
assert len(requests)==9,len(requests)
summary=requests[6];continued=requests[7];restored=requests[8]
assert 'A'*128 in str(summary)
for request in [continued,restored]:
    assert 'A'*128 not in str(request)
    assert 'COMPACTED_TASK_ANCHOR' in str(request) and 'recent context' in str(request)
result={'fixture_only':True,'actual_packaged_plugin':str(plugin),'before_tokens':before,'after_tokens':after,'summary_requested':True,'old_prefix_replaced_by_summary':True,'recent_context_preserved':True,'continue_after_compact':True,'checkpoint_restore_and_continue':True,'empty_compact_no_provider_call':True,'compact_result':stages['compact'],'empty_compact_result':stages['empty_compact']}
(root/'out/evidence/compact-plugin-acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
