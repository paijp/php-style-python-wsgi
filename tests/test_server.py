# python3 -m unittest discover -s tests   (standard library only)
import http.client
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP = '''
import threading, time
lock = threading.Lock()
active = peak = 0
def application(environ, start_response):
	global active, peak
	if environ["PATH_INFO"].startswith("/slow/"):
		with lock:
			active += 1
			peak = max(peak, active)
		time.sleep(0.5)
		with lock:
			active -= 1
	if environ["PATH_INFO"].startswith("/later/"):
		environ["pyweb.later"].append((open(environ["QUERY_STRING"], "w").write, ("done",)))
	body = "%s|%s|%s|%s|%d" % (environ["PATH_INFO"], environ.get("REMOTE_ADDR"),
		environ["wsgi.url_scheme"], environ.get("REQUEST_URI"), peak)
	start_response("200 OK", [("Content-Type", "text/plain")])
	return [body.encode()]
def broken(environ, start_response):
	raise RuntimeError("test")
'''

CONF = '''
threads = 2
max_body = 100
path = ["%s"]
[[app]]
prefix = "/slow/"
app = "testapp:application"
[[app]]
prefix = "/a/"
app = "testapp:application"
[[app]]
prefix = "/later/"
app = "testapp:application"
[[app]]
prefix = "/old/index.php"
app = "testapp:application"
max_body = 1000
[[app]]
prefix = "/broken"
app = "testapp:broken"
'''


def freeport():
	s = socket.socket()
	s.bind(("127.0.0.1", 0))
	p = s.getsockname()[1]
	s.close()
	return p


class ServerTest(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.dir = tempfile.TemporaryDirectory()
		d = cls.dir.name
		for name, text in (("testapp.py", APP), ("web.toml", CONF % d)):
			with open(os.path.join(d, name), "w") as f:
				f.write(text)
		cls.port = freeport()
		cls.proc = subprocess.Popen([sys.executable, "-I", os.path.join(ROOT, "server.py"), "127.0.0.1:%d" % cls.port],
			env=dict(os.environ, PYWEB_CONFIG=os.path.join(d, "web.toml")), stderr=subprocess.PIPE)
		for i in range(50):
			try:
				socket.create_connection(("127.0.0.1", cls.port), 0.2).close()
				break
			except OSError:
				time.sleep(0.1)

	@classmethod
	def tearDownClass(cls):
		cls.proc.terminate()
		cls.proc.wait()
		cls.proc.stderr.close()
		cls.dir.cleanup()

	def get(self, path, method="GET", body=None, headers=None):
		c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
		c.request(method, path, body, headers or {})
		r = c.getresponse()
		return r.status, r.read().decode()

	def test_routes(self):
		self.assertEqual(self.get("/a/x?q=1")[1].split("|")[0], "/a/x")
		self.assertEqual(self.get("/a/")[0], 200)
		self.assertEqual(self.get("/a")[0], 404)			# "/a/" covers below it only
		self.assertEqual(self.get("/b/")[0], 404)
		self.assertEqual(self.get("/old/index.php")[0], 200)
		self.assertEqual(self.get("/old/index.php/nofmt/x.html")[0], 200)
		self.assertEqual(self.get("/old/index.phpx")[0], 404)
		self.assertEqual(self.get("/a/../x")[0], 200)		# PATH_INFO as sent; nginx normalizes

	def test_request_uri_and_proxy_headers(self):
		st, b = self.get("/a/%41?x=%42", headers={"X-Real-IP": "192.0.2.1", "X-Forwarded-Proto": "https"})
		path, addr, scheme, uri, _ = b.split("|")
		self.assertEqual((path, addr, scheme, uri), ("/a/A", "192.0.2.1", "https", "/a/%41?x=%42"))
		_, b = self.get("/a/")
		self.assertEqual(b.split("|")[1:3], ["", "http"])

	def test_max_body(self):
		self.assertEqual(self.get("/a/", "POST", "x" * 100)[0], 200)
		self.assertEqual(self.get("/a/", "POST", "x" * 101)[0], 413)
		self.assertEqual(self.get("/old/index.php", "POST", "x" * 1000)[0], 200)
		self.assertEqual(self.get("/old/index.php", "POST", "x" * 1001)[0], 413)

	def test_threads_limit(self):
		out = []
		ts = [threading.Thread(target=lambda: out.append(self.get("/slow/")[1])) for i in range(5)]
		t0 = time.time()
		for t in ts:
			t.start()
		for t in ts:
			t.join()
		self.assertEqual(max(int(b.split("|")[4]) for b in out), 2)
		self.assertGreaterEqual(time.time() - t0, 1.4)		# 5 requests, 2 at a time, 0.5 s each

	def test_later(self):
		fn = os.path.join(self.dir.name, "later.txt")
		self.assertEqual(self.get("/later/?" + fn)[0], 200)
		for i in range(20):
			if os.path.exists(fn):
				break
			time.sleep(0.05)
		with open(fn) as f:
			self.assertEqual(f.read(), "done")

	def test_error(self):
		self.assertEqual(self.get("/broken")[0], 500)
		self.assertEqual(self.get("/a/")[0], 200)			# the server goes on


if __name__ == "__main__":
	unittest.main()
