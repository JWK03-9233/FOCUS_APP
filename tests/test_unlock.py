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


def test_complexity_levels_use_their_characters_and_each_group_at_least_once():
    from focus_app import unlock

    for _ in range(50):
        basic = unlock.generate_code(32, "basic")
        assert set(basic) <= set(ALPHABET)
        sym = unlock.generate_code(32, "symbols")
        assert set(sym) & set(unlock.SYMBOLS) and not set(sym) & set(unlock.AMBIGUOUS)
        assert any(c.isupper() for c in sym) and any(c.islower() for c in sym) and any(c.isdigit() for c in sym)
    # 최대 단계에서는 헷갈리는 글자도 나올 수 있음
    assert set("".join(unlock.generate_code(256, "max") for _ in range(20))) & set(unlock.AMBIGUOUS)
    assert unlock.generate_code(40, "없는 단계") and len(unlock.generate_code(40, "max")) == 40


def test_challenge_keeps_complexity_after_wrong_input():
    from focus_app import unlock

    c = UnlockChallenge(length=32, complexity="symbols")
    assert set(c.code) & set(unlock.SYMBOLS)
    c.verify("틀림")
    assert set(c.code) & set(unlock.SYMBOLS) and len(c.code) == 32


def test_settings_complexity_is_validated():
    from focus_app.config import Settings

    assert Settings.from_dict({"unlock_code_complexity": "max"}).unlock_code_complexity == "max"
    assert Settings.from_dict({"unlock_code_complexity": "이상한 값"}).unlock_code_complexity == "basic"
