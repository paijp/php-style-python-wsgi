#
#	pyweb: WSGI applications behind nginx, in one process, standard library only.
#
#	- systemd starts it at the first connection to its socket (socket
#	  activation) and it ends itself after `idle` seconds without a request:
#	  no memory while nobody uses the site, whatever the number of applications
#	  (as php-fpm "ondemand"). While it restarts, the connections wait in the
#	  socket.
#	- One thread for each request, at most `threads` at the same time (the
#	  others wait in the socket).
#	- The settings file (TOML) maps the start of the path to an application
#	  ("module:function", imported at its first request); any other path is
#	  404. Only these entry points run: no file is served or run because of
#	  where it is. nginx serves the static files.
#	- nginx tells the client address (X-Real-IP) and the scheme
#	  (X-Forwarded-Proto); nobody else can connect to the socket.
#	- environ["pyweb.later"] (also "pai.later") is a list of (function, args)
#	  to call after the answer has been sent (e.g. notifications).
#
#	python3 -I server.py                 under systemd (the socket is fd 3)
#	python3 -I server.py 127.0.0.1:8960  by hand, for a test
#	PYWEB_CONFIG: the settings file (default /etc/pyweb/web.toml)
#	PYWEB_MOUNT="/path=module:function": put one more application first (tests)
#
import importlib
import os
import socket
import sys
import threading
import time
import tomllib
import traceback
from socketserver import ThreadingMixIn
from wsgiref.simple_server import ServerHandler, WSGIRequestHandler, WSGIServer

CONFIG = os.environ.get("PYWEB_CONFIG") or "/etc/pyweb/web.toml"
with open(CONFIG, "rb") as f:
	conf = tomllib.load(f)
IDLE = int(conf.get("idle", 60))
THREADS = int(conf.get("threads", 10))
MAX_BODY = int(conf.get("max_body", 1 << 20))
for p in reversed(conf.get("path", [])):
	sys.path.insert(0, p)
APPS = [(a["prefix"], a["app"], int(a.get("max_body", MAX_BODY))) for a in conf.get("app", [])]
if os.environ.get("PYWEB_MOUNT"):
	_p, _t = os.environ["PYWEB_MOUNT"].split("=", 1)
	APPS.insert(0, (_p, _t, MAX_BODY))

_lock = threading.Lock()
_active = 0
_last = time.time()


def _find(path):
	"""The application for the path: the prefix itself, or below it."""
	for prefix, target, max_body in APPS:
		if path == prefix or path.startswith(prefix if prefix.endswith("/") else prefix + "/"):
			mod, func = target.split(":")
			return getattr(importlib.import_module(mod), func), max_body
	return None, 0


def _answer(start_response, status, text):
	start_response(status, [("Content-Type", "text/plain")])
	return [text.encode()]


def application(environ, start_response):
	app, max_body = _find(environ.get("PATH_INFO", ""))
	if app is None:
		return _answer(start_response, "404 Not Found", "not found\n")
	try:
		if int(environ.get("CONTENT_LENGTH") or 0) > max_body:
			return _answer(start_response, "413 Content Too Large", "too large\n")
	except ValueError:
		return _answer(start_response, "400 Bad Request", "bad length\n")
	if environ.get("HTTP_X_REAL_IP"):
		environ["REMOTE_ADDR"] = environ["HTTP_X_REAL_IP"]
	if environ.get("HTTP_X_FORWARDED_PROTO") == "https":
		environ["wsgi.url_scheme"] = "https"
		environ["HTTPS"] = "on"
	environ["pyweb.later"] = environ["pai.later"] = []
	try:
		return app(environ, start_response)
	except Exception:
		traceback.print_exc()
		start_response("500 Internal Server Error", [("Content-Type", "text/plain")], sys.exc_info())
		return [b"error\n"]


class Handler(WSGIRequestHandler):
	timeout = 120		# seconds a connection may stay silent (a stuck client does not keep a thread)

	def log_message(self, *a):
		pass		# nginx logs the requests

	def address_string(self):
		return "-"

	def setup(self):
		super().setup()
		if not isinstance(self.client_address, tuple) or not self.client_address:
			self.client_address = ("", 0)		# a unix socket has no address (nginx tells it)

	def get_environ(self):
		env = super().get_environ()
		env["REMOTE_ADDR"] = ""
		env["REQUEST_URI"] = self.path		# as sent (PATH_INFO is decoded)
		return env

	def handle(self):
		self.raw_requestline = self.rfile.readline(65537)
		if not self.parse_request():
			return
		h = ServerHandler(self.rfile, self.wfile, self.get_stderr(), self.get_environ(), multithread=True)
		h.request_handler = self
		later = []

		def app(environ, start_response):
			r = application(environ, start_response)
			later.extend(environ.get("pyweb.later", []))
			return r
		h.run(app)
		self.wfile.flush()
		try:
			self.connection.shutdown(socket.SHUT_WR)		# the answer is complete: nginx may go on
		except OSError:
			pass
		for fn, args in later:
			try:
				fn(*args)
			except Exception:
				traceback.print_exc()


class Server(ThreadingMixIn, WSGIServer):
	daemon_threads = True
	request_queue_size = 64

	def __init__(self, *a, **k):
		self._slots = threading.BoundedSemaphore(THREADS)
		super().__init__(*a, **k)

	def server_bind(self):
		if self.socket.family == socket.AF_UNIX:
			self.server_name, self.server_port = "localhost", 80
			self.setup_environ()
			return
		super().server_bind()

	def process_request(self, request, client_address):
		global _active
		self._slots.acquire()		# at most THREADS at a time; the next connections wait in the socket
		with _lock:
			_active += 1
		super().process_request(request, client_address)

	def process_request_thread(self, request, client_address):
		global _active, _last
		try:
			super().process_request_thread(request, client_address)
		finally:
			with _lock:
				_active -= 1
				_last = time.time()
			self._slots.release()


def _idlewatch(server):
	while True:
		time.sleep(5)
		with _lock:
			if _active == 0 and time.time() - _last > IDLE:
				break
	server.shutdown()


def main():
	if len(sys.argv) > 1:		# by hand: host:port
		host, port = sys.argv[1].rsplit(":", 1)
		server = Server((host, int(port)), Handler)
	elif os.environ.get("LISTEN_FDS") == "1" and os.environ.get("LISTEN_PID") == str(os.getpid()):
		server = Server(None, Handler, bind_and_activate=False)
		server.socket = socket.socket(fileno=3)
		server.server_bind()
		threading.Thread(target=_idlewatch, args=(server,), daemon=True).start()
	else:
		sys.exit("pyweb: no socket (start the .socket unit, or give host:port)")
	server.set_app(application)
	server.serve_forever()


if __name__ == "__main__":
	main()
