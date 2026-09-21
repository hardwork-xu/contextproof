import json

import pytest

from benchmarks.revision_model import canonical, parse_answer


def test_scoring_preserves_typed_json_and_ignores_object_order():
    assert canonical({"value": True}) != canonical({"value": 1})
    assert canonical({"value": [1, 2]}) != canonical({"value": [2, 1]})
    assert canonical({"value": {"a": 1, "b": 2}}) == canonical({"value": {"b": 2, "a": 1}})
    assert parse_answer(json.dumps({"answer_json": '{"error":"TypeError"}'})) == {"error": "TypeError"}


@pytest.mark.parametrize("answer", ['{"value":NaN}', '{"value":Infinity}',
                                    '{"value":false,"value":true}',
                                    '{"error":123}', '{"value":1,"reason":"extra"}', '[1]'])
def test_invalid_or_ambiguous_answers_never_score(answer):
    with pytest.raises((ValueError, TypeError)):
        parse_answer(json.dumps({"answer_json": answer}))
