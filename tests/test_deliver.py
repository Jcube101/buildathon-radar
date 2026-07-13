from email import message_from_string
from email.header import decode_header
from unittest.mock import MagicMock, patch

from buildathon_radar import deliver


def _decoded_subject(sent_msg):
    parsed = message_from_string(sent_msg)
    parts = decode_header(parsed["Subject"])
    return "".join(
        part.decode(enc or "utf-8") if isinstance(part, bytes) else part
        for part, enc in parts
    )


class TestSubjectFormatting:
    def test_send_digest_subject_includes_pick_count(self):
        digest_text = (
            "*note*\n\n## Must-see\n\n### [Event A](https://a.com)\ncard\n\n"
            "### [Event B](https://b.com)\ncard\n\n---\n**Source health:** x"
        )
        with patch.object(deliver, "smtplib") as mock_smtplib, patch.object(
            deliver, "save_to_archive"
        ):
            mock_server = MagicMock()
            mock_smtplib.SMTP_SSL.return_value.__enter__.return_value = mock_server
            mock_smtplib.SMTPAuthenticationError = smtplib_auth_error()
            mock_smtplib.SMTPException = Exception
            deliver.send_digest(digest_text)

        sent_msg = mock_server.sendmail.call_args[0][2]
        assert "2 events" in _decoded_subject(sent_msg)

    def test_send_digest_zero_picks_subject(self):
        digest_text = "Quiet week: 0 events.\n\n---\n**Source health:** x"
        with patch.object(deliver, "smtplib") as mock_smtplib, patch.object(
            deliver, "save_to_archive"
        ):
            mock_server = MagicMock()
            mock_smtplib.SMTP_SSL.return_value.__enter__.return_value = mock_server
            mock_smtplib.SMTPAuthenticationError = smtplib_auth_error()
            mock_smtplib.SMTPException = Exception
            deliver.send_digest(digest_text)

        sent_msg = mock_server.sendmail.call_args[0][2]
        assert "0 events" in _decoded_subject(sent_msg)


def smtplib_auth_error():
    import smtplib

    return smtplib.SMTPAuthenticationError


class TestMissingCredentials:
    def test_send_digest_skips_when_no_credentials(self, monkeypatch):
        monkeypatch.setattr(deliver.os, "getenv", lambda k, default=None: None)
        with patch.object(deliver, "smtplib") as mock_smtplib, patch.object(
            deliver, "save_to_archive"
        ):
            deliver.send_digest("some digest")
        mock_smtplib.SMTP_SSL.assert_not_called()


class TestFailureEmail:
    def test_send_failure_email_sends_with_correct_subject(self):
        with patch.object(deliver, "smtplib") as mock_smtplib:
            mock_server = MagicMock()
            mock_smtplib.SMTP_SSL.return_value.__enter__.return_value = mock_server
            deliver.send_failure_email("Traceback: something broke")

        sent_msg = mock_server.sendmail.call_args[0][2]
        assert "run failed" in sent_msg
        assert "something broke" in sent_msg

    def test_send_failure_email_never_raises_on_smtp_error(self):
        with patch.object(deliver, "smtplib") as mock_smtplib:
            mock_smtplib.SMTP_SSL.side_effect = Exception("network down")
            deliver.send_failure_email("boom")  # must not raise

    def test_send_failure_email_skips_when_no_credentials(self, monkeypatch):
        monkeypatch.setattr(deliver.os, "getenv", lambda k, default=None: None)
        with patch.object(deliver, "smtplib") as mock_smtplib:
            deliver.send_failure_email("boom")
        mock_smtplib.SMTP_SSL.assert_not_called()


class TestGetDateRange:
    def test_returns_nonempty_string(self):
        assert isinstance(deliver.get_date_range(), str)
        assert len(deliver.get_date_range()) > 0


class TestMarkdownToHtml:
    def test_contains_heading_and_body(self):
        html = deliver.markdown_to_html("## Hello\n\nSome text", "Jul 1 - 7, 2026")
        assert "Buildathon Radar" in html
        assert "Hello" in html
        assert "Jul 1 - 7, 2026" in html

    def test_no_date_range_omits_subtitle_block(self):
        html = deliver.markdown_to_html("body text", None)
        assert "Buildathon Radar" in html
