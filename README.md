# ILoveUI

A lightweight, immediate-mode GUI framework built with Pygame, designed for rapid UI development and easy debugging.

一个基于 Pygame 构建的轻量级立即模式 GUI 框架，专为快速 UI 开发和便捷调试设计。

## 特性 / Features
- Immediate-mode GUI: No complex state management, write UI logic directly
- Rich components: Buttons, text, input fields, sliders, checkboxes, scroll views, etc.
- Flexible layout system: Box, Row, Column, Lazy list for large data
- Animation support: Smooth transitions and coroutine-based animations
- Popup system: Toast, dialog, draggable windows
- Powerful debugging tools: Render layer control, performance monitoring, rect visualization
- Event system: Mouse, keyboard, touch, and scroll events
- Lightweight & customizable: Easy to extend and adapt to your needs
-
- 立即模式 GUI：无需复杂状态管理，直接编写 UI 逻辑
- 丰富组件：按钮、文本、输入框、滑块、复选框、滚动视图等
- 灵活布局：盒子、行、列、懒加载列表（支持海量数据）
- 动画支持：平滑过渡和基于协程的动画
- 弹窗系统：提示框、对话框、可拖动窗口
- 强大调试：渲染层控制、性能监控、矩形可视化
- 事件系统：鼠标、键盘、触摸、滚轮事件
- 轻量可定制：易于扩展和适配需求

## 快速开始 / Quick Start

安装依赖 / Install Dependencies

```bash
pip install pygame
```

直接运行 .py 文件 / Run main script directly

```bash
python iloveui.py
```

## 最小示例 / Minimal Example

```python
from iloveui import fast_debug, FastStartContext, ILoveUI, popup_layer, text, column_content

def main_ui(u: ILoveUI, ctx: FastStartContext):
    popup_layer(u)

    @column_content(u)
    def content(u: ILoveUI):
        text(u, "Hello ILoveUI!")
        text(u, f"FPS: {ctx.fps:.1f}")

    content

if __name__ == '__main__':
    fast_debug(main_ui)
```

## 核心概念 / Core Concepts

### 立即模式 UI

UI is rebuilt every frame, no need to manually manage component states.

UI 每帧重新构建，无需手动管理组件状态。

### UIPath

Unique identifier for component state management:

组件状态管理的唯一标识：

```python
root = UIPath.root()

def main_ui(u: ILoveUI, ctx: FastStartContext):
    value_ref: list[int] = (root / 'main').remember(lambda: [0])  # Persistent state 持久化状态

    def inc_count(_):
        value_ref[0] += 1

    text(u, f"count: {value_ref[0]}") \
        .clickable(highlight, inc_count) \
        .align_xy(0.5, 0.5)

if __name__ == '__main__':
    fast_debug(main_ui)

```

## 布局系统

- box: Stack components, fill available space
- row: Horizontal layout
- column: Vertical layout
- lazy_list_column/row: Lazy loading for large datasets
-
- box：堆叠组件，填充可用空间
- row：水平布局
- column：垂直布局
- lazy_list_column/row：大数据集懒加载

## 组件示例 / Component Examples

### 可点击按钮 / Clickable Button
```python
text(u, "Click Me").clickable(highlight, lambda _: toast(u, "Clicked!"))
```

### 文本输入框 / Text Field
```python
text_ref = (id / 'text_ref').remember(lambda: Ref.new_box(""))
text_field(u, id / "input", text_ref, placeholder="Type here...")
```

### 滑块 / Slider
```python
value_ref = (id / 'value_ref').remember(lambda: Ref.new_box(50.0))
slider(u, value_ref, 0, 100)
```

### 滚动视图 / Scroll View
```python
@column_content(u)
def items(u):
    text(u, "Item -2")
    text(u, "Item -1")

    for i in range(10):
        text(u, f"Item {i}")

items \
    .v_scroll(id / 'items scroll')
    .min_size_xy(0, 100)
```

### 惰性滚动列表 / Lazy Scroll List
```python
@lazy_list_column_content(u, id / "list", range(1000))
def items(u, i):
    return text(u, f"Item {i}")

items \
    .min_size_xy(0, 100)
```

### 弹窗 / Popup
```python
toast(u, "Notification")  # Toast
dialog(u, "Confirm?", yes_or_no_callback, cancel_callback)  # Dialog
window(u, window_content)  # Draggable window
```

## 调试工具 / Debug Tools
- Render layer control: Debug rendering step by step
- Performance monitor: Render time tracking
- Rect visualization: View component boundaries
- Single-step mode: Pause and step through frames
-
- 渲染层控制：逐步骤调试渲染
- 性能监控：渲染时间追踪
- 矩形可视化：查看组件边界
- 单步模式：暂停并逐帧执行

## 项目结构 / Project Structure
```plaintext
iloveui/
├── Core:          ILoveUIContext, Placeable, Modifying
├── Layouts:       box, row, column, lazy_list
├── Widgets:       text, button, input, slider, scroll
├── Popups:        toast, dialog, window
├── Renderer:      PygameILoveUIRenderer
└── Debug:         render_layer_control, performance monitor
```

## 许可证 / License

MIT License
