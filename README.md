# ILoveUI.py
ILoveUI — Pygame Immediate Mode GUI                         简单的 python 立即模式 gui 库

Lightweight immediate-mode UI library built for Pygame, pure Python, no extra dependencies. 可以轻易替换后端实现

Features
- ✅ Chain-style modifier API (background/click/align/flex)  链式调用风格的 modifier api
- ✅ Flex row/column layout system,                          弹性 row/column 布局系统
- ✅ Built-in widgets: Text / Input Field / Slider           内置 Text / Input Field / Slider 组件
- ✅ Popup dialog & Toast notification                       内置 Popup dialog & Toast 组件
- ✅ Abstract render layer (easy to replace renderer)        抽象渲染层, 可轻易替换实现
- ✅ Unified mouse/touch event system
Quick Start
Install pygame
```bash
pip install pygame
```
Run main script directly
```bash
python main.py
```

Preview                               预览
- Click text to trigger toast tips    点击顶部 'hello world' 按钮, 显示 'hello' toast
- Select fruit buttons                点击水果按钮选择水果
- Edit text input & drag slider       修改文本框, 拖动滑块
- Pop up confirm dialog               点击底部按钮弹出确认弹窗

Structure                                  代码结构
- Core event manager & render abstraction  核心事件管理器和渲染抽象层
- Immediate-mode UI context & state cache  立即模式 ui 上下文 / 全局状态保存
- Ready-to-use basic components & layout   开箱即用的基础组件和布局
- Popup/toast global layer                 弹窗和 toast 系统
- Extendable                               可拓展
- Add custom widgets / replace renderer / modifier easily. 可轻易添加自定义控件 / 渲染器 / modifier
