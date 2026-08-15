# lecture-transcript

把课程录屏变成可读的 markdown 口播稿。转写在本地跑，不上传任何音频。

两个部分：

- **转写侧**：`faster-whisper` 批量把视频/音频转成 SRT 字幕（Python，Windows/Linux/macOS）
- **清洗侧**：一个 Claude Code 插件，把 SRT 变成能直接读的 markdown

清洗这一步的特点是**只删不写**：除了标点、分段，和它逐条声明的 ASR 错字纠正之外，
输出必须是原文的严格子序列——不新增一个字，不替换措辞，不调整语序。这不靠自觉，
靠一个字符级 diff 脚本在收工前逐字校验。

## 为什么不直接让模型"润色一下"

因为你要的是**讲者说过的话**，不是模型觉得他应该怎么说。

通用的"整理成文稿"会顺手改写句式、合并观点、删掉它认为啰嗦的重复——而口播里的
重复往往是有意强调，半句放弃的话头往往是思路的真实痕迹。等你发现稿子和课不一样，
已经没法知道哪些是原话了。

所以这里把两件事分开：**能机械做的交给脚本**（剥时间轴、字符级校验），
**需要判断的交给模型但上镣铐**（只准删语气词，改任何一个字都必须列进报告）。

## 流程

```
手机录屏  →  传到电脑  →  transcribe.bat  →  cleaner  →  你核对
                          ↓            ↓          ↓
                        .srt         .md      两张表
```

1. **录**：手机录屏（录音机通常拿不到 App 内部音频）。分辨率和码率调到最低，画面用不上。
2. **传**：局域网直传（LocalSend / KDE Connect 一类）到数据目录的 `待转写/`。
3. **转写**：双击 `transcribe.bat`。收件箱里有几个跑几个，跑完源文件自动移进 `已处理/`。
4. **清洗**：在 Claude Code 里说「用 cleaner 清洗 <某个>.srt」。
5. **核对**：cleaner 会返回两张表——改过的 ASR 错字、以及可疑但没敢动的地方（带时间戳）。
   拿时间戳回 `.srt` 搜那个词，跳到音频那一秒听三秒。不用通篇重听。
6. **养表**：这一轮新暴露的错法加进 `glossary.md`，往后每集自动命中。

**第 4 步要在第 5 步之前。** 反过来做（自己先改一遍再交给 cleaner）等于自己承担了
"从几千字里把错字找出来"的成本，而那正是它做得最好的部分。实测：同一门课的两集，
纯自动那集 cleaner 报出 39 处 ASR 错字；先手改过的那集只剩 2 处——另外约 22 处是
手工一个字一个字找出来的。找的成本远高于核的成本。

## 安装

### 转写侧

```bash
git clone <this repo> lecture-transcript
cd lecture-transcript
python -m venv .venv
.venv/Scripts/pip install -r transcribe/requirements.txt   # Windows
# .venv/bin/pip install -r transcribe/requirements.txt      # Linux / macOS
```

`requirements.txt` 里的两个 `nvidia-*` 包是 GPU 加速用的。不装也能跑，会自动回退 CPU。

然后建一个**数据目录**（放在仓库外面，课程内容不进仓库）：

```
我的课程/
├── 待转写/     ← 传输工具的接收目录设成这里
├── 输出/       ← .srt 和 .md
├── 已处理/     ← 自动归档
├── models/     ← 模型缓存，首次运行自动下载
└── glossary.md ← 从 glossary.example.md 复制过来
```

三个子目录不用手建，跑一次会自动创建。

最后告诉脚本数据在哪——复制 `transcribe/local.cfg.example` 成
`transcribe/local.cfg`，填三行：

```ini
LECTURE_HOME=D:\我的课程
MODEL=small
PYTHON=D:\projects\lecture-transcript\.venv\Scripts\python.exe
```

之后双击 `transcribe/transcribe.bat`（或给它建个桌面快捷方式）。

