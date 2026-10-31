# 本地手写字拼接工作流

用户给出需要拼接的段落时，直接使用项目内 CLI 完成工作。默认字体库是 `en-潦草`；若它不存在，先运行 `fonts` 并选择现有字体库。保留用户原文的换行、空行和大小写。`~~word~~` 表示给完整英文词加删除线，标记不会出现在成品中。不要修改 `data/fonts` 中的原始字形。

在项目根目录运行 `./.venv/Scripts/python.exe -m api.agent_cli`。所有成功命令向 stdout 输出 UTF-8 JSON；失败向 stderr 输出 JSON 并返回非零状态。无需启动网页或配置 MCP。输入文字用 `compose --font en-潦草 --text-file -` 从标准输入读取，也可以传 UTF-8 文件路径。不要把多行文字拼在 shell 参数里。

## 工作步骤

1. 用 `fonts` 查看库。用 `compose` 生成草稿，并记下返回的 `id`、`revision` 和绝对图片路径。缺字时告知用户缺少的字符，不要自行替换原文。
2. 用图片查看工具打开返回的 PNG。用 `inspect <id>` 查看每行字符的原文列号、实际坐标、尺寸、当前间距和可选字形。可用 `inspect <id> --line 0` 获取单行预览，或 `--region X Y WIDTH HEIGHT` 查看局部。行号和列号从 0 开始。
3. 需要对齐普通英文字母的底部时，运行 `align-baselines <id> --revision <当前修订号>`；可加 `--line 0` 只处理一行。它一次移动到该行的中位数基线，没有网页按钮的 8 px 步长限制。发现其他错位、过大空隙或重叠时，写一个 UTF-8 JSON 数组操作文件，然后运行 `apply <id> --revision <当前修订号> --ops <文件>`。每次操作后重新查看图片；不要仅凭数值判断最终视觉效果。编辑操作使用原文行号和列号定位，即使拆词后 placement 数量变化也不改变位置含义。位置实际改变后修订号加 1；对齐已到位时不会产生新修订号。
4. 用 `word-candidates <id>` 查看可保存的整词及各自预览。**保存到词库之前，先把候选词和预览展示给用户，让用户选择要保存的实例。**仅对用户选中的 key 运行 `save-words <id> --revision <当前修订号> --keys 0-0 1-5`。没有得到选择时，直接交付拼接图，不保存词。
5. 用 `export <id> --output <目标.png>` 导出成品，并向用户提供绝对路径。若不需要复制，`export <id>` 返回当前 PNG 路径。

## 编辑操作格式

`apply` 的 `--ops` 文件是 JSON 数组。以下操作可以在一次调用中顺序执行：

```json
[
  {"type": "move", "line": 0, "column": 3, "dx": 2, "dy": -4},
  {"type": "move", "line": 0, "column": 5, "end_column": 10, "dx": 8, "dy": 0},
  {"type": "set_gap", "line": 0, "column": 12, "gap_px": 6},
  {"type": "move_line", "line": 1, "dx": 0, "dy": 5},
  {"type": "replace_variant", "line": 1, "column": 2, "sample_file": "glyphs/U+0041/示例.png"},
  {"type": "replace_unavailable"},
  {"type": "split_word", "line": 2, "column": 0}
]
```

`move` 不带 `end_column` 时移动该位置的单个字形或整词；带结束列时选中 `[column, end_column)` 内的完整字形。`set_gap` 把目标与前一个字形的间距设为指定像素，并平移该行后续字形。`replace_variant` 的 `sample_file` 从 `inspect` 返回的 `variants` 中选，字符和整词类型必须相同。`replace_unavailable` 把当前草稿中已停用或已从字库删除的字形换成可用版本；若字符没有其他版本，该位置保留原图并需要提示用户。`split_word` 把已复用的词拆成可编辑字母；原词只保存了 PNG，因此拆开时会重新选字母并估算初始位置，需要再次查看和调整。所有操作都会检查画布边界、字形归属及修订号。

`align-baselines` 只处理普通英文字母，跳过小写 `g、j、p、q、y`、标点和整词图片。它按每行字母 `y + 高度` 的中位数对齐；如果某个字母太高，目标基线会下移，避免将笔迹移出画布上边缘。对齐后仍需看图确认视觉效果。

CLI 操作数据不会修改字体库，只有 `save-words` 会新增词图片。`data/renders/english/<id>` 存每次拼接的清单和当前 PNG。使用项目 `.venv`；如缺依赖，按 README 中的安装命令处理。
