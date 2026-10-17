// QA only: navigate the explicit owned headed browser without viewport/device
// emulation, Runtime.enable, or activation of another native application's UI.
import assert from 'node:assert/strict';
const port=Number(process.argv[2]), url=process.argv[3];
assert.equal(port,18841);
const reset=url==='about:blank';
assert(reset||/^http:\/\/127\.0\.0\.1:18842\/\?run=[0-9a-f-]{36}&font=MetaBrowserPrivacyCanary[a-f0-9]+$/.test(url));
const blank = value=>['about:blank','chrome://newtab/','chrome://new-tab-page/'].includes(value);
let pages=[];
const startupDeadline=Date.now()+10000;
while(Date.now()<startupDeadline){
 const targets=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
 pages=targets.filter(t=>t.type==='page');
 if(pages.length>1){
  assert(pages.length<=8&&pages.every(t=>blank(t.url)),'Fixture resumed active probes; refusing to run concurrent captures');
  for(const extra of pages.slice(1)){
   const response=await fetch(`http://127.0.0.1:${port}/json/close/${encodeURIComponent(extra.id)}`);
   assert(response.ok,'Cannot close redundant blank fixture tab');
  }
  await new Promise(resolve=>setTimeout(resolve,100));continue;
 }
 if(pages.length===1&&(blank(pages[0].url)||(reset&&/^http:\/\/127\.0\.0\.1:18842\//.test(pages[0].url))))break;
 await new Promise(resolve=>setTimeout(resolve,100));
}
assert.equal(pages.length,1,'Fixture has no ready page');
assert(blank(pages[0].url)||(reset&&/^http:\/\/127\.0\.0\.1:18842\//.test(pages[0].url)));
const ws=new WebSocket(pages[0].webSocketDebuggerUrl);
const timeout=setTimeout(()=>{ws.close();throw Error('Fixture navigation timeout')},15000);
try{
 await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true})});
 const reply=new Promise((resolve,reject)=>ws.addEventListener('message',event=>{
  const message=JSON.parse(event.data);if(message.id!==1)return;
  message.error?reject(Error(message.error.message)):resolve(message.result);
 }));
 ws.send(JSON.stringify({id:1,method:'Page.navigate',params:{url}}));
 const result=await reply;
 assert(!result.errorText,result.errorText);
 let committed=false, nextId=2;
 while(!committed){
  const id=nextId++;
  const treeReply=new Promise((resolve,reject)=>{
   const listener=event=>{const message=JSON.parse(event.data);if(message.id!==id)return;ws.removeEventListener('message',listener);message.error?reject(Error(message.error.message)):resolve(message.result)};
   ws.addEventListener('message',listener);
  });
  ws.send(JSON.stringify({id,method:'Page.getFrameTree'}));
  const {frameTree}=await treeReply;
  committed=frameTree.frame.url===url&&(!result.loaderId||frameTree.frame.loaderId===result.loaderId);
  if(!committed)await new Promise(resolve=>setTimeout(resolve,50));
 }

}finally{clearTimeout(timeout);ws.close()}
