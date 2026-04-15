# pynt: paint

import array
import copy
import dataclasses
import enum

import iloveui as ui
import os
import pygame

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from iloveui import ILoveUI, Modifying, NewFingerEvent, PlaceContext, Placeable, Rect, toast
from typing import Any, Callable, Generic, Literal, TypeVar

T = TypeVar('T')

def remove_if(pred: Callable[[int, T], bool], lst: list[T]) -> int:
    removed = 0
    for i in range(len(lst) - 1, -1, -1):
        if pred(i, lst[i]):
            del lst[i]
            removed += 1

    return removed

def find_index(pred: Callable[[int, T], bool], lst: list[T]) -> int | None:
    for i, e in enumerate(lst):
        if pred(i, e):
            return i
    return None

def find(pred: Callable[[int, T], bool], lst: list[T]) -> T | None:
    for i, e in enumerate(lst):
        if pred(i, e):
            return e
    return None

@dataclass(slots=True)
class TreeNode(Generic[T]):
    value: T
    parent: 'TreeNode[T] | None' = None
    children: list['TreeNode'] = field(default_factory=list)

    def remove_self(self) -> bool:
        """从父节点移除自己"""
        if self.parent is None:
            return False
        self.parent.children.remove(self)
        self.parent = None
        return True

    def insert_child(self, n: 'TreeNode[T]', idx: int | None = None):
        """插入子节点，自动断开原父节点"""
        n.remove_self()
        n.parent = self

        if idx is None:
            self.children.append(n)
        else:
            self.children.insert(idx, n)

    def dfs(self, fn: Callable[['TreeNode'], bool]):
        if not fn(self):
            return

        for e in self.children:
            e.dfs(fn)

    def count_nodes(self) -> int:
        count = 0
        def inc(_) -> Literal[True]:
            nonlocal count
            count += 1
            return True

        self.dfs(inc)
        return count



@dataclass(slots=True)
class UTNode(Generic[T]):
    v: T
    depth: int

@dataclass(slots=True)
class UndoTree(Generic[T]):
    '''
    分支式撤销重做树
    push 不会清除后续节点，而是创建新分支
    '''

    root: TreeNode[UTNode[T]] | None = None
    curr: TreeNode[UTNode[T]] | None = None

    def is_empty(self) -> bool:
        """树是否为空"""
        return self.root is None

    @property
    def curr_value(self) -> T | None:
        """获取当前节点的值"""
        return self.curr.value.v if self.curr else None

    def push(self, value: T):
        """
        在当前节点下新建子节点，并切换到该节点
        不会删除原有子节点，而是创建新分支
        """
        new_node = TreeNode(UTNode(value, self.curr.value.depth + 1 if self.curr else 0))

        if self.root is None:
            # 空树：设为根节点
            self.root = new_node
            self.curr = new_node
        else:
            # 非空：插入到当前节点下
            self.curr.insert_child(new_node) # type: ignore
            self.curr = new_node

    def undo(self) -> T | None:
        """
        撤销：回到父节点
        返回撤销前的当前节点值，无法撤销返回 None
        """
        if self.curr is None or self.curr.parent is None:
            return None

        undo_value = self.curr_value
        self.curr = self.curr.parent
        return undo_value

    def redo(self) -> T | None:
        """
        重做：进入子节点
        有多个子节点时，默认进入最后一个子节点
        返回新的当前节点值，无法重做返回 None
        """
        if self.curr is None or len(self.curr.children) == 0:
            return None

        self.curr = self.curr.children[-1]
        return self.curr_value

    def goto(self, n: TreeNode[UTNode[T]]):
        """
        直接跳转到指定节点
        节点必须属于这棵树
        """
        self.curr = n

    def clear(self):
        """清空整棵树"""
        self.root = None
        self.curr = None

    def print_tree(self, node: TreeNode[UTNode[T]] | None = None, indent: int = 0):
        """打印树结构（调试用）"""
        if node is None:
            node = self.root
        if node is None:
            print("空树")
            return

        print("  " * indent + f"- {node.value}")
        for child in node.children:
            self.print_tree(child, indent + 1)

@dataclass(slots=True)
class Command:
    name: str
    execute: Callable[[], None]
    undo: Callable[[], None]
    render_fn: Callable[[ILoveUI, TreeNode[UTNode['Command']]], Modifying]
    rect: Rect = ui.Rect(0, 0, 100, 100)

