# A minimal application for server.py (WSGI). It keeps no state between
# requests: everything a request needs is in environ (see docs/design.md).
import html
import urllib.parse


def application(environ, start_response):
	q = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
	name = q.get("name", ["world"])[-1]
	body = "<!DOCTYPE html>\n<p>Hello, %s (from %s)</p>\n" % (
		html.escape(name), html.escape(environ.get("REMOTE_ADDR", "")))
	# something to do after the answer has been sent (a notice, a log line)
	environ["pyweb.later"].append((print, ("hello was shown",)))
	start_response("200 OK", [("Content-Type", "text/html; charset=UTF-8")])
	return [body.encode("utf-8")]
