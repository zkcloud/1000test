import asyncio, json, ssl, socket, sys
from datetime import datetime, timezone
from aioquic.asyncio import connect, QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.h3.connection import H3Connection, H3_ALPN
from aioquic.h3.events import HeadersReceived, DataReceived
from h2.connection import H2Connection
from h2.events import ResponseReceived, DataReceived as H2Data, StreamEnded
DOMAIN='ty.1byte.online'
class Client(QuicConnectionProtocol):
    def __init__(self,*a,**k):
        super().__init__(*a,**k); self.http=H3Connection(self._quic); self.done=None; self.headers=[]; self.body=b''
    def quic_event_received(self,event):
        for e in self.http.handle_event(event):
            if isinstance(e,HeadersReceived): self.headers.extend(e.headers)
            if isinstance(e,DataReceived): self.body+=e.data
            if isinstance(e,(HeadersReceived,DataReceived)) and e.stream_ended and self.done and not self.done.done():
                self.done.set_result({'protocol':'h3','status':dict(self.headers).get(b':status',b'').decode(),'body':self.body.decode(),'headers':{k.decode():v.decode() for k,v in self.headers}})
    async def get(self):
        self.done=asyncio.get_running_loop().create_future()
        self.http.send_headers(stream_id=self._quic.get_next_available_stream_id(),headers=[(b':method',b'GET'),(b':scheme',b'https'),(b':authority',DOMAIN.encode()),(b':path',b'/api/health')],end_stream=True)
        self.transmit(); return await self.done
async def h3(host,port=443):
    cfg=QuicConfiguration(is_client=True,alpn_protocols=H3_ALPN,server_name=DOMAIN)
    async with connect(host,port,configuration=cfg,create_protocol=Client) as c: return await c.get()
def h2(host):
    ctx=ssl.create_default_context();ctx.set_alpn_protocols(['h2'])
    with socket.create_connection((host,443),timeout=15) as raw, ctx.wrap_socket(raw,server_hostname=DOMAIN) as s:
        assert s.selected_alpn_protocol()=='h2'
        conn=H2Connection();conn.initiate_connection();conn.send_headers(1,[(b':method',b'GET'),(b':scheme',b'https'),(b':authority',DOMAIN.encode()),(b':path',b'/api/health')],end_stream=True);s.sendall(conn.data_to_send());headers={};body=b''
        while True:
            data=s.recv(65536)
            if not data: raise ConnectionError('Unexpected EOF')
            for e in conn.receive_data(data):
                if isinstance(e,ResponseReceived):headers.update({k.decode():v.decode() for k,v in e.headers})
                if isinstance(e,H2Data): body+=e.data;conn.acknowledge_received_data(e.flow_controlled_length,e.stream_id)
                if isinstance(e,StreamEnded):return {'protocol':'h2','status':headers[':status'],'body':body.decode(),'headers':headers}
            outgoing=conn.data_to_send()
            if outgoing:s.sendall(outgoing)
async def main():
    origin=sys.argv[1] if len(sys.argv)>1 else '43.155.140.75'
    results=[]
    for name,host,protocol in [('origin-h3',origin,'h3'),('public-h3',DOMAIN,'h3'),('origin-h2',origin,'h2'),('public-h2',DOMAIN,'h2')]:
        try:
            result=await asyncio.wait_for(h3(host),12) if protocol=='h3' else await asyncio.to_thread(h2,host)
            assert result['status']=='200' and json.loads(result['body'])=={'status':'ok'}
            results.append({'test':name,'ok':True,**result})
        except Exception as e:results.append({'test':name,'ok':False,'error':type(e).__name__+': '+str(e)})
    # Use an unused UDP port to simulate an unavailable QUIC endpoint; retry HTTPS/TCP with ALPN h2.
    try:
        await asyncio.wait_for(h3(origin,9),2)
        results.append({'test':'udp-unavailable-client-fallback','ok':False,'error':'Unexpected UDP 9 service'})
    except (TimeoutError,ConnectionError,OSError):
        try:
            result=await asyncio.to_thread(h2,origin);assert result['status']=='200'
            results.append({'test':'udp-unavailable-client-fallback','ok':True,'simulation':'QUIC to unused UDP port 9 timed out, then TLS/TCP 443','tls_verification':True,**result})
        except Exception as e:results.append({'test':'udp-unavailable-client-fallback','ok':False,'error':str(e)})
    print(json.dumps({'time_utc':datetime.now(timezone.utc).isoformat(),'tls_verification':True,'origin':origin,'results':results},ensure_ascii=False,indent=2))
asyncio.run(main())
