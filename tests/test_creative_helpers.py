"""编剧辅助函数回归测试。

守护两个曾在真实任务中暴露的问题：
1. 研究 LLM 写出的长 features 原样拼进口播，确定性降级段单段冲到 700 字，
   导致成片 635 秒（目标约 300 秒）——_clip/_shrink_to_sentences 是长度护栏；
2. 时长估算常数必须与 SAPI 实测语速（约 5 字/秒）保持同一数量级。
"""

from videoforge.agents.creative import (_clip, _format_stars, _shrink_to_sentences,
                                        estimate_duration)


def test_clip_cuts_long_text_with_marker():
    assert _clip("短文本", 80) == "短文本"
    out = _clip("a" * 100, 10)
    assert len(out) == 10 and out.endswith("…")


def test_clip_strips_newlines_and_punctuation_tail():
    assert "\n" not in _clip("第一行\n第二行继续", 100)
    assert not _clip("太长了，" + "x" * 50, 6).endswith("，")


def test_shrink_keeps_full_sentence_when_boundary_in_latter_half():
    text = "x" * 45 + "。" + "啰" * 80
    out = _shrink_to_sentences(text, 60)
    assert out.endswith("。") and len(out) == 46 and "啰" not in out


def test_shrink_without_any_punctuation_hard_cuts():
    out = _shrink_to_sentences("x" * 100, 30)
    assert len(out) <= 31 and out.endswith("。")


def test_shrink_comma_fallback_keeps_most_of_long_sentence():
    # 真实事故：模型把一段写成 280 字一个长句，首个句号在 40 字处，
    # 只按句号截断会丢掉全部特性介绍。limit 附近有逗号时应在逗号收束。
    text = "首句很短。" + "甲" * 193 + "，" + "尾" * 60
    out = _shrink_to_sentences(text, 220)
    assert out.endswith("。")
    assert int(220 * 0.75) <= len(out) <= 220
    assert "甲" in out  # 早句号之后的信息量被保留


def test_short_text_passes_through_shrink():
    assert _shrink_to_sentences("就这些。", 100) == "就这些。"


def test_format_stars_chinese_wan():
    assert _format_stars(277917) == "27.8 万"
    assert _format_stars(999) == "999"
    assert _format_stars(10000) == "1.0 万"


def test_estimate_duration_calibrated_near_5_cps_and_clamped():
    assert estimate_duration("字" * 100) == 20.0          # 100 / 5.0
    assert estimate_duration("字") == 6.0                 # 最短镜头钳制
    assert estimate_duration("字" * 1000) == 75.0         # 最长镜头钳制
