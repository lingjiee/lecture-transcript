"""流水线的测试套件。

    python -m unittest discover -s tests -v
    python tests/test_pipeline.py

只用标准库，不需要装 faster-whisper——transcribe.py 把它的 import 放在函数里，
所以纯逻辑部分可以脱离模型测试。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRT2TXT = REPO / "bin" / "srt2txt"
SRT_VERIFY = REPO / "bin" / "srt-verify"

sys.path.insert(0, str(REPO / "transcribe"))
import transcribe  # noqa: E402


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name: str, content: str, encoding: str = "utf-8") -> Path:
        path = self.tmp / name
        path.write_bytes(content.encode(encoding))
        return path

    def write_bytes(self, name: str, data: bytes) -> Path:
        path = self.tmp / name
        path.write_bytes(data)
        return path


# ---------------------------------------------------------------- srt2txt

BASIC = """1
00:00:00,000 --> 00:00:02,000
第一句

2
00:00:02,000 --> 00:00:04,000
第二句
"""


class TestSrt2Txt(TempDirCase):
    def extract(self, path: Path, *args: str) -> str:
        out = self.tmp / "out.txt"
        proc = run(SRT2TXT, str(path), *args, "-o", str(out))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return out.read_text(encoding="utf-8").strip()

    def test_strips_indices_and_timecodes(self):
        self.assertEqual(self.extract(self.write("a.srt", BASIC)), "第一句第二句")

    def test_no_space_between_cjk_but_space_around_latin(self):
        src = ("1\n00:00:00,000 --> 00:00:01,000\n中文\n\n"
               "2\n00:00:01,000 --> 00:00:02,000\nAI\n\n"
               "3\n00:00:02,000 --> 00:00:03,000\ntool\n")
        # CJK 相邻不加空格；拉丁词之间加空格
        self.assertEqual(self.extract(self.write("b.srt", src)), "中文 AI tool")

    def test_vtt_header_ignored(self):
        src = "WEBVTT\n\nNOTE something\n\n00:00:00.000 --> 00:00:01.000\n你好\n"
        self.assertEqual(self.extract(self.write("c.vtt", src)), "你好")

    def test_handles_bom_and_crlf(self):
        path = self.write("d.srt", BASIC.replace("\n", "\r\n"), encoding="utf-8-sig")
        self.assertEqual(self.extract(path), "第一句第二句")

    def test_handles_gbk(self):
        self.assertEqual(self.extract(self.write("e.srt", BASIC, encoding="gb18030")),
                         "第一句第二句")

    def test_handles_utf16(self):
        self.assertEqual(self.extract(self.write("f.srt", BASIC, encoding="utf-16")),
                         "第一句第二句")

    def test_strips_markup_and_sound_effects(self):
        src = ("1\n00:00:00,000 --> 00:00:01,000\n{\\an8}<i>真正的</i>内容\n\n"
               "2\n00:00:01,000 --> 00:00:02,000\n[音乐]\n\n"
               "3\n00:00:02,000 --> 00:00:03,000\n【笑声】后半句\n")
        self.assertEqual(self.extract(self.write("g.srt", src)), "真正的内容后半句")

    def test_merges_multiline_cue(self):
        src = "1\n00:00:00,000 --> 00:00:02,000\n上半句\n下半句\n"
        self.assertEqual(self.extract(self.write("h.srt", src)), "上半句下半句")

    def test_dedupes_rolling_captions(self):
        """滚动字幕：后一条常以前一条为前缀，只应留最长的那条。"""
        src = ("1\n00:00:00,000 --> 00:00:01,000\n我们今天\n\n"
               "2\n00:00:01,000 --> 00:00:02,000\n我们今天要讲\n\n"
               "3\n00:00:02,000 --> 00:00:03,000\n我们今天要讲的是这个\n")
        self.assertEqual(self.extract(self.write("i.srt", src)), "我们今天要讲的是这个")

    def test_keep_lines_gives_one_cue_per_line(self):
        text = self.extract(self.write("j.srt", BASIC), "--keep-lines")
        self.assertEqual(text.split("\n"), ["第一句", "第二句"])

    def test_gap_splits_paragraphs(self):
        """cue 之间静音超过阈值就分段。"""
        src = ("1\n00:00:00,000 --> 00:00:01,000\n第一段\n\n"
               "2\n00:00:09,000 --> 00:00:10,000\n第二段\n")
        self.assertIn("\n\n", self.extract(self.write("k.srt", src), "--gap", "2"))

    def test_gap_zero_disables_splitting(self):
        src = ("1\n00:00:00,000 --> 00:00:01,000\n第一段\n\n"
               "2\n00:00:09,000 --> 00:00:10,000\n第二段\n")
        self.assertNotIn("\n\n", self.extract(self.write("l.srt", src), "--gap", "0"))

    # --- 失败路径：这些是有意的行为，cleaner 的定义依赖它们 ---

    def test_plain_text_input_fails_loudly(self):
        """喂纯文本必须报错退出，不能静默产出空结果。

        cleaner 的定义里专门写了这条分支：输入不是字幕时要跳过 srt2txt。
        """
        proc = run(SRT2TXT, str(self.write("m.txt", "就是一段普通文字。\n没有时间轴。\n")))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no timecoded cues", proc.stderr)

    def test_empty_file_fails(self):
        proc = run(SRT2TXT, str(self.write("n.srt", "")))
        self.assertNotEqual(proc.returncode, 0)

    def test_cues_that_clean_to_nothing_fail(self):
        src = "1\n00:00:00,000 --> 00:00:01,000\n[音乐]\n\n2\n00:00:01,000 --> 00:00:02,000\n【掌声】\n"
        proc = run(SRT2TXT, str(self.write("o.srt", src)))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("all empty after cleaning", proc.stderr)

    def test_missing_file_fails(self):
        proc = run(SRT2TXT, str(self.tmp / "不存在.srt"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no such file", proc.stderr)


# ------------------------------------------------------------- srt-verify

RAW = "我们今天呢要讲的是这个对吧非常重要的概念"


class TestSrtVerify(TempDirCase):
    def verify(self, raw: str, clean: str, *args: str) -> subprocess.CompletedProcess:
        a = self.write("raw.txt", raw)
        b = self.write("clean.md", clean)
        return run(SRT_VERIFY, str(a), str(b), *args)

    def test_pure_deletion_passes(self):
        """只删语气词——正是允许的操作，不应报出任何改动。"""
        proc = self.verify(RAW, "我们今天要讲的是这个非常重要的概念", "--whole")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("改动原文之处: 0", proc.stdout)

    def test_added_punctuation_and_spacing_ignored(self):
        """加标点、加空格、重新分段都会被归一化掉，不算改写。"""
        clean = "我们今天，要讲的是这个。\n\n非常重要的概念！"
        proc = self.verify(RAW, clean, "--whole")
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_rewrite_is_caught(self):
        """替换措辞必须被抓出来。"""
        proc = self.verify(RAW, "我们今天要讲的是那个非常重要的概念", "--whole")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("改动原文之处", proc.stdout)

    def test_insertion_is_caught(self):
        proc = self.verify(RAW, "我们今天要讲的是这个特别特别非常重要的概念", "--whole")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("改动原文之处", proc.stdout)

    def test_exit_code_counts_findings(self):
        """退出码等于问题数，所以 `srt-verify ... && echo OK` 能用。"""
        proc = self.verify("甲乙丙", "甲丁丙", "--whole")
        self.assertEqual(proc.returncode, 1)

    def test_whole_flag_covers_text_after_horizontal_rule(self):
        """不加 --whole 时 `---` 之后算总结区，加了就整篇按正文查。"""
        raw, clean = "甲乙丙", "甲乙丙\n\n---\n\n丁"
        loose = self.verify(raw, clean)                 # 丁 落在总结区，正文检查看不到
        strict = self.verify(raw, clean, "--whole")     # 丁 属于正文，是新增
        self.assertEqual(loose.returncode, 0, loose.stdout)
        self.assertNotEqual(strict.returncode, 0)

    def test_deletion_is_not_detectable(self):
        """已知局限：过度删除永远是子序列，改写检查判不出来。

        这条测试锁住的是"我们知道它拦不住什么"，README 里也写明了。
        真正约束删除范围的是 cleaner 定义里的规则，不是这个脚本。
        """
        proc = self.verify(RAW, "我们", "--whole")
        self.assertEqual(proc.returncode, 0)

    # --- 从"过度删除"里切出来的、后果最严重的一块 ---

    def test_deleted_negation_is_caught(self):
        """删掉一个「不」，意思就反了，而它仍然是严格子序列。"""
        proc = self.verify("这不是推荐方案", "这是推荐方案", "--whole")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("删掉了 不", proc.stdout)

    def test_deleted_number_is_caught(self):
        proc = self.verify("我们有三个选项", "我们有个选项", "--whole")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("删掉了 三", proc.stdout)

    def test_arabic_digit_deletion_is_caught(self):
        proc = self.verify("跑了 60 分钟", "跑了 0 分钟", "--whole")
        self.assertNotEqual(proc.returncode, 0)

    def test_declared_correction_touching_a_number_is_not_flagged(self):
        """`一遍 -> 以便` 这类已申报的纠错是 replace，不该被当成删数字。

        改写检查已经报了它、也要求申报，这里再报一次就是重复噪音。
        """
        proc = self.verify("写进文件里一遍我随后查看", "写进文件里以便我随后查看", "--whole")
        self.assertIn("被删掉的否定词/数字: 0", proc.stdout)

    def test_filler_deletion_does_not_trip_the_guard(self):
        """现行删除清单里的词一个都不含否定词或数字，所以不该误报。"""
        proc = self.verify(RAW, "我们今天要讲的是这个非常重要的概念", "--whole")
        self.assertIn("被删掉的否定词/数字: 0", proc.stdout)

    def test_syllable_of_an_ordinary_word_is_not_a_negation(self):
        """「非常」的非、「特别」的别、「未来」的未都不是否定，不该误报。"""
        for src in ("这非常重要", "这特别重要", "说的是未来", "无论如何"):
            with self.subTest(src=src):
                proc = self.verify(src, "", "--whole")
                self.assertIn("被删掉的否定词/数字: 0", proc.stdout)

    def test_real_negation_still_caught_next_to_lookalikes(self):
        """例外名单不能把真的否定也放过去。"""
        proc = self.verify("非常不重要", "非常重要", "--whole")
        self.assertIn("删掉了 不", proc.stdout)


# ------------------------------------------------------------ transcribe

class TestSrtTime(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(transcribe.srt_time(0), "00:00:00,000")

    def test_milliseconds(self):
        self.assertEqual(transcribe.srt_time(1.5), "00:00:01,500")

    def test_hours(self):
        self.assertEqual(transcribe.srt_time(3661.25), "01:01:01,250")

    def test_negative_clamped_to_zero(self):
        self.assertEqual(transcribe.srt_time(-1), "00:00:00,000")

    def test_rounds_not_truncates(self):
        self.assertEqual(transcribe.srt_time(0.9999), "00:00:01,000")


class TestNormalizePunctuation(unittest.TestCase):
    def test_converts_sentence_punctuation(self):
        self.assertEqual(transcribe.normalize_punctuation("好.真的?是!"), "好。真的？是！")

    def test_leaves_decimals_alone(self):
        self.assertEqual(transcribe.normalize_punctuation("大约 1.5 倍"), "大约 1.5 倍")

    def test_leaves_thousands_separator_alone(self):
        self.assertEqual(transcribe.normalize_punctuation("有 1,000 行"), "有 1,000 行")

    def test_converts_comma_between_words(self):
        self.assertEqual(transcribe.normalize_punctuation("甲,乙"), "甲，乙")


class TestCollectInputs(TempDirCase):
    def setUp(self):
        super().setUp()
        self.layout = transcribe.Layout(self.tmp)
        self.layout.inbox.mkdir(parents=True)

    def touch(self, name: str) -> Path:
        path = self.layout.inbox / name
        path.write_bytes(b"x")
        return path

    def test_empty_inbox_raises(self):
        with self.assertRaises(FileNotFoundError):
            transcribe.collect_inputs(None, self.layout)

    def test_missing_inbox_raises(self):
        shutil.rmtree(self.layout.inbox)
        with self.assertRaises(FileNotFoundError):
            transcribe.collect_inputs(None, self.layout)

    def test_ignores_non_media_files(self):
        self.touch("笔记.txt")
        self.touch("封面.png")
        with self.assertRaises(FileNotFoundError):
            transcribe.collect_inputs(None, self.layout)

    def test_picks_up_media_and_sorts(self):
        self.touch("b.mp4")
        self.touch("a.m4a")
        self.touch("说明.txt")            # 非媒体，应被滤掉
        names = [p.name for p in transcribe.collect_inputs(None, self.layout)]
        self.assertEqual(names, ["a.m4a", "b.mp4"])

    def test_suffix_match_is_case_insensitive(self):
        self.touch("大写.MP4")
        self.assertEqual(len(transcribe.collect_inputs(None, self.layout)), 1)

    def test_explicit_file_bypasses_inbox(self):
        outside = self.tmp / "别处.mp4"
        outside.write_bytes(b"x")
        got = transcribe.collect_inputs(str(outside), self.layout)
        self.assertEqual([p.name for p in got], ["别处.mp4"])

    def test_explicit_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            transcribe.collect_inputs(str(self.tmp / "无.mp4"), self.layout)


class TestArchive(TempDirCase):
    def setUp(self):
        super().setUp()
        self.layout = transcribe.Layout(self.tmp)
        self.layout.inbox.mkdir(parents=True)

    def test_moves_out_of_inbox(self):
        source = self.layout.inbox / "课.mp4"
        source.write_bytes(b"x")
        transcribe.archive(source, self.layout)
        self.assertFalse(source.exists())
        self.assertTrue((self.layout.done / "课.mp4").exists())

    def test_name_collision_keeps_both(self):
        """重名不能覆盖——之前那份也是用户的素材。"""
        self.layout.done.mkdir(parents=True)
        (self.layout.done / "课.mp4").write_bytes(b"old")
        source = self.layout.inbox / "课.mp4"
        source.write_bytes(b"new")
        transcribe.archive(source, self.layout)
        survivors = sorted(p.name for p in self.layout.done.iterdir())
        self.assertEqual(len(survivors), 2, survivors)
        self.assertEqual((self.layout.done / "课.mp4").read_bytes(), b"old")

    def test_file_outside_inbox_is_left_alone(self):
        """拖进来的单个文件不属于收件箱，不该被搬走。"""
        outside = self.tmp / "别处.mp4"
        outside.write_bytes(b"x")
        transcribe.archive(outside, self.layout)
        self.assertTrue(outside.exists())
        self.assertFalse(self.layout.done.exists())


class TestFactsOnly(TempDirCase):
    """导读是生成物，允许新措辞，但硬事实必须在正文里有出处。"""

    BODY = "我们讲了《思考的真相》这本书，Git 有 3 个核心概念，作者是李笑来。"

    def facts(self, digest: str) -> subprocess.CompletedProcess:
        a = self.write("body.md", self.BODY)
        b = self.write("digest.md", digest)
        return run(SRT_VERIFY, str(a), str(b), "--facts-only")

    def test_new_wording_is_allowed(self):
        """概括性词语原文没出现过也没关系——这正是导读和逐字稿的区别。"""
        proc = self.facts("**主旨**：讲版本控制的认知模型，从一本书讲起。")
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("查无出处的专名/数字: 0", proc.stdout)

    def test_invented_book_title_is_caught(self):
        proc = self.facts("提到了《原则》这本书。")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("《原则》", proc.stdout)

    def test_invented_number_is_caught(self):
        proc = self.facts("Git 有 7 个核心概念。")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("7", proc.stdout)

    def test_invented_latin_token_is_caught(self):
        proc = self.facts("讲了 Git 和 Mercurial。")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("Mercurial", proc.stdout)

    def test_facts_present_in_body_pass(self):
        proc = self.facts("《思考的真相》，Git，3 个概念，李笑来。")
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_exit_code_counts_missing_facts(self):
        proc = self.facts("《原则》和 Mercurial。")
        self.assertEqual(proc.returncode, 2)

    def test_timestamps_are_not_treated_as_facts(self):
        """`00:30` 是回跳音频的导航元数据，不是正文要支持的主张。

        不排除的话，一份带 13 个时间戳的导读会报出 20 处"查无出处的数字"，
        全是误报，真正的问题会被淹掉。
        """
        proc = self.facts("- `00:30` 讲了一本书\n- `12:05` 又讲了别的")
        self.assertIn("查无出处的专名/数字: 0", proc.stdout)

    def test_a_real_number_next_to_timestamps_is_still_caught(self):
        proc = self.facts("- `00:30` 一共有 99 个概念")
        self.assertIn("99", proc.stdout)

    def test_facts_only_skips_the_rewrite_check(self):
        """导读整篇都是新写的，不该被当成改写原文。"""
        proc = self.facts("完全不同的措辞，一个原文的句子都没有照抄。")
        self.assertNotIn("改动原文之处", proc.stdout)


class TestFindLoops(unittest.TestCase):
    """复读机幻觉是下游唯一发现不了的污染，所以检测它的逻辑要有测试。"""

    @staticmethod
    def seg(texts):
        return [(float(i), i + 1.0, t) for i, t in enumerate(texts)]

    def test_no_repetition_is_clean(self):
        self.assertEqual(transcribe.find_loops(self.seg(["甲", "乙", "丙"])), [])

    def test_two_in_a_row_is_below_threshold(self):
        """讲者重复一句是强调，不是幻觉。默认要连着三段才算。"""
        self.assertEqual(transcribe.find_loops(self.seg(["甲", "甲", "乙"])), [])

    def test_three_in_a_row_is_flagged(self):
        found = transcribe.find_loops(self.seg(["乙", "甲", "甲", "甲", "丙"]))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][2], "甲")

    def test_span_covers_the_whole_run(self):
        found = transcribe.find_loops(self.seg(["甲", "甲", "甲", "甲"]))
        self.assertEqual((found[0][0], found[0][1]), (0.0, 4.0))

    def test_two_separate_loops(self):
        found = transcribe.find_loops(self.seg(["甲"] * 3 + ["丙"] + ["乙"] * 3))
        self.assertEqual([f[2] for f in found], ["甲", "乙"])

    def test_empty_input(self):
        self.assertEqual(transcribe.find_loops([]), [])


class TestLayout(TempDirCase):
    def test_all_paths_under_home(self):
        layout = transcribe.Layout(self.tmp)
        for path in (layout.inbox, layout.output, layout.done, layout.models):
            self.assertEqual(path.parent, self.tmp)

    def test_caches_are_redirected_into_data_dir(self):
        """模型缓存必须落在数据目录，不能散到 C 盘。"""
        import os
        for key in ("HF_HOME", "HF_HUB_CACHE", "XDG_CACHE_HOME"):
            os.environ.pop(key, None)
        models = self.tmp / "models"
        transcribe.configure_caches(models)
        self.assertTrue(os.environ["HF_HOME"].startswith(str(models)))
        self.assertTrue(os.environ["HF_HUB_CACHE"].startswith(str(models)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
