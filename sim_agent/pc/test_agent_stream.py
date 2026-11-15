import io,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'board'/'agent'))
from agent import Model

class StreamingModelTests(unittest.TestCase):
    def test_text_and_fragmented_function_arguments(self):
        chunks=[{'choices':[{'delta':{'content':'先观察'}}]},
                {'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call_1','function':{'name':'pick','arguments':'{"object":'}}]}}]},
                {'choices':[{'delta':{'content':'再抓取','tool_calls':[{'index':0,'function':{'arguments':'"red_cube"}'}}]}}]},
                {'choices':[],'usage':{'total_tokens':123}}]
        wire=b''.join(b'data: '+json.dumps(c).encode()+b'\n\n' for c in chunks)+b'data: [DONE]\n\n'
        class Http:
            def open(self,request,timeout):
                self.body=json.loads(request.data);return io.BytesIO(wire)
        model=Model.__new__(Model);model.key='test-only';model.http=Http();events=[];model.emit=events.append
        messages=[{'role':'user','content':'simulation fixture'}]
        result,request,retry=model.call(messages);messages.append({'role':'assistant','content':'later'})
        message=result['choices'][0]['message']
        self.assertEqual(message['content'],'先观察再抓取')
        self.assertEqual(json.loads(message['tool_calls'][0]['function']['arguments']),{'object':'red_cube'})
        self.assertEqual(len(request['messages']),1);self.assertTrue(model.http.body['stream'])
        self.assertEqual([e['text'] for e in events if e['type']=='think_delta'],['先观察','再抓取'])
        self.assertEqual(events[-1]['tokens']['total_tokens'],123)
        self.assertEqual(retry,0)

if __name__=='__main__':unittest.main()
