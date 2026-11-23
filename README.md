# php-style-python-wsgi

A small WSGI server for Python web applications that behaves like PHP on a
small server, and some tools for moving PHP applications to Python.

(WSGI is Python's standard interface between a web application and the
server that runs it, what SAPI / php-fpm is for PHP.)

## Why

PHP is easy to run on a small server: nginx or Apache passes `.php` requests
to php-fpm, one pool serves every application, and with `pm = ondemand` an
idle site uses no memory at all, however many applications it has. Python's
usual setup is different: one resident process (gunicorn, uWSGI, ...) per
application, so every application costs memory all the time.

`server.py` gives Python applications the PHP-like setup:

- **No memory while idle.** systemd starts it at the first connection to its
  socket and it ends itself after `idle` seconds without a request.
- **One process for all applications.** Adding an application costs nothing
  while it is not used.
- **Concurrent requests in threads**, at most `threads` at a time; the next
  connections wait in the socket. Connections also wait there while the
  server restarts, so a restart loses no request.
- **Standard library only** (Python 3.11+). About 200 lines, written to be
  read and reviewed.

It was made to take PHP out of servers for security, keeping the old URLs
(`/app/index.php?...`) working with no PHP installed.

## Files

| file | |
|---|---|
| `server.py` | the server |
| `examples/` | settings (`web.toml`), systemd units, nginx, a minimal application |
| `php/phpenv.py` | read a PHP `env.php` / `config.php` (constant assignments) from Python, so that both versions share one settings file during the move |
| `php/phpcompat.py` | PHP functions whose exact output matters: `htmlspecialchars` (`&#039;`), `trim`, `strtolower`, `mb_convert_kana` (with a table made by `tools/kana_table.php`) |
| `docs/design.md` | the rules for applications, and why the server works this way (including what PHP does that it does not do) |
| `docs/migrating.md` | how to move a PHP application and check that the Python version answers the same |
| `tests/` | `python3 -m unittest discover -s tests` (the comparisons with PHP run when `php` is installed) |

## Quick start (Rocky Linux / RHEL, nginx)

1. Copy `server.py` to `/opt/pyweb/server.py` and your applications to
   `/opt/apps/` (e.g. `examples/hello/` as `/opt/apps/hello/`).
2. Write `/etc/pyweb/web.toml` (see `examples/web.toml`), owned by root.
3. Install `examples/systemd/pyweb.socket` and `pyweb.service` in
   `/etc/systemd/system/`, then `systemctl daemon-reload && systemctl enable --now pyweb.socket`.
4. Pass the paths from nginx to `/run/pyweb.sock` (see `examples/nginx.conf`)
   and reload nginx.

Test by hand: `PYWEB_CONFIG=examples/web.toml python3 server.py 127.0.0.1:8080`
(with `path` pointing to `examples/`).

After a change of `web.toml` or an application, `systemctl restart pyweb.service`
(or stop it: the next request starts it again).

## Settings (web.toml)

```toml
idle = 60          # seconds without a request, then the process ends
threads = 10       # requests at the same time
max_body = 1048576 # bytes of a request body (413 above), per application too
path = ["/opt/apps"]

[[app]]
prefix = "/hello/"              # this path and below it
app = "hello.app:application"   # module:function, imported at its first request
```

A path that matches no `prefix` is 404. Nothing runs because of where a file
is: see [docs/design.md](docs/design.md).

## Status

Used on production servers (a set of business applications moved from PHP:
mail, bulletin boards, newsletters; an IoT data logger). Feedback is welcome.

## License

MIT
