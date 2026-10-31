# 手写字拼接器：模板字形提取

目前实现了**模板上传、字形提取和多行文字拼接**。程序读取四角 ArUco 定位码，校正页面，逐格生成透明 PNG。网页可上传、查看字形，并在多行输入框里粘贴文字，按原有换行生成拼接图。同一字体库可以上传多张采集页，字形合并到一个目录。

## 环境

在项目目录创建并使用独立虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[web,test]"
```

PNG、JPEG、TIFF 由 Pillow 解码。PDF 输入另外需要系统能运行 `pdfinfo` 和 `pdftoppm`（Poppler）；这两个命令不安装进 `.venv`。模板与 JSON 在本项目中：[A4 PDF](手写字母采集模板_A4.pdf)、[坐标数据](pkg/handwriting_concat/assets/template_v2.json)。

只需单页字形提取命令行时，可以改用 `pip install -e .` 安装较少依赖。本地 agent CLI 复用网页的编辑处理层，需要安装 `.[web]`。

## 启动上传页面

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8765
```

浏览器打开 `http://127.0.0.1:8765/` 即可使用，无需登录。每次上传填写后的照片或单页 PDF 时，都要选择目标字体库；可以选择已有库，也可以填写名称新建库。多次上传到同一个库会合并到 `data/fonts/english/<字体名称>`。顶部可以切换正在查看和拼接的字体库。页面展示所选字体库最近上传的校正页、累计提取数量和逐字预览；点击字形可对照原格裁图。页面地址中的 `?font=<字体名称>` 可直接打开指定字体库。旧版哈希目录如未导入任何命名字体库，会显示导入入口。

在“拼接文字”多行框中直接粘贴文字。**每个换行和空行都会保留**，不会自动折行。用 `~~word~~` 给一个完整英文词加删除线，标记本身不会出现在成品中。程序用连续英文字母识别词，优先使用词库中的整词 PNG；没有整词版本时才逐字母拼接。同一个词或字符先随机用完所有可用版本，再重新洗牌循环使用。只有词和字母都无法覆盖输入内容时才阻止生成。可调整字大小、字距随机幅度、行距和背景。每次生成保存随机种子与实际选用的字形，结果可重新打开并下载 PNG。当前不支持 `.txt` 上传。

生成后点击“编辑字形与排版”打开编辑器。画布按实际像素显示，支持缩放和横向滚动。点击字母或整词可替换版本、拖动位置、调整大小和字前间距；已保存的整词可以拆成字母重新调整。Shift 点击可按文字顺序连选，Ctrl 点击可增减选中字形，从画布空白处拖动可框选；拖动任一选中字形即可整体移动，方向键也作用于整组，Esc 清除选择。还可轻度对齐基线、整体移动某行、撤销/重做。编辑结果保存到该拼接编号的清单和 PNG，重新打开可继续编辑；下载时会先保存尚未保存的修改。编辑完成后可点击“挑选词存入词库”，候选词默认全选，可逐个取消或用按钮全选/取消全选；下载 PNG 时也会询问。被删除线划掉的词不进入候选列表。词库只保存透明 PNG，按词名建目录、按出现位置和修订号保存不同版本。字形版本可停用或重新启用；编辑器会把当前草稿中已停用或删除的版本自动换成可用版本。首页“逐字查看”可删除单个样本或整个字符的全部版本。删除会从可用字库移除它们并保留旧文件，确保已有拼接图仍能打开。

上传数据保存为：

```text
data/
  file/<编号>.jpg                        原始上传文件
  fonts/english/<字体名称>/
    pages/<上传编号>/registered_page.png   该次上传的校正页
    pages/<上传编号>/cells/r01_c01.png   每格原始裁图
    glyphs/U+0041/<上传编号>-001.png      合并后的透明字形
    words/Happy/<拼接编号>-0-0-r1.png     编辑后保存的整词透明图片
    manifest.json                        累计样本、上传记录与质检标记
  renders/english/<拼接编号>/
    composition.png                      拼接结果
    manifest.json                        原文、参数、随机种子、字形选取与位置
```

