from focus_app.unlock import ALPHABET, UnlockChallenge, generate_code, group_code, normalize_input


def test_generate_code_length_and_alphabet():
    code = generate_code(32)
    assert len(code) == 32
    assert set(code) <= set(ALPHABET)
    assert len(generate_code(2)) == 8  # 최소 길이
    assert generate_code(32) != generate_code(32)


def test_alphabet_has_no_ambiguous_chars():
    for ch in "0O1lI":
        assert ch not in ALPHABET


def test_group_and_normalize():
    assert group_code("abcdefghij") == "abcd efgh ij"
    assert normalize_input(" ab cd\tef\n") == "abcdef"


def test_challenge_accepts_exact_and_spaced_input():
    c = UnlockChallenge(length=16)
    code = c.code
    assert c.verify(group_code(code))
    assert c.attempts == 1


def test_wrong_input_rotates_code():
    c = UnlockChallenge(length=16)
    old = c.code
    assert not c.verify("nope")
    assert c.code != old
    assert c.attempts == 1
    assert not c.verify(old)  # 이전 문자열은 더 이상 유효하지 않음
