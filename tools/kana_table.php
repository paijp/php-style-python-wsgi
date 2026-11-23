<?php
# Write the table of mb_convert_kana($s, <options>, "UTF-8") for php/phpcompat.py
# load_kana(): every character that the options change, one at a time.
#     php tools/kana_table.php askh > kana_askh.json
# Ranges: ASCII and Latin-1, general punctuation, CJK symbols, kana, and the
# halfwidth / fullwidth forms (what mb_convert_kana works on).
$opt = (string)@$argv[1];
if (!preg_match('/^[rRnNaAsSkKhHcC]+$/', $opt))
	die("usage: php kana_table.php <options of mb_convert_kana, e.g. askh>\n");
$out = array();
foreach (array(array(0x20, 0xff), array(0x2010, 0x2030), array(0x3000, 0x30ff), array(0xff00, 0xffef)) as $r)
	for ($c = $r[0]; $c <= $r[1]; $c++) {
		$s = mb_chr($c, "UTF-8");
		if (($t = mb_convert_kana($s, $opt, "UTF-8")) !== $s)
			$out[$s] = $t;
	}
print json_encode($out, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT)."\n";
