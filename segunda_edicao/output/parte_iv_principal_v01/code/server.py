"""Loopback inference; validates units/categories at the actual consumer."""
from http.server import BaseHTTPRequestHandler,HTTPServer
from pathlib import Path
import argparse,json,os,time
from laboratorios.parte_i.common import load,save
from laboratorios.parte_iv.core import predict,identity

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    model=load(a.model)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            t=time.perf_counter();request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:
                result=predict(model,request['row'],future=request['mode']=='future_bad',unsafe_unit=request['mode']=='unit_bad');status=200
                result.update(model=identity(model),pid=os.getpid())
            except ValueError as e:status=422;result={'error':str(e),'id':request['row']['id'],'pid':os.getpid()}
            evidence={'request':request,'status':status,'response':result,'seconds':time.perf_counter()-t}
            save(a.out/'requests'/(request['attempt']+'.json'),evidence)
            body=json.dumps(result,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=HTTPServer(('127.0.0.1',0),Handler)
    save(a.out/'ready.json',{'port':server.server_port,'pid':os.getpid(),'model':identity(model)})
    server.serve_forever()

if __name__=='__main__':main()