每次上传和拼接仍有独立编号，避免覆盖旧结果。HTTP 接口包括 `GET/POST /api/fonts`、`POST /api/fonts/{字体名称}/claim/{旧编号}`、`POST /api/imports`（表单需传 `font_name`）、`GET /api/imports/{字体名称}`、`PATCH/DELETE /api/imports/{字体名称}/sample`、`DELETE /api/imports/{字体名称}/character`、`POST /api/compositions`、`GET /api/compositions/{id}`、`GET/PUT /api/compositions/{id}/draft`、`POST /api/compositions/{id}/transform`、`POST /api/compositions/{id}/align-baselines`、`GET /api/compositions/{id}/word-candidates` 和 `POST /api/compositions/{id}/words`，以及对应图片、原图和清单的读取接口；FastAPI 的 `/docs` 提供接口文档。编辑保存使用修订号防止旧页面覆盖新结果。上传大小限制为 50 MB。

## 命令行运行

### 让本地 agent 拼接和编辑

项目根目录的 `AGENTS.md` 记录了 agent 的完整操作流程。无需启动网页或配置 MCP；直接使用项目 `.venv` 中的 Python 调用本地 CLI：

```powershell
.\.venv\Scripts\python.exe -m api.agent_cli fonts
Get-Content -Raw -Encoding UTF8 .\text.txt | .\.venv\Scripts\python.exe -m api.agent_cli compose --font "en-潦草" --text-file -
.\.venv\Scripts\python.exe -m api.agent_cli inspect <拼接编号> --line 0
.\.venv\Scripts\python.exe -m api.agent_cli apply <拼接编号> --revision 0 --ops .\edits.json
.\.venv\Scripts\python.exe -m api.agent_cli align-baselines <拼接编号> --revision 1
.\.venv\Scripts\python.exe -m api.agent_cli word-candidates <拼接编号>
.\.venv\Scripts\python.exe -m api.agent_cli export <拼接编号> --output .\final.png
```

命令返回 JSON 和图片绝对路径。`apply` 的操作示例及各命令用途见 `AGENTS.md`。词候选需要用户挑选后，才用 `save-words` 存入字体库。HTTP 编辑器的“拆开整词”也使用同一套后端变换规则；变换不会自动保存，仍可在网页里撤销后再保存。

### 单页字形提取

```powershell
.\.venv\Scripts\python.exe -m handwriting_concat "填写后的扫描图.jpg" -o "output\我的字迹"
```

也可传入单页 PDF。默认根据照片中 9 mm 定位码的像素尺寸估算输出 DPI，最高 600；需要固定尺寸时用 `--dpi 300` 或 `--dpi 600`。PDF 渲染 DPI 可用 `--pdf-dpi` 调整，默认 600。`--layout` 可以指定其他版本 2 的坐标 JSON。输出目录需为空，工具不会覆盖已有字形库。

Python 调用：

```python
from handwriting_concat import extract_page

report = extract_page("scan.jpg", "output/my-handwriting")
print(report.manifest_path, report.glyph_count, report.review_count)
```

结果目录包含：

```text
output/my-handwriting/
  source.jpg                原始上传文件
  registered_page.png       拉正后的整页
  cells/r01_c01.png         每个应填写格的原始裁图
  glyphs/U+0041/001.png     透明字形，按 Unicode 码点归档
  manifest.json             坐标、文件位置、质量标记、校对状态
```

`manifest.json` 中的 `flags` 可能包含 `empty`、`touches_border`、`low_contrast`。没有真实填写样本前，这些阈值仍需校准；自动标记只是校对提示。`accepted` 初始为 `null`，留给后续校对界面填写。缺字不会由印刷字体自动补齐。

## 代码结构

`pkg/handwriting_concat` 是独立核心包。`pipeline.py` 编排字形提取，`composition.py` 负责缺字检查、随机选样和保留换行的排版，`editing.py` 处理按原文位置定位的编辑操作。`api/router` 处理 HTTP，`api/handler` 管理导入及拼接结果，`api/model` 定义请求与响应，`api/agent_cli.py` 是本地 agent 入口，`frontend` 是静态页面。提取细节见[提取技术方案](docs/handwriting-extraction.md)。

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[web,test]"
.\.venv\Scripts\python.exe -m pytest -q
```
