"""Run with uv --no-project --with a2a-sdk --with httpx; test-only client."""
import asyncio, json, os, time, uuid
import httpx
from google.protobuf.json_format import ParseDict
from a2a.types import AgentCard,Task,SendMessageRequest,Message,Part,Role,GetTaskRequest
from a2a.client import ClientFactory,ClientConfig
async def main():
    url=os.environ.get('METABROWSER_AGENT_URL','http://127.0.0.1:18795')
    token=os.environ['METABROWSER_AGENT_TOKEN']
    async with httpx.AsyncClient(headers={'Authorization':'Bearer '+token},timeout=20) as http:
        unauthorized=await httpx.AsyncClient().post(url+'/a2a',json={})
        assert unauthorized.status_code==401
        card=(await http.get(url+'/.well-known/agent-card.json')).json()
        parsed=ParseDict(card,AgentCard())
        factory=ClientFactory(ClientConfig(streaming=False,polling=False,httpx_client=http))
        client=factory.create(parsed)
        ident=str(uuid.uuid4())
        request=SendMessageRequest(message=Message(message_id=ident,role=Role.ROLE_USER,parts=[Part(text=os.environ.get('METABROWSER_TEST_PROMPT','External agent integration fixture'))]))
        tasks=[]
        async for event in client.send_message(request):
            if event.HasField('task'):tasks.append(event.task)
        assert tasks,'Official client did not receive a Task'
        task=tasks[-1]
        for _ in range(900):
            task=await client.get_task(GetTaskRequest(id=task.id))
            if task.status.state in (3,4,5,7):break
            await asyncio.sleep(.1)
        # Use descriptor names rather than assuming enum number assignments.
        state=task.status.DESCRIPTOR.fields_by_name['state'].enum_type.values_by_number[task.status.state].name
        assert state=='TASK_STATE_COMPLETED',state
        output=' '.join(p.text for a in task.artifacts for p in a.parts)
        assert 'Local capability fixture' in output,output
        print('Output:',output[:200])
        print('PASS: official A2A client AgentCard, SendMessage, GetTask and native AgentCore output; task',task.id)
        print('Prompt:',os.environ.get('METABROWSER_TEST_PROMPT','External agent integration fixture'))
asyncio.run(main())
