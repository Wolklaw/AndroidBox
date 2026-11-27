import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from androidbox import i18n, paths  # noqa: E402


class I18nTests(unittest.TestCase):
    def tearDown(self):
        i18n.use("en")

    def test_pot_template_and_zh_tw_po_exist(self):
        pot = paths.LOCALES / "androidbox.pot"
        po = i18n.po_path("zh_TW")
        self.assertTrue(pot.is_file(), f"Missing .pot template: {pot}")
        self.assertTrue(po.is_file(), f"Missing zh_TW .po file: {po}")

    def test_parse_po_handles_multiline_and_escapes(self):
        sample = '''
# Comment
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

msgid "Hello\\n"
"World"
msgstr "你好\\n"
"世界"

#, fuzzy
msgid "Fuzzy"
msgstr "模糊"
'''
        parsed = i18n.parse_po(sample)
        self.assertEqual(parsed["Hello\nWorld"], "你好\n世界")
        self.assertNotIn("Fuzzy", parsed)

    def test_switch_between_english_and_traditional_chinese(self):
        i18n.use("en")
        self.assertEqual(i18n.current(), "en")
        self.assertEqual(i18n.t("Interface language"), "Interface language")
        self.assertEqual(i18n.t("Settings"), "Settings")

        i18n.use("zh_TW")
        self.assertEqual(i18n.current(), "zh_TW")
        self.assertEqual(i18n.t("Interface language"), "介面語言")
        self.assertEqual(i18n.t("Settings"), "設定")
        self.assertEqual(i18n.t("Eco mode"), "省電模式")
        # Untranslated strings fall back cleanly to English
        self.assertEqual(i18n.t("Untranslated fallback"), "Untranslated fallback")


if __name__ == "__main__":
    unittest.main()