def layout_command_tree(n: TreeNode[UTNode[Command]], pos: tuple[float, float] = (0, 0)) -> float:
    '''
    @return height
    '''
    size = 100
    if not n.children:
        n.value.v.rect = Rect(pos[0], pos[1], size, size)
        return size

    height = 0
    for e in n.children:
        height += layout_command_tree(e, (pos[0] + size, pos[1] + height))

    n.value.v.rect = Rect(pos[0], pos[1] + height / 2 - size / 2, size, size)
    return height

# off = -100
# scl = 1
# cen = -off * scl
# print(f'{cen = }')
# nscl = 0.2
# errcen = -off * nscl
# print(f'{errcen = }')
# noff = -cen / nscl
# print(f'{noff = }')
# ncen = -noff * nscl
# print(f'{ncen = }')

@dataclass(slots=True)
class TreeUI:
    id: ui.UIPath = field(default_factory=ui.UIPath.root)
    offset_x: float = 0
    offset_y: float = 0
    scale: float = 1

    def set_offset(self, xy: tuple[float, float]):
        x, y = xy
        self.offset_x = x
        self.offset_y = y

    def tree_ui(self, u: ILoveUI, tree: TreeNode[UTNode[Command]]) -> Modifying:
        def modifier(p: Placeable) -> Placeable:
            def place_fn(ctx: PlaceContext):
                def consume_key_event(e: ui.KeyEvent) -> bool:
                    old_center = -self.offset_x * self.scale, -self.offset_y * self.scale

                    if e.keycode == pygame.K_EQUALS:
                        self.scale *= 1.1
                    elif e.keycode == pygame.K_MINUS:
                        self.scale *= 0.9
                    else:
                        return False

                    self.scale = ui.clamp(0.1, self.scale, 100)

                    self.offset_x = -old_center[0] / self.scale
                    self.offset_y = -old_center[1] / self.scale
                    print(self.scale)

                    return True
                ctx.context.event_manager.consume_events(ui.KeyEvent, consume_key_event)

                p.place_fn(ctx)

            return dataclasses.replace(p, place_fn=place_fn)

        def render_content(ctx: PlaceContext):
            def iter_node(n: TreeNode[UTNode[Command]]) -> Literal[True]:

                def render_node(u: ILoveUI):
                    n.value.v.render_fn(u, n)

                rect = Rect(
                    ctx.rect.x + self.offset_x + self.scale * n.value.v.rect.x,
                    ctx.rect.y + self.offset_y + self.scale * n.value.v.rect.y,
                    n.value.v.rect.w,
                    n.value.v.rect.h
                )
                u.context.render_in(rect, render_node, out_render_tick_listeners=ctx.deferred_render_tick_listeners)

                return True

            tree.dfs(iter_node)

        return u.element(render_content) \
            .scissor() \
            .min_size_xy(200, 200) \
            .modifier(modifier) \
            .draggable(ui.Ref(lambda: (self.offset_x, self.offset_y), self.set_offset))



# todo 拖拽插值
# todo 真撤销重做
# todo 调节画布大小和背景色
# todo 图层锁 / 隐藏
# todo 更好的背景
# todo 移动缩放视角
# todo 网格
# todo 橡皮擦工具, 本质就是笔刷只是画的是背景色 x 直接在调色板里显示背景色
# todo 推开工具
# todo 线条工具

@dataclass(slots=True)
class Layer:
    name: str
    surface: pygame.Surface
    dyn: dict[str, Any] = field(default_factory=dict)

