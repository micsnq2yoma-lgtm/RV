import base64,io,threading,time,unittest,urllib.request
from PIL import Image
from mjpeg import Streams,parameters

class MjpegTests(unittest.TestCase):
    def test_parameter_bounds(self):
        self.assertEqual(parameters('/stream/front.mjpg'),('front',640,480,8))
        for path in ['/stream/bad.mjpg','/stream/top.mjpg?w=1280','/stream/top.mjpg?fps=nan','/stream/top.mjpg?fps=9','/stream/top.mjpg?fps=','/stream/top.mjpg?fps=1&fps=2']:
            with self.assertRaises(ValueError):parameters(path)
        with self.assertRaises(ValueError):Streams('0.0.0.0:8090')
    def test_real_http_shared_latest_frame(self):
        image=io.BytesIO();Image.new('RGB',(320,240),'red').save(image,'JPEG');jpeg=image.getvalue()
        class Sim:
            calls=0
            def service(self,*args):self.calls+=1;return {'jpeg_b64':base64.b64encode(jpeg).decode()}
        sim=Sim();streams=Streams('127.0.0.1:0');port=streams.server.server_port;stop=threading.Event()
        def pump():
            while not stop.wait(.01):streams.pump(sim,None,None)
        thread=threading.Thread(target=pump);thread.start()
        http=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with http.open(f'http://127.0.0.1:{port}/stream/top.mjpg?w=320&h=240&fps=8',timeout=3) as response:
                self.assertIn('multipart',response.headers['Content-Type'])
                self.assertEqual(response.readline(),b'--rvframe\r\n')
                self.assertEqual(response.readline(),b'Content-Type: image/jpeg\r\n')
                length=int(response.readline().split(b':')[1]);response.readline()
                self.assertEqual(response.read(length),jpeg)
                self.assertLessEqual(sim.calls,2)
        finally:stop.set();thread.join();streams.close()
        self.assertFalse(streams.thread.is_alive())

if __name__=='__main__':unittest.main()
