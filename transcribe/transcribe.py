"""把视频/音频批量转写成 SRT 字幕（faster-whisper，全本地）。

代码和数据分离：本脚本可以放在任何地方，数据目录由 --home 指定。

    transcribe.py                      # 处理 <当前目录>/待转写 里的全部文件
    transcribe.py --home D:\\课程        # 指定数据根目录
    transcribe.py 某个文件.mp4          # 只处理这一个
    transcribe.py --model large-v3 --device cpu

数据根目录（--home，默认当前目录）下的结构：

    待转写/    收件箱，扫这里
    输出/      产出 .srt
    已处理/    转写成功的源文件移到这里
    models/    模型缓存（首次运行自动下载）
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


SUPPORTED = {
    ".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma",
}

# 这些档位在 2GB 显存上跑到一半会 OOM，且错误发生在逐段转写过程中来不及回退，
# 所以 --device auto 时直接给 CPU。显存充裕的机器用 --device cuda 覆盖。
GPU_SAFE_MODELS = {"small"}


class Layout:
    """数据根目录下的四个子目录。"""

    def __init__(self, home: Path):
        self.home = home
        self.inbox = home / "待转写"
        self.output = home / "输出"
        self.done = home / "已处理"
        self.models = home / "models"


def configure_caches(models: Path) -> None:
    """把所有 Hugging Face 缓存关进数据目录，不散落到 C 盘。

    必须在 import faster_whisper 之前调用。
    """
    os.environ.setdefault("HF_HOME", str(models / "huggingface"))
    os.environ.setdefault("HF_HUB_CACHE", str(models / "huggingface" / "hub"))
    os.environ.setdefault("XDG_CACHE_HOME", str(models / ".cache"))
    # hf_xet 的快速传输在部分网络环境下会卡死不动，改用普通 HTTP 下载。
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


def normalize_punctuation(text: str) -> str:
    """把句读标点换成中文形式，但不动数字里的点和逗号。"""
    text = re.sub(r"(?<!\d),(?!\d)", "，", text)
    text = re.sub(r"(?<!\d)\.(?!\d)", "。", text)
    return text.translate(str.maketrans({"?": "？", "!": "！", ":": "：", ";": "；"}))


def srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def collect_inputs(value: str | None, layout: Layout) -> list[Path]:
    """一个指定的文件，或者收件箱里排队的全部文件。"""
    if value:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"找不到输入文件：{path}")
        return [path]

    if not layout.inbox.is_dir():
        raise FileNotFoundError(f"收件箱不存在：{layout.inbox}")

    pending = sorted(
        path for path in layout.inbox.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED
    )
    if not pending:
        raise FileNotFoundError(
            f"「待转写」里没有媒体文件。\n"
            f"把要转写的录屏/录音放进：{layout.inbox}\n"
            f"（局域网传输工具的接收目录建议就设成这里，传完直接跑本脚本。）"
        )
    return pending


def archive(source: Path, layout: Layout) -> None:
    """把转完的源文件移出收件箱，下次就不会重复处理。"""
    if source.parent != layout.inbox:
        return                       # 单独指定的文件不属于收件箱，原地不动
    layout.done.mkdir(parents=True, exist_ok=True)
    target = layout.done / source.name
    if target.exists():
        target = layout.done / f"{source.stem}_{int(time.time())}{source.suffix}"
    shutil.move(str(source), str(target))
    print(f"源文件已归档：{target}")


def register_cuda_dlls() -> None:
    """让 ctranslate2 找得到 pip 装进 venv 的 CUDA 运行库。

    pip 装的 nvidia-cublas-cu12 / nvidia-cudnn-cu12 的 DLL 不在系统 PATH 里，
    不注册的话 GPU 能加载成功、但一转写就报 DLL 找不到。
    """
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    site_packages = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    for pkg in ("cublas", "cudnn", "cuda_nvrtc"):
        bin_dir = site_packages / pkg / "bin"
        if bin_dir.is_dir():
            os.add_dll_directory(str(bin_dir))
            # ctranslate2 的原生扩展按标准 DLL 搜索顺序（含 PATH）加载依赖，
            # 只调用 add_dll_directory 不够，必须把目录也塞进 PATH。
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def load_model(name: str, device: str, threads: int, models: Path):
    register_cuda_dlls()
    from faster_whisper import WhisperModel

    want_gpu = device == "cuda" or (device == "auto" and name in GPU_SAFE_MODELS)
    if device == "auto" and not want_gpu:
        print(f"模型 {name} 在小显存机器上跑 GPU 容易 OOM，自动选择 CPU。"
              f"显存充裕可以加 --device cuda 覆盖。")

    if want_gpu:
        try:
            model = WhisperModel(name, device="cuda", compute_type="int8",
                                 download_root=str(models))
            print("加速：GPU（CUDA / int8）")
            return model
        except Exception as exc:
            if device == "cuda":
                raise
            print(f"GPU 不可用（{exc}），回退到 CPU。", file=sys.stderr)

    model = WhisperModel(name, device="cpu", compute_type="int8",
                         cpu_threads=threads, download_root=str(models))
    print(f"加速：CPU（int8，{threads} 线程）")
    return model


def transcribe_one(model, source: Path, layout: Layout, language: str) -> Path | None:
    """写出 输出/<名字>.srt，返回路径；没听到人声则返回 None。"""
    segments, info = model.transcribe(
        str(source),
        task="transcribe",
        language=language,
        beam_size=5,
        temperature=0,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=True,
    )

    duration = max(float(info.duration), 0.001)
    print(f"音频时长：{duration / 60:.1f} 分钟，开始识别……")

    collected: list[tuple[float, float, str]] = []
    started = time.time()
    for segment in segments:
        text = normalize_punctuation(segment.text.strip())
        if text:
            collected.append((segment.start, segment.end, text))
        progress = min(100.0, segment.end / duration * 100)
        print(f"\r进度：{progress:5.1f}%  {segment.end / 60:6.1f}/{duration / 60:.1f} 分钟",
              end="", flush=True)
    print()

    if not collected:
        print("没有识别到语音，未生成结果。", file=sys.stderr)
        return None

    layout.output.mkdir(parents=True, exist_ok=True)
    srt_path = layout.output / f"{source.stem}.srt"
    parts = [
        f"{index}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n"
        for index, (start, end, text) in enumerate(collected, 1)
    ]
    srt_path.write_text("\n".join(parts), encoding="utf-8-sig")

    print(f"用时 {(time.time() - started) / 60:.1f} 分钟 → {srt_path}")
    return srt_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="用 faster-whisper 把视频/音频批量转成 SRT 字幕（供 cleaner 清洗）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", nargs="?",
                        help="单个文件路径；省略时批量处理收件箱里的全部文件")
    parser.add_argument("--home", default=os.environ.get("LECTURE_HOME"),
                        help="数据根目录，含 待转写/输出/已处理/models（默认当前目录，"
                             "也可用环境变量 LECTURE_HOME）")
    parser.add_argument("--model", default="small",
                        choices=("tiny", "base", "small", "medium", "large-v3"),
                        help="模型大小（默认 small）")
    parser.add_argument("--device", default="auto", choices=("auto", "cuda", "cpu"),
                        help="auto=small 走 GPU、更大的走 CPU；cuda=强制 GPU；cpu=强制 CPU")
    parser.add_argument("--threads", type=int, default=0,
                        help="CPU 线程数（默认自动，取 CPU 核数与 6 的较小值）")
    parser.add_argument("--language", default="zh",
                        help="识别语言（默认 zh；写 auto 让模型自己判断）")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    home = Path(args.home).expanduser().resolve() if args.home else Path.cwd()
    layout = Layout(home)
    configure_caches(layout.models)          # 必须早于 import faster_whisper

    layout.inbox.mkdir(parents=True, exist_ok=True)
    layout.models.mkdir(parents=True, exist_ok=True)

    try:
        sources = collect_inputs(args.input, layout)
    except FileNotFoundError as exc:
        print(f"\n{exc}\n", file=sys.stderr)
        return 2

    threads = args.threads or max(1, min(6, os.cpu_count() or 4))
    language = None if args.language == "auto" else args.language

    print(f"数据目录：{home}")
    print(f"待处理：{len(sources)} 个文件")
    for path in sources:
        print(f"  - {path.name}")
    print(f"模型：{args.model}；语言：{args.language}；任务：转写（不翻译）")
    print("正在加载模型……首次使用某个模型会先从网络下载。")

    # 模型只加载一次，整批复用——这是批量模式最主要的时间收益。
    model = load_model(args.model, args.device, threads, layout.models)

    failed: list[str] = []
    for index, source in enumerate(sources, 1):
        print(f"\n===== [{index}/{len(sources)}] {source.name} =====")
        try:
            result = transcribe_one(model, source, layout, language)
        except Exception as exc:                      # 单个文件出错不能拖垮整批
            print(f"转写失败：{exc}", file=sys.stderr)
            failed.append(source.name)
            continue
        if result is None:
            failed.append(source.name)
            continue
        archive(source, layout)                       # 只有成功才归档

    print(f"\n全部结束：成功 {len(sources) - len(failed)} / {len(sources)}")
    print(f"字幕在：{layout.output}")
    if failed:
        print("以下文件没有成功，仍留在收件箱里：", file=sys.stderr)
        for name in failed:
            print(f"  - {name}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
