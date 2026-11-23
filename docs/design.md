# Design

## The model

```
browser ── nginx ──(unix socket)── server.py ── application (WSGI)
            │                       one process, one thread per request,
            └ static files           started by systemd, ends when idle
```

- **nginx** speaks to the clients: TLS, HTTP/2, static files, request
  buffering, access logs. It passes only the paths of the applications to the
  socket, with `X-Real-IP` and `X-Forwarded-Proto`. Only nginx (its group) can
  connect to the socket, so these headers can be trusted.
- **systemd** owns the socket (socket activation). It starts the server at the
  first connection; the server ends itself after `idle` seconds without a
  request. While the server is not running or restarts, connections wait in
  the socket instead of failing.
- **server.py** maps the start of the path to an application (`web.toml`),
  runs each request in a thread (at most `threads`), checks the body size, and
  calls the functions an application put in `environ["pyweb.later"]` after the
  answer has been sent.

## Rules for applications

PHP starts every request from nothing ("shared nothing"). Applications here
share one process, so they follow the same idea by hand:

1. **No per-request state in module globals.** Keep it in local variables or
   in an object made for the request. A global that is only set once at import
   (settings, tables, compiled patterns) is fine. If an old design needs a
   "current request" global, make it `threading.local()`.
2. **No `os.chdir()`**, no changes of `os.environ` or of other process-wide
   state while serving. Use absolute paths.
3. **Open files and database connections per request** (or use a pool that is
   safe in threads). SQLite: set a busy timeout, writes wait for each other.
4. **Long work after the answer** (notifications, mail) goes in
   `environ["pyweb.later"]` as `(function, args)`.

An application that cannot follow them (for example one that registers its
classes in globals, so two sites cannot share a process) gets its own
instance: a second socket, service and `web.toml`. It is the same code, so
nothing new to review.

## Decisions, and why

### Only listed entry points run; never "a file because it is there"

With Apache + PHP, any `.php` file under the document root can be run by
requesting it. It is convenient, and it is where many PHP sites got broken:

- **Uploaded files run.** If the application can write to a directory under
  the document root (uploads, caches), an uploaded `.php` file is a program
  the attacker runs on the server (a "web shell").
- **Files that are not entry points run.** Settings (`config.php`) and
  libraries (`lib.php`, helpers) can be requested directly and run out of
  context: errors that show paths or values, actions without the checks the
  real entry point does.
- **Copies leak.** `index.php.bak`, `config.php~` or an editor's swap file is
  not run as PHP; it is sent as text, with its passwords.
- **Nobody knows what runs.** After some years nobody can list the programs a
  site exposes; old tools stay reachable.

So here an application runs only because `web.toml` names it, by module, not
by file. The rest of the URL space is 404 (or nginx's static files, which are
never run). Keep the applications in a directory the server's user cannot
write to, and the data (databases, uploads) elsewhere (`/var/lib/<app>/`): a
file written there is never run.

`web.toml` decides which code runs, so it is owned by root or the deploying
user, not by the user the server runs as.

### Old `.php` URLs keep working, with no PHP

For Python, `.php` is part of a path like any other. List the old URL as a
prefix (`/app/index.php`): the application gets `PATH_INFO` and the query and
answers as the PHP page did. Bookmarks, links in mails and URLs written in
devices keep working. No `.php` file is ever run; PHP need not be installed.

### Threads, not processes

On a small server with one CPU, more processes do not make computing faster;
they only cost memory. Threads already share the CPU fairly: while a request
waits (database, network, disk) the others run, and Python switches between
busy threads every few milliseconds, so a slow page makes the others slower,
not stopped. Spawning and reaping worker processes is also the most complex
part of servers like php-fpm or uWSGI; leaving it out keeps the server short.
If one application is heavy, give it its own instance.

`threads` limits the requests at the same time so that a burst cannot exhaust
memory; the next connections wait in the socket (backlog 64 in the example).

### Standard library only

Every dependency is something to update and review. The server uses
`socketserver`, `wsgiref` and `tomllib`, maintained with Python itself; HTTP
from the clients is parsed by nginx first. `wsgiref` speaks HTTP/1.0-style
connections to nginx, which is all nginx needs here.

### What is left out on purpose

- **TLS, HTTP/2, static files, access logs, compression**: nginx does them.
- **Authentication** (Basic, cookies): in nginx (`auth_basic`, `auth_request`)
  or in the application. Security code in the server would have to be
  reviewed for every site.
- **Reloading the settings**: restart the service; connections wait meanwhile.
- **Changing the number of processes with the load**: see above.
- **Finding applications by file name**: see above.

## Other ways that also give "no memory while idle"

- **CGI** (fcgiwrap or Apache): a process per request. Simple and fully
  isolated; every request pays the Python start-up and imports, and a burst
  costs memory per request. Good for rare, heavy jobs.
- **systemd-socket-proxyd** in front of any server (gunicorn, Flask's
  `app.run()`): start on demand and stop when idle without changing the
  application. Make the proxy wait until the application listens
  (`ExecStartPost` loop or `Type=notify`), or the first connection can fail.
- **Phusion Passenger**: spawns application processes on demand and stops
  idle ones; threads within a process are in the paid edition.
- **mod_wsgi daemon mode** with `inactivity-timeout`: unloads the application,
  but the empty process stays (about 8 MB each, measured).