**`.bat` 只在仓库里存在一份，不要复制它。** 机器相关的东西全在 `local.cfg` 里，
而那个文件是 git-ignored 的。这样逻辑只有一处、配置只有一处，不会出现
「改了一份忘了另一份」的漂移。同理，`local.cfg` 里的 `PYTHON=` 让你可以指向
任何已有的解释器，不必为这个项目重建一个 2GB 的虚拟环境。

不用 `.bat` 的话直接跑：

```bash
python transcribe/transcribe.py --home /path/to/我的课程 --model small
```

### 清洗侧

作为 Claude Code 插件安装，`cleaner` agent 和它依赖的两个脚本会一起就位。
装好后在 Claude Code 里直接说「用 cleaner 清洗 xxx.srt」。

如果你不用插件机制，也可以手动把 `agents/cleaner.md` 放进 `~/.claude/agents/`，
并把 `bin/` 里的两个脚本放到 `PATH` 上。

## 模型档位

| 档位 | 设备 | 速度（19 分钟音频） |
|---|---|---|
| `small` | GPU（2GB 显存够用） | 约 4 分钟 |
| `medium` | CPU | 约 30 分钟 |
| `large-v3` | CPU | 更慢 |

默认 `small`。`--device auto` 会把 `medium`/`large-v3` 自动推到 CPU，因为它们在
2GB 显存上跑到一半会 OOM，而且错误发生在逐段转写过程中来不及回退。
显存充裕的机器用 `--device cuda` 覆盖这个保守判断。

**不建议靠堆模型换准确率。** `small` 的错字绝大多数是同音字，上下文足够时 cleaner
能可靠还原，常错的进术语表之后下次自动修。慢八倍换有限的提升不划算。

## 里面有什么

```
.claude-plugin/plugin.json   插件清单
agents/cleaner.md            清洗 agent 的完整定义（约束都写在这里）
bin/srt2txt                  字幕 → 纯文本，剥时间轴/标签/音效/滚动重复
bin/srt-verify               字符级 diff，校验"只删不写"
transcribe/transcribe.py     批量转写
transcribe/transcribe.bat    Windows 启动器（配置读 local.cfg）
glossary.example.md          术语表示例
```

`bin/` 里两个脚本是纯 Python 标准库，无依赖，也可以单独拿去用：

```bash
srt2txt talk.srt --keep-lines -o raw.txt
srt-verify raw.txt talk.md --whole
```

## 测试

```bash
python -m unittest discover -s tests -v
```

44 个测试，只用标准库，不需要装 faster-whisper（`transcribe.py` 把模型的 import
放在函数里，纯逻辑部分可以脱离模型测试）。覆盖的是这三块：

- **`srt2txt`**：编码（BOM / CRLF / GBK / UTF-16）、标记清理（HTML / ASS / 音效方括号）、
  跨行 cue 合并、滚动字幕去重、中英文间距、按停顿分段——以及**三条失败路径**：
  喂纯文本必须报错退出、空文件必须失败、cue 清理后全空必须失败。
  最后这几条是有意的行为，`cleaner` 的定义依赖它们。
- **`srt-verify`**：只删应通过、加标点和重新分段不算改写、替换和新增必须被抓出、
  退出码等于问题数、`--whole` 与默认模式的区别。
  另有一条测试专门锁住**它拦不住什么**（见下）。
- **`transcribe.py`**：时间戳格式化（含进位与负数钳制）、标点转换不误伤小数和千分位、
  收件箱扫描（空目录、缺目录、非媒体文件、大小写后缀、排序）、
  归档（重名不覆盖、收件箱外的文件不搬）、缓存重定向。

## 已知的取舍

- **转写用 SRT 不用纯文本。** 时间轴是唯一无法事后恢复的信息，生成它不花额外成本，
  而它是第 5 步定位音频的唯一手段。断句和分段交给 cleaner 按语义做，不用脚本硬切。
- **`srt-verify` 拦不住过度删除。** 删除永远是子序列，脚本判不出来。它能拦住的是
  改写和新增。不删实词这条靠 agent 定义里的规则约束。
- **它也拦不住"用原文出现过的字重新拼出来的假话"。** 因果、程度、立场无法机器校验。

## License

MIT