class PixelCanvasCore:
    """像素画应用内核，管理所有绘图状态与操作，无UI依赖"""
    def __init__(self, width: int, height: int, bg_color: pygame.Color | None = None):
        # 画布基础属性
        self.width = width
        self.height = height
        # 背景色（默认纯黑透明）
        self.bg_color = bg_color if bg_color else pygame.Color(0, 0, 0, 0)

        # 图层系统：字典存储 {图层名: surface对象}，有序+可命名
        self.layers: list[Layer] = []
        self.active_layer: int = 0  # 当前激活图层

        # 绘图工具配置
        self.palette: list[pygame.Color] = [pygame.Color(255, 255, 255, 255)] # 调色板：存储pygame.Color对象
        self.current_color_idx = 0  # 当前选中颜色
        self.brush_radius = 1  # 画笔半径（1=单像素）
        self.opacity = 255  # 全局透明度 0-255

        # 初始化空白画布
        self._init_empty_canvas()

    @property
    def current_color(self) -> pygame.Color:
        return self.palette[self.current_color_idx]

    @property
    def current_color_with_opacity(self) -> pygame.Color:
        v = self.current_color
        return pygame.Color(v.r, v.g, v.b, v.a * self.opacity // 255)

    # ==================== 基础画布初始化 ====================
    def _init_empty_canvas(self):
        """初始化空白画布（创建默认图层）"""
        self.add_layer("默认图层")
        self.set_active_layer("默认图层")

    def _save_state(self):
        """保存当前所有图层状态，用于撤销/重做（核心方法）"""
        return # ai 代码复制 surface 出错, 应该改成基于稀疏 diff 的
        # 深拷贝所有图层数据
        state = {
            "layers": copy.deepcopy(self.layers),
            "order": copy.deepcopy(self.layer_order),
            "active": self.active_layer
        }
        self.undo_stack.append(state)
        self.redo_stack.clear()  # 新操作清空重做栈

    # ==================== 图层管理（可命名） ====================
    def add_layer(self, name: str, idx: int = -1):
        """添加命名图层，返回是否成功"""
        # 创建带透明通道的图层
        sur = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        sur.fill(self.bg_color)
        if idx < 0:
            idx = len(self.layers)
        self.layers.insert(idx, Layer(name, sur))
        self._save_state()

    def remove_layer(self, name: str) -> bool:
        """删除指定图层"""
        for idx, layer in enumerate(self.layers):
            if layer.name == name:
                del self.layers[idx]
                # 如果删除的是激活图层，切换到最后一个图层
                if self.active_layer == idx:
                    self.active_layer = len(self.layers) - 1
                self._save_state()
                return True
        return False

    def set_active_layer(self, name: str) -> bool:
        """设置当前激活图层"""
        idx = find_index(lambda i, e: e.name == name, self.layers)
        if idx is None:
            return False
        self.active_layer = idx
        return True

    def get_layer(self) -> pygame.Surface | None:
        """获取指定图层（默认获取激活图层）"""
        if 0 <= self.active_layer < len(self.layers):
            return self.layers[self.active_layer].surface
        return None

    # ==================== 调色板管理 ====================
    def add_color(self, color: pygame.Color):
        """添加颜色到调色板"""
        if color not in self.palette:
            self.palette.append(color)

    def remove_color(self, index: int):
        """删除调色板颜色"""
        if 0 <= index < len(self.palette):
            self.palette.pop(index)

    def set_opacity(self, alpha: int):
        """设置全局透明度（0-255）"""
        self.opacity = max(0, min(255, alpha))

    # ==================== 绘图工具 ====================
    def set_brush_radius(self, radius: int):
        """设置画笔半径（最小1）"""
        self.brush_radius = max(1, radius)

    def draw_brush(self, x: int, y: int):
        """圆形画笔绘制（核心）"""
        layer = self.get_layer()
        if not layer:
            return

        self._save_state()
        radius = self.brush_radius
        ext = radius - 1
        color = self.current_color_with_opacity
        # 圆形画笔：遍历半径内所有像素
        for dx in range(-ext, ext + 1):
            for dy in range(-ext, ext + 1):
                if dx**2 + dy**2 <= ext**2:
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < self.width and 0 <= ny < self.height:
                        layer.set_at((nx, ny), color)

    def fill_bucket(self, x: int, y: int):
        """油漆桶填充（四方向连通域，支持透明）"""
        layer = self.get_layer()
        if not layer:
            return

        # 获取目标像素颜色
        try:
            target_color = layer.get_at((x, y))
        except IndexError:
            return
        # 如果目标颜色和当前颜色一致，不操作
        if target_color == self.current_color:
            return

        color = self.current_color_with_opacity

        self._save_state()
        # 广度优先搜索填充
        stack = [(x, y)]
        visited = set()

        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in visited:
                continue
            visited.add((cx, cy))

            # 边界检查
            if not (0 <= cx < self.width and 0 <= cy < self.height):
                continue
            # 非目标颜色，跳过
            if layer.get_at((cx, cy)) != target_color:
                continue

            # 填充像素
            layer.set_at((cx, cy), color)
            # 四方向入栈
            stack.extend([(cx+1, cy), (cx-1, cy), (cx, cy+1), (cx, cy-1)])

    # ==================== 渲染合成 ====================
    def render(self) -> pygame.Surface:
        """合成所有图层，返回最终画布（UI层直接渲染这个Surface）"""
        canvas = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        canvas.fill(self.bg_color)
        # 按顺序叠加图层（从下到上）
        for layer in reversed(self.layers):
            canvas.blit(layer.surface, (0, 0))
        return canvas

    def export_png(self, filepath: str = None) -> str:
        """
        导出当前画布为PNG图片（支持透明）
        :param filepath: 自定义保存路径，为空则自动生成
        :return: 保存的文件路径
        """
        # 自动生成文件名：时间戳+尺寸
        if filepath is None:
            # 创建exports文件夹
            if not os.path.exists("exports"):
                os.makedirs("exports")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = f"exports/paint_{self.width}x{self.height}_{timestamp}.png"

        # 渲染完整画布并保存
        final_surface = self.render()
        pygame.image.save(final_surface, filepath)
        return filepath


@dataclass(slots=True)
class DiffSegment:
    start_raw_data_idx: int
    xor_data: bytes

    def __repr__(self) -> str:
        return f'at {self.start_raw_data_idx}: {self.xor_data}'

def diff_surface(a: pygame.Surface, b: pygame.Surface) -> list[DiffSegment]:
    """
    计算两个 pygame 表面的异或差分，仅保留变化的字节段
    大小/像素格式不同会抛出 ValueError
    """
    # 1. 严格校验尺寸和格式（必须完全一致才能差分）
    if a.get_size() != b.get_size():
        raise ValueError("两个 Surface 尺寸不一致，无法计算差分")
    if a.get_bitsize() != b.get_bitsize():
        raise ValueError("两个 Surface 像素格式不一致，无法计算差分")

    # 2. 获取原始像素字节数据（最底层内存视图，速度最快）
    view_a = memoryview(a.get_view('1'))
    view_b = memoryview(b.get_view('1'))
    data_a = bytes(view_a)
    data_b = bytes(view_b)

    if len(data_a) != len(data_b):
        raise ValueError("Surface 原始数据长度不一致")

    item_n_bytes = 4
    item_type = 'I'
    bytes_a = array.array(item_type)
    bytes_a.frombytes(data_a)

    bytes_b = array.array(item_type)
    bytes_b.frombytes(data_b)

    # 3. 计算异或并生成连续差分段（跳过全0无变化段）
    diff_segments = []
    total_len = len(bytes_a)
    i = 0

    while i < total_len:
        # 跳过无变化字节
        while i < total_len and bytes_a[i] == bytes_b[i]:
            i += 1
        if i >= total_len:
            break

        # 记录起始位置
        start = i
        # 收集连续变化的字节
        while i < total_len and bytes_a[i] != bytes_b[i]:
            i += 1

        # 生成异或数据段
        xor_segment = array.array(
            item_type,
            (ba ^ bb for ba, bb in zip(bytes_a[start:i], bytes_b[start:i]))
        )
        seg = DiffSegment(start * item_n_bytes, xor_segment.tobytes())
        diff_segments.append(seg)

    return diff_segments


def apply_diff(diff: list[DiffSegment], sur: pygame.Surface):
    """
    将差分异或数据应用到目标 Surface 上
    原地修改，无返回值
    """
    buffer = sur.get_buffer()
    pixel_data = bytearray(buffer.raw)

    # 逐段异或应用差分
    for seg in diff:
        start = seg.start_raw_data_idx
        xor_data = seg.xor_data
        length = len(xor_data)

        # 安全校验
        if start + length > len(pixel_data):
            raise ValueError("差分数据超出 Surface 范围")

        # 核心：逐字节异或
        for i in range(length):
            pixel_data[start + i] ^= xor_data[i]

    buffer.write(bytes(pixel_data), 0)

class Tool(Enum):
    brush = enum.auto()
    fill_bucket = enum.auto()

def surface_ui(u: ILoveUI, sur: pygame.Surface) -> ui.Modifying:
    def place_fn(ctx: ui.PlaceContext):
        @ctx.deferred_render_tick
        def render():
            ctx.context.renderer.screen_surface.blit(pygame.transform.scale(sur, (ctx.rect.w, ctx.rect.h)), (ctx.rect.x, ctx.rect.y))

    return u.element(place_fn, sur.get_width(), sur.get_height()) \
        .ratio_pad(sur.get_width(), sur.get_height())

class Screen:
    def __init__(self) -> None:
        self.core = PixelCanvasCore(16, 16, pygame.Color(16, 16, 16))
        self.tool = Tool.brush
        self.id = ui.UIPath.root()
        self.undo_tree = UndoTree[Command]()

        self.undo_tree.push(Command(
            'idle',
            lambda: None,
            lambda: None,
            lambda u, _: ui.text(u, 'idle') \
                .background(ui.gray)
        ))

    def set_mode(self, value: Tool):
        self.tool = value

    def undo_tree_changed(self):
        if self.undo_tree.root:
            layout_command_tree(self.undo_tree.root)

    def create_command_by_diff(self, diff: list[DiffSegment], icon: pygame.Surface) -> Command:
        def render(u: ILoveUI, n: TreeNode[UTNode[Command]]) -> Modifying:
            @ui.column_content(u)
            def top(u: ILoveUI):
                surface_ui(u, icon).flex()

                ui.text(u, 'no name') \
                    .clickable(ui.highlight, lambda _: toast(u, 'test'))

                if n is self.undo_tree.curr:
                    ui.text(u, 'curr, undo?')

                if n.parent and n.parent is self.undo_tree.curr:
                    ui.text(u, 'next of curr, redo?')

            return top \
                .background(ui.gray)

        return Command(
            'no name',
            lambda: apply_diff(diff, self.core.get_layer()),
            lambda: apply_diff(diff, self.core.get_layer()),
            render
        )

    def canvas_ui(self, u: ILoveUI) -> ui.Modifying:
        core = self.core
        sur = core.render()

        def place_fn(ctx: ui.PlaceContext):
            def handle_touch(finger: ui.Finger):
                x = int(sur.get_width() * (finger.x - ctx.rect.x) // ctx.rect.w)
                y = int(sur.get_height() * (finger.y - ctx.rect.y) // ctx.rect.h)
                match self.tool:
                    case Tool.brush:
                        core.draw_brush(x, y)

                    case Tool.fill_bucket:
                        core.fill_bucket(x, y)

            @NewFingerEvent.consume_events(ctx)
            def consume_finger_event(e: ui.NewFingerEvent):
                original = core.get_layer()

                if original is not None:
                    original = original.copy()

                    handle_touch(e.finger)
                    e.finger.on_drag(handle_touch)

                    @e.finger.on_release
                    def on_release(_):
                        curr = core.get_layer()

                        if curr is None:
                            return

                        diff = diff_surface(original, curr)
                        self.undo_tree.push(self.create_command_by_diff(diff, pygame.transform.scale(curr, (16, 16))))
                        self.undo_tree_changed()

            @ctx.deferred_render_tick
            def render():
                ctx.context.renderer.screen_surface.blit(pygame.transform.scale(sur, (ctx.rect.w, ctx.rect.h)), (ctx.rect.x, ctx.rect.y))

        return u.element(place_fn, sur.get_width(), sur.get_height()) \
            .ratio_pad(core.width, core.height)

    def palette(self, u: ILoveUI) -> Modifying:
        def palette_color(u: ILoveUI, idx: int, color: pygame.Color) -> ui.Modifying:
            def open_color_window(_):
                if self.core.current_color_idx != idx:
                    self.core.current_color_idx = idx
                    return

                @ui.window_content(u, close_layer=True, with_close_button=False)
                def top(u: ILoveUI, ctx: ui.PopupContext):
                    def set_color(v: ui.Color):
                        self.core.palette[idx] = pygame.Color(v.r, v.g, v.b, v.a)

                    def get_color():
                        v = self.core.palette[idx]
                        return ui.Color(v.r, v.g, v.b, v.a)

                    ui.rgba_color_selector(u, ui.Ref(get_color, set_color))

            v = ui.spacing(u, 30, 30) \
                .clickable(ui.highlight, open_color_window, ui.Color(color.r, color.g, color.b, color.a)) \
                .background(ui.black, touch_through=True)

            if self.core.current_color_idx == idx:
                v.padding_xy(4, 4) \
                    .background(ui.green)

            return v.align_xy(0.5, 0.5)

        return ui.manageable_list(
            u, self.core.palette, palette_color,
            insert_at=lambda idx: self.core.palette.insert(idx, pygame.Color(255, 255, 255)),
        )

    def undo_ui(self, u: ILoveUI) -> Modifying:
        @ui.column_content(u)
        def top_col(u: ILoveUI):

            @ui.def_popup_layer
            def open_window(u: ILoveUI, _) -> Modifying:
                if not hasattr(self, '_tree_ui'):
                    self._tree_ui = TreeUI() # type: ignore

                if self.undo_tree.root:
                    v = self._tree_ui.tree_ui(u, self.undo_tree.root)
                else:
                    v = ui.spacing(u)

                return v

            ui.text(u, 'tree') \
                .clickable(ui.highlight, lambda _: open_window(u), ui.gray)

            @ui.row_content(u)
            def btns_row(u: ILoveUI):
                def undo_or_redo(name: str, command: Command | None, execute: Callable[[Command], None]):
                    if command is None:
                        toast(u, f'{name} failed')
                        return
                    execute(command)
                    toast(u, f'{name} success')

                ui.text(u, 'undo') \
                    .clickable(ui.highlight, lambda _: undo_or_redo('undo', self.undo_tree.undo(), lambda c: c.undo()), ui.gray) \
                    .flex()

                ui.text(u, 'redo') \
                    .clickable(ui.highlight, lambda _: undo_or_redo('redo', self.undo_tree.redo(), lambda c: c.execute()), ui.gray) \
                    .flex()

        return top_col

    def info_ui(self, u: ILoveUI) -> Modifying:
        @ui.column_content(u)
        def top(u: ILoveUI):

            ui.text(u, f'tree size: {self.undo_tree.root.count_nodes() if self.undo_tree.root else 0}')

            ui.text(u, 'print') \
                .clickable(ui.highlight, lambda _: print(self.undo_tree.print_tree()))

        return top

    def left_panel(self, u: ILoveUI) -> Modifying:
        @ui.column_content(u)
        def top(u: ILoveUI):

            self.info_ui(u)

            self.undo_ui(u)

            self.palette(u).align_xy(0, 0)

            @ui.row_content(u)
            def tools_row(u: ILoveUI):

                def tool_switch_btn(u: ILoveUI, tool: Tool):
                    ui.text(u, tool.name) \
                        .clickable(ui.highlight, lambda _: self.set_mode(tool), ui.green if self.tool == tool else ui.gray) \
                        .flex()

                tool_switch_btn(u, Tool.brush)
                tool_switch_btn(u, Tool.fill_bucket)

            ui.number_input(u, 'brush radius', ui.Ref(lambda: self.core.brush_radius, self.core.set_brush_radius))

            @ui.row_content(u)
            def export_buttons(u: ILoveUI):
                # 导出完整画布
                def export(_):
                    msg = f"导出完成：{self.core.export_png()}"
                    print(msg)
                    ui.toast(u, msg)

                ui.text(u, "Export All") \
                    .clickable(ui.highlight, export) \
                    .background(ui.gray) \
                    .flex()

        return top

    def right_panel(self, u: ILoveUI) -> ui.Modifying:
        def layer_ui(u: ILoveUI, idx: int, layer: Layer) -> ui.Modifying:
            @ui.column_content(u)
            def top(u: ILoveUI):
                def set_active(_):
                    self.core.active_layer = idx

                v = surface_ui(u, layer.surface) \
                    .min_size_xy(80, 80) \
                    .background(ui.black) \
                    .clickable(ui.highlight, set_active)

                if idx == self.core.active_layer:
                    v.padding_xy(4, 4) \
                        .background(ui.green)

                if 'ui_state' not in layer.dyn:
                    layer.dyn['ui_state'] = ui.UIPath.root()

                ui.text_field(u, layer.dyn['ui_state'], ui.Ref.from_attr(layer, 'name'))

            return top

        def insert_at(idx: int):
            self.core.add_layer('no name', idx)

        return ui.manageable_list(u, self.core.layers, layer_ui, insert_at=insert_at)

    def screen(self, u: ILoveUI):
        ui.popup_layer(u)

        @ui.row_content(u)
        def top(u: ILoveUI):
            self.left_panel(u) \
                .align_xy(0.5, 0.5)

            # 画布组件
            self.canvas_ui(u) \
                .flex()

            self.right_panel(u) \
                .align_xy(0.5, 0.5)

def main():
    s = Screen()
    ui.fast_debug(lambda u, _: s.screen(u))

if __name__ == '__main__':
    main()
