# Design system

## Direction

本地创作工作台。冷白与浅蓝灰表面、天蓝色主操作、深蓝灰文字。拼接预览和手写字形保持白底与充足留白。

## Colors

- Accent: `#2389E8`; hover: `#116DC2`; selected: `#E8F3FF`.
- App background: `#F5F8FC`; surface: `#FFFFFF`.
- Main text: `#243449`; muted text: `#536276`; borders: `#DCE5EF`.
- Error and warning are reserved for status, never for navigation or decoration.

## Typography

System UI / Noto Sans SC / Microsoft YaHei. One family with 13–15 px controls, 18–20 px section titles and 26 px page title. Handwriting is shown only in image previews.

## Layout

Desktop workspace uses a 224 px sidebar, flexible main region, and balanced input/preview columns. Editor uses a 68 px rail, flexible canvas, and 320 px inspector. Narrow screens stack the main columns and keep controls reachable.

## Shared components

Buttons: primary, secondary, quiet and danger variants share height, radius and focus treatment. Modal: native dialog with common heading, body and action area. Popup select: button and bounded option popover synchronized with a native select for form state and progressive enhancement. Inputs and status messages share tokens.

## Motion

Short state transitions only. Respect `prefers-reduced-motion`.
