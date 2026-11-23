# Moving a PHP application

The goal is a Python version that answers like the PHP version, byte for
byte where it matters, so that users see no change and the move can be
checked by a machine instead of by eye.

## 1. Keep the URLs and the data

- Serve the same URLs (`/app/index.php`, `/app/index.php/page.html`): list
  them as prefixes in `web.toml`.
- Use the same database and files; do not change their format in the same
  step. Cookies keep their names and paths, so logged-in users stay logged in.
- Read the same settings file with `php/phpenv.py` while both versions exist.

## 2. Port

Write the WSGI application following the rules in [design.md](design.md).
Things that differ between PHP and Python and change the output:

| PHP | Python | note |
|---|---|---|
| `htmlspecialchars($s)` | `phpcompat.htmlspecialchars(s)` | `'` is `&#039;` (`html.escape` gives `&#x27;`) |
| `trim($s)` | `phpcompat.trim(s)` | `str.strip()` also removes U+3000 and other spaces |
| `strtolower($s)` | `phpcompat.strtolower(s)` | ASCII only in PHP 8 |
| `mb_convert_kana($s, "askh")` | `phpcompat.load_kana(table)(s)` | table from `tools/kana_table.php` |
| `date()` | `datetime` with the same time zone | PHP's default may be UTC (no `date.timezone`) |
| `(int)"12abc"` | write it out | PHP takes the leading digits |
| `$a[2] = x` on a short array | lists do not grow | check `explode` results |
| `explode("\n", "")` | `[""]` in PHP too | but `"".split()` is `[]` |
| HTML written in the PHP file | | the PHP file may have CRLF line ends; compare with them normalized |
| `mb_convert_encoding` (EUC-JP, ISO-2022-JP) | Python codecs | a few characters differ (e.g. `~`, `‾`, `¥`); map them |

## 3. Compare

Run the PHP and the Python version on the same data and compare everything
they send: status, `Location`, cookies, body, and the database afterwards.

- **A scenario on a fresh database.** A script logs in, posts, edits,
  deletes, searches, ... first against the PHP version (`php -S`), then
  against the Python version (`server.py host:port` with `PYWEB_MOUNT`),
  writes each answer to a file with times and random keys masked, and
  compares the two directories. Wait a second between changes if the pages
  sort by time.
- **All the pages of the real database.** On a copy, make every page (or an
  even sample of a large site) with both versions and count the pages that
  differ, printing counts only, so the output can be shown without showing
  the data. For the pages that differ, print the kind of difference without
  the text: the lines reduced to their HTML tag names, and the characters that
  differ as classes (letters `a`, digits `9`, other characters `U+xxxx`).
- Run the two servers one after the other on a small machine, not both at
  once.

Then switch nginx to the Python version for one application at a time. Keep
the PHP files for some days so that switching back is one location in nginx.
When nothing uses PHP any more, stop and mask php-fpm.
