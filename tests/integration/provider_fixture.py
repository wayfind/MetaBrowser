#!/usr/bin/env python3
"""Local test-only OpenAI SSE fixture. Never used as a production model."""
import http.server, json, time
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def do_POST(self):
        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        users=[m for m in request.get('messages',[]) if m.get('role')=='user']
        prompt=str(users[-1].get('content','')) if users else ''
        slow='cancel-check' in prompt
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
        chunks=['本地验收：','这条回复经过真实 MetaCodes AgentCore 会话流式传回。','\n原生侧边栏 → Zig → AgentCore → 本地测试服务 → 侧边栏。']
        if slow: chunks=['cancel-check stream '] * 100
        try:
            for text in chunks:
                body={'id':'fixture','object':'chat.completion.chunk','model':'gpt-4.1-mini','choices':[{'index':0,'delta':{'content':text},'finish_reason':None}]}
                self.wfile.write(('data: '+json.dumps(body,ensure_ascii=False)+'\n\n').encode());self.wfile.flush();time.sleep(0.15 if slow else 0.08)
            body={'id':'fixture','object':'chat.completion.chunk','choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}
            self.wfile.write(('data: '+json.dumps(body)+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):pass
if __name__=='__main__':
    print('Local test provider on 127.0.0.1:18792',flush=True)
    http.server.ThreadingHTTPServer(('127.0.0.1',18792),Handler).serve_forever()
