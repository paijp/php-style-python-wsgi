#
#	Small PHP functions whose exact output matters when a Python version must
#	answer byte for byte like the PHP version it replaces.
#
import json
import re


def htmlspecialchars(s, quotes=True):
	"""htmlspecialchars($s) of PHP 8.1+ (ENT_QUOTES | ENT_SUBSTITUTE by default):
	& < > " ' as &amp; &lt; &gt; &quot; &#039; (html.escape gives &#x27; for ').
	quotes=False: as ENT_NOQUOTES."""
	s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
	if quotes:
		s = s.replace('"', "&quot;").replace("'", "&#039;")
	return s


def trim(s, chars=" \t\n\r\0\x0b"):
	"""trim($s): only these characters (str.strip() also removes U+3000 and others)."""
	return s.strip(chars)


def load_kana(path):
	"""mb_convert_kana($s, <options>, "UTF-8") from a table made with
	tools/kana_table.php (one character at a time; PHP does not join
	characters with these options; "V" (join voiced marks) is not supported)."""
	with open(path, encoding="utf-8") as f:
		table = json.load(f)
	return lambda s: "".join(table.get(ch, ch) for ch in s)


def strtolower(s):
	"""strtolower() of PHP 8: ASCII letters only."""
	return re.sub(r"[A-Z]+", lambda m: m.group().lower(), s)
