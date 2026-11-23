# python3 -m unittest discover -s tests   (the comparisons with PHP run when php is installed)
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "php"))
import phpcompat  # noqa: E402
import phpenv  # noqa: E402

PHP = shutil.which("php")

ENV = r'''<?php
# settings
require_once("/somewhere/lib.php");
date_default_timezone_set("Asia/Tokyo");
$title = "a \"title\"\t\x41\101 \$x";
$single = 'it\'s \n raw';
$n = 3; $f = 1.5; $neg = -2; $yes = true; $none = null;
$list = array("a", "b");
$map = ["k" => "v", "n" => 2];
$joined = "a" . 'b' . 3;
$sys->name = "x";
$doc = <<<EOO
line1
  line2 "q"
EOO;
$raw = <<<'EOO'
no \t escape
EOO;
ini_set("memory_limit", "64M");
'''


class PhpEnvTest(unittest.TestCase):
	def setUp(self):
		self.f = tempfile.NamedTemporaryFile("w", suffix=".php", delete=False)
		self.f.write(ENV)
		self.f.close()

	def tearDown(self):
		os.unlink(self.f.name)

	def test_read(self):
		d = phpenv.read(self.f.name)
		self.assertEqual(d["require"], ["/somewhere/lib.php"])
		self.assertEqual(d["date_default_timezone_set"], "Asia/Tokyo")
		self.assertEqual(d["$title"], 'a "title"\tAA $x')
		self.assertEqual(d["$single"], "it's \\n raw")
		self.assertEqual((d["$n"], d["$f"], d["$neg"], d["$yes"], d["$none"]), (3, 1.5, -2, True, None))
		self.assertEqual(d["$list"], ["a", "b"])
		self.assertEqual(d["$map"], {"k": "v", "n": 2})
		self.assertEqual(d["$joined"], "ab3")
		self.assertEqual(d["$sys->name"], "x")
		self.assertEqual(d["$doc"], 'line1\n  line2 "q"')
		self.assertEqual(d["$raw"], "no \\t escape")
		self.assertIn(("ini_set", ["memory_limit", "64M"]), d["calls"])

	def test_error_has_no_text(self):
		with open(self.f.name, "w") as f:
			f.write('<?php\n$secret = "pass" . $other;\n')
		with self.assertRaises(phpenv.PhpEnvError) as e:
			phpenv.read(self.f.name)
		self.assertNotIn("pass", str(e.exception))

	@unittest.skipUnless(PHP, "php is not installed")
	def test_same_as_php(self):
		d = phpenv.read(self.f.name)
		src = ENV.replace('require_once("/somewhere/lib.php");', "").replace("<?php", "<?php $sys = new stdClass;", 1)
		src += 'print json_encode(array($title, $single, $joined, $doc, $raw, $sys->name, $list, $map));'
		out = subprocess.run([PHP, "-r", "?>" + src], capture_output=True, text=True).stdout
		self.assertEqual(json.loads(out), [d["$title"], d["$single"], d["$joined"], d["$doc"], d["$raw"], d["$sys->name"], d["$list"], d["$map"]])


class CompatTest(unittest.TestCase):
	S = ["", "a&b<c>\"d'e", "日本語 ＡＢＣ　ｶﾞ", " \t trim \r\n\0\x0b", "　keep　", "MiXeD Ä"]

	def test_values(self):
		self.assertEqual(phpcompat.htmlspecialchars("<'\"&>"), "&lt;&#039;&quot;&amp;&gt;")
		self.assertEqual(phpcompat.htmlspecialchars("'\"", quotes=False), "'\"")
		self.assertEqual(phpcompat.trim("　x \n"), "　x")
		self.assertEqual(phpcompat.strtolower("ABC Ä"), "abc Ä")

	@unittest.skipUnless(PHP, "php is not installed")
	def test_same_as_php(self):
		code = 'foreach (json_decode(stream_get_contents(STDIN)) as $s) $o[] = array(htmlspecialchars($s), trim($s), strtolower($s), mb_convert_kana($s, "askh", "UTF-8")); print json_encode($o);'
		out = json.loads(subprocess.run([PHP, "-r", code], input=json.dumps(self.S), capture_output=True, text=True).stdout)
		with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
			f.write(subprocess.run([PHP, os.path.join(ROOT, "tools", "kana_table.php"), "askh"], capture_output=True, text=True).stdout)
		try:
			kana = phpcompat.load_kana(f.name)
			mine = [[phpcompat.htmlspecialchars(s), phpcompat.trim(s), phpcompat.strtolower(s), kana(s)] for s in self.S]
		finally:
			os.unlink(f.name)
		self.assertEqual(mine, out)


if __name__ == "__main__":
	unittest.main()
