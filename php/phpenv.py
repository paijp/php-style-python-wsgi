#
#	Read the settings of a PHP env.php (config.php, ...) from Python, so that
#	the PHP and the Python version of an application can share one file while
#	both exist. It never runs PHP: it understands assignments of constant values.
#
#	    import phpenv
#	    d = phpenv.read("/etc/myapp/env.php")    # {"$dbpath": "...", "$sys->title": "..."}
#	    phpenv.apply(settings_object, d, "$sys") # settings_object.title = ...
#
#	Only these forms are understood, one statement per line
#	(a statement may go on over lines until its ";"):
#	    $var = <value>;            $var->name = <value>;
#	    require / include "...";   (the paths are kept in "require", a list)
#	    name(<value>, ...);        (a call, kept in "calls": a list of (name, [values]);
#	                               date_default_timezone_set also as "date_default_timezone_set")
#	    <value>: <<<ID heredoc / <<<'ID' nowdoc, "..." (with \n \t \r \0 \\ \" \$ \xhh \ooo), '...', a number,
#	             true / false / null, array(...) or [...] of values (with "key" => value),
#	             and values joined with "."
#	Anything else stops with PhpEnvError (the line number, never the text:
#	the files hold secrets).
#
import re


class PhpEnvError(Exception):
	pass


class _Tok:
	_re = re.compile(r'''
		(?P<ws>\s+|\#[^\n]*|//[^\n]*|/\*.*?\*/)
		|(?P<hd><<<[ \t]*(?P<hq>["']?)(?P<hid>[A-Za-z_][A-Za-z_0-9]*)(?P=hq)\r?\n(?:.*?\n)??[ \t]*(?P=hid)\b)
		|(?P<dq>"(?:[^"\\]|\\.)*")
		|(?P<sq>'(?:[^'\\]|\\.)*')
		|(?P<num>-?(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?))
		|(?P<var>\$[A-Za-z_][A-Za-z_0-9]*)
		|(?P<word>[A-Za-z_][A-Za-z_0-9]*)
		|(?P<op>->|=>|[=;.,()\[\]])
		''', re.S | re.X)

	def __init__(self, text):
		self.toks = []
		pos = 0
		while pos < len(text):
			m = self._re.match(text, pos)
			if m is None:
				raise PhpEnvError("line %d: cannot read" % (text.count("\n", 0, pos) + 1))
			if m.lastgroup != "ws":
				self.toks.append((m.lastgroup, m.group(), text.count("\n", 0, pos) + 1))
			pos = m.end()
		self.i = 0

	def peek(self):
		return self.toks[self.i] if self.i < len(self.toks) else (None, None, 0)

	def take(self, value=None):
		t = self.peek()
		if t[0] is None or (value is not None and t[1] != value):
			raise PhpEnvError("line %d: unexpected" % t[2])
		self.i += 1
		return t


_ESC = {"n": "\n", "t": "\t", "r": "\r", "v": "\v", "e": "\x1b", "f": "\f", "\\": "\\", "$": "$", '"': '"'}


def _dq(s, line):
	out = ""
	i = 0
	while i < len(s):
		c = s[i]
		if c == "$" and i + 1 < len(s) and re.match(r'[A-Za-z_{]', s[i + 1]):
			raise PhpEnvError("line %d: a variable in a string" % line)
		if c != "\\" or i + 1 >= len(s):
			out += c
			i += 1
			continue
		n = s[i + 1]
		if n in _ESC:
			out += _ESC[n]
			i += 2
		elif (m := re.match(r'[0-7]{1,3}', s[i + 1:])):
			out += chr(int(m.group(), 8) & 0xff)
			i += 1 + len(m.group())
		elif n == "x" and (m := re.match(r'[0-9a-fA-F]{1,2}', s[i + 2:])):
			out += chr(int(m.group(), 16))
			i += 2 + len(m.group())
		else:
			out += c
			i += 1
	return out


def _heredoc(s, line):
	"""<<<ID ... ID (as "...") and <<<'ID' ... ID (as is); the indentation of the
	closing ID is taken off every line (PHP 7.3)."""
	m = re.match(r'<<<[ \t]*(["\']?)([A-Za-z_][A-Za-z_0-9]*)\1\r?\n', s)
	body = s[m.end():]
	lines = body.split("\n")
	indent = re.match(r'[ \t]*', lines[-1]).group()
	lines = [l[len(indent):] if l.startswith(indent) else l for l in lines[:-1]]
	text = "\n".join(lines)
	return text if m.group(1) == "'" else _dq(text, line)


def _value(t):
	v = _atom(t)
	while t.peek()[1] == ".":
		t.take(".")
		v = _str(v) + _str(_atom(t))
	return v


def _str(v):
	if v is True:
		return "1"
	if v is None or v is False:
		return ""
	return str(v)


def _atom(t):
	kind, s, line = t.take()
	if kind == "dq":
		return _dq(s[1:-1], line)
	if kind == "hd":
		return _heredoc(s, line)
	if kind == "sq":
		return re.sub(r"\\([\\'])", r"\1", s[1:-1])
	if kind == "num":
		return float(s) if "." in s else int(s, 0)
	if kind == "word" and s.lower() in ("true", "false", "null"):
		return {"true": True, "false": False, "null": None}[s.lower()]
	if (kind == "word" and s.lower() == "array") or s == "[":
		end = ")" if s != "[" else "]"
		if s != "[":
			t.take("(")
		d = {}
		n = 0
		while t.peek()[1] != end:
			v = _value(t)
			if t.peek()[1] == "=>":
				t.take("=>")
				k, v = v, _value(t)
			else:
				k, n = n, n + 1
			d[k] = v
			if t.peek()[1] != ",":
				break
			t.take(",")
		t.take(end)
		return list(d.values()) if list(d.keys()) == list(range(len(d))) else d
	raise PhpEnvError("line %d: unknown value" % line)


def read(fn):
	"""{"$var": value, "$var->name": value} of the assignments in fn.
	A missing file gives {} (as include of PHP with @)."""
	try:
		with open(fn, encoding="utf-8", errors="surrogateescape") as f:
			text = f.read()
	except OSError:
		return {}
	text = re.sub(r'^\s*<\?php', "", text)
	text = re.sub(r'\?>\s*$', "", text)
	t = _Tok(text)
	ret = {}
	while t.peek()[0] is not None:
		kind, s, line = t.take()
		if kind == "word" and s.lower() in ("require", "require_once", "include", "include_once"):
			paren = t.peek()[1] == "("
			if paren:
				t.take("(")
			ret.setdefault("require", []).append(_value(t))
			if paren:
				t.take(")")
			t.take(";")
			continue
		if kind == "word" and t.peek()[1] == "(":
			t.take("(")
			args = []
			while t.peek()[1] != ")":
				args.append(_value(t))
				if t.peek()[1] != ",":
					break
				t.take(",")
			t.take(")")
			t.take(";")
			ret.setdefault("calls", []).append((s.lower(), args))
			if s.lower() == "date_default_timezone_set" and args:
				ret["date_default_timezone_set"] = args[0]
			continue
		if kind != "var":
			raise PhpEnvError("line %d: not an assignment" % line)
		name = s
		if t.peek()[1] == "->":
			t.take("->")
			name += "->" + t.take()[1]
		t.take("=")
		ret[name] = _value(t)
		t.take(";")
	return ret


def apply(obj, settings, var):
	"""Set the attributes of obj from the "$var->name" settings."""
	p = var + "->"
	for k, v in settings.items():
		if k.startswith(p):
			setattr(obj, k[len(p):], v)
	return obj
