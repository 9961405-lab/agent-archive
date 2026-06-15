import pytest
from agent_archive.llm import extract_json

def test_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}

def test_strips_code_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

def test_ignores_prose_around_json():
    assert extract_json('好的，结果如下：\n{"a": 1}\n以上。') == {"a": 1}

def test_brace_inside_string_not_treated_as_end():
    assert extract_json('{"text": "a } b", "n": 2}') == {"text": "a } b", "n": 2}

def test_escaped_quote_inside_string():
    assert extract_json(r'{"t": "he said \"hi\" }", "n": 3}') == {"t": 'he said "hi" }', "n": 3}

def test_raises_on_no_json():
    with pytest.raises(ValueError):
        extract_json("完全没有 JSON")
