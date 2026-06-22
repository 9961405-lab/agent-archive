from agent_archive.redact import redact


def test_redacts_common_secrets():
    s = redact("key=sk-abcdefghijklmnopqrstuvwx token gho_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345")
    assert "sk-abcdefghijklmnopqrstuvwx" not in s
    assert "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in s
    assert "[REDACTED]" in s


def test_redacts_aws_bearer_email_userpath():
    s = redact("AKIAIOSFODNN7EXAMPLE Bearer abc.def.ghi a@b.com /Users/mac/secret")
    assert "AKIAIOSFODNN7EXAMPLE" not in s
    assert "a@b.com" not in s
    assert "Bearer abc.def.ghi" not in s
    assert "/Users/mac/" not in s
    assert "/Users/[USER]/" in s


def test_redacts_bare_userpath_without_trailing_slash():
    s = redact("工作目录是 /Users/mac（不是项目）")
    assert "/Users/mac" not in s
    assert "/Users/[USER]" in s


def test_keeps_normal_text():
    assert redact("帮我核对快团团订单，金额对不上") == "帮我核对快团团订单，金额对不上"
