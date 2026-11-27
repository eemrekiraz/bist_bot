from __future__ import annotations

import unittest

from bist_ai_radar.kap_documents import extract_kap_attachment_urls, extract_kap_document_text


class KapDocumentTests(unittest.TestCase):
    def test_extracts_readable_text_without_script_payload(self) -> None:
        text = extract_kap_document_text(
            "<html><script>ignore me</script><main>"
            "Yatirim karari kapsaminda yeni kapasite artisi planlanmistir."
            "</main></html>"
        )
        self.assertIn("kapasite artisi", text)
        self.assertNotIn("ignore me", text)

    def test_finds_only_kap_pdf_attachments(self) -> None:
        urls = extract_kap_attachment_urls(
            '<a href="/files/duyuru.pdf">Ek</a><a href="https://example.com/x.pdf">x</a>',
            "https://www.kap.org.tr/tr/Bildirim/123",
        )
        self.assertEqual(urls, ["https://www.kap.org.tr/files/duyuru.pdf"])
