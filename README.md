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

只需命令行核心、不启动网页时，可以改用 `pip install -e .` 安装较少依赖。

## 启动上传页面

```powershell
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8765
```

浏览器打开 `http://127.0.0.1:8765/` 即可使用，无需登录。每次上传填写后的照片或单页 PDF 时，都要选择目标字体库；可以选择已有库，也可以填写名称新建库。多次上传到同一个库会合并到 `data/fonts/english/<字体名称>`。顶部可以切换正在查看和拼接的字体库。页面展示所选字体库最近上传的校正页、累计提取数量和逐字预览；点击字形可对照原格裁图。页面地址中的 `?font=<字体名称>` 可直接打开指定字体库。旧版哈希目录如未导入任何命名字体库，会显示导入入口。

在“拼接文字”多行框中直接粘贴文字。**每个换行和空行都会保留**，不会自动折行。每个字符先随机用完所有可用字形，再重新洗牌循环使用；只有完全缺少该字符字形时才阻止生成。可调整字大小、字距随机幅度、行距和背景。每次生成保存随机种子与实际选用的字形，结果可重新打开并下载 PNG。当前不支持 `.txt` 上传。

生成后点击“编辑字形与排版”打开编辑器。画布按实际像素显示，支持缩放和横向滚动。点击字母可替换手写版本、拖动位置、调整大小和字前间距；绿色间距线会移动该字及同一行后面的字。Shift 点击可按文字顺序连选，Ctrl 点击可增减选中字形，从画布空白处拖动可框选；拖动任一选中字形即可整体移动，方向键也作用于整组，Esc 清除选择。还可轻度对齐基线、整体移动某行、撤销/重做。编辑结果保存到该拼接编号的清单和 PNG，重新打开可继续编辑；下载时会先保存尚未保存的修改。字形版本可停用或重新启用，停用影响后续生成，不会改动已保存的拼接图。

上传数据保存为：

```text
data/
  file/<编号>.jpg                        原始上传文件
  fonts/english/<字体名称>/
    pages/<上传编号>/registered_page.png   该次上传的校正页
    pages/<上传编号>/cells/r01_c01.png   每格原始裁图
    glyphs/U+0041/<上传编号>-001.png      合并后的透明字形
    manifest.json                        累计样本、上传记录与质检标记
  renders/english/<拼接编号>/
    composition.png                      拼接结果
    manifest.json                        原文、参数、随机种子、字形选取与位置
```

每次上传和拼接仍有独立编号，避免覆盖旧结果。HTTP 接口包括 `GET/POST /api/fonts`、`POST /api/fonts/{字体名称}/claim/{旧编号}`、`POST /api/imports`（表单需传 `font_name`）、`GET /api/imports/{字体名称}`、`PATCH /api/imports/{字体名称}/sample`、`POST /api/compositions`、`GET /api/compositions/{id}` 和 `GET/PUT /api/compositions/{id}/draft`，以及对应图片、原图和清单的读取接口；FastAPI 的 `/docs` 提供接口文档。编辑保存使用修订号防止旧页面覆盖新结果。上传大小限制为 50 MB。

## 命令行运行

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

`pkg/handwriting_concat` 是独立核心包。`pipeline.py` 编排字形提取，`composition.py` 负责缺字检查、随机选样和保留换行的排版。`api/router` 处理 HTTP，`api/handler` 管理导入及拼接结果，`api/model` 定义响应，`frontend` 是静态页面。提取细节见[提取技术方案](docs/handwriting-extraction.md)。

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[web,test]"
.\.venv\Scripts\python.exe -m pytest -q
```
