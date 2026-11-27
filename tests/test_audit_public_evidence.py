"""Synthetic content-screening checks without network or publisher documents."""
import gzip
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import audit_public_evidence as audit


class ContentAuditTests(unittest.TestCase):
    def test_soft_404_image_url_is_not_counted_as_image_evidence(self):
        flags = audit.content_flags("https://example.org/spec.jpg", "404 NOT FOUND", "Page moved", b"<html>missing</html>")
        self.assertIn("ERROR_OR_ACCESS_PAGE", flags)
        self.assertIn("IMAGE_URL_RETURNED_OTHER_MEDIA", flags)
        self.assertEqual(audit.review_class(flags, b"<html>missing</html>"), "ERROR_OR_ACCESS_PAGE")

    def test_placeholder_requires_substantive_marker(self):
        flags = audit.content_flags("https://example.org/item", "Product Name", "This is a description of the item.", b"<html></html>")
        self.assertIn("JAVASCRIPT_PLACEHOLDER", flags)
        self.assertNotIn("JAVASCRIPT_PLACEHOLDER", audit.content_flags("https://example.org/item", "Product Name", "Specific operating specification", b"<html></html>"))

    def test_challenge_page_is_flagged(self):
        flags = audit.content_flags("https://example.org/item", "Just a moment...", "Checking your browser", b"<html></html>")
        self.assertIn("ERROR_OR_ACCESS_PAGE", flags)

    def test_gzip_decoding_preserves_original_bytes(self):
        original = gzip.compress(b"<html><title>Example</title><p>Useful text.</p><script>hidden()</script></html>")
        before = original
        parser = audit.VisibleHTML()
        parser.feed(audit.decode_gzip(original).decode())
        self.assertEqual(original, before)
        self.assertIn("Useful text.", parser.text)
        self.assertNotIn("hidden()", parser.text)

    def test_image_is_retained_for_visual_review(self):
        raw = b"\xff\xd8\xffsynthetic"
        flags = audit.content_flags("https://example.org/diagram.jpg", "", "", raw)
        self.assertEqual(audit.review_class(flags, raw), "IMAGE_REQUIRES_VISUAL_REVIEW")

    def test_pdf_redirect_to_html_is_flagged(self):
        flags = audit.content_flags("https://example.org/manual.pdf", "Store", "Storefront navigation", b"<html>Storefront</html>")
        self.assertIn("PDF_URL_RETURNED_OTHER_MEDIA", flags)
        self.assertEqual(audit.review_class(flags, b"<html>Storefront</html>"), "UNEXPECTED_MEDIA")


if __name__ == "__main__":
    unittest.main()
