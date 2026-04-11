# pynt: paint

import copy
import enum
import iloveui as ui
import os
import pygame

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from iloveui import ILoveUI
from typing import Any, Callable, TypeVar

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

        # 撤销/重做栈
        self.undo_stack = deque(maxlen=30)  # 限制最大撤销步数
        self.redo_stack = deque()

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
                if self.active_layer == name:
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

    # ==================== 撤销/重做 ====================
    def undo(self) -> bool:
        """撤销上一步操作"""
        if not self.undo_stack:
            return False
        # 保存当前状态到重做栈
        current_state = {
            "layers": copy.deepcopy(self.layers),
            # "order": copy.deepcopy(self.layer_order),
            "active": self.active_layer
        }
        self.redo_stack.append(current_state)

        # 恢复上一个状态
        state = self.undo_stack.pop()
        self.layers = state["layers"]
        # self.layer_order = state["order"]
        self.active_layer = state["active"]
        return True

    def redo(self) -> bool:
        """重做撤销的操作"""
        if not self.redo_stack:
            return False
        # 保存当前状态到撤销栈
        current_state = {
            "layers": copy.deepcopy(self.layers),
            # "order": copy.deepcopy(self.layer_order),
            "active": self.active_layer
        }
        self.undo_stack.append(current_state)

        # 恢复重做状态
        state = self.redo_stack.pop()
        self.layers = state["layers"]
        # self.layer_order = state["order"]
        self.active_layer = state["active"]
        return True

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



class Tool(Enum):
    brush = enum.auto()
    fill_bucket = enum.auto()

class Screen:
    def __init__(self) -> None:
        self.core = PixelCanvasCore(16, 16, pygame.Color(16, 16, 16))
        self.tool = Tool.brush

    def set_mode(self, value: Tool):
        self.tool = value

    def surface_ui(self, u: ILoveUI, sur: pygame.Surface) -> ui.Modifying:
        def place_fn(ctx: ui.PlaceContext):
            @ctx.deferred_render_tick
            def render():
                ctx.context.renderer.screen_surface.blit(pygame.transform.scale(sur, (ctx.rect.w, ctx.rect.h)), (ctx.rect.x, ctx.rect.y))

        return u.element(place_fn, sur.get_width(), sur.get_height()) \
            .ratio_pad(sur.get_width(), sur.get_height())

    def canvas_ui(self, u: ILoveUI) -> ui.Modifying:
        core = self.core
        sur = core.render()

        def place_fn(ctx: ui.PlaceContext):
            def handle_touch(finger: ui.Finger):
                x, y = (
                    int(sur.get_width() * (finger.x - ctx.rect.x) // ctx.rect.w),
                    int(sur.get_height() * (finger.y - ctx.rect.y) // ctx.rect.h)
                )
                match self.tool:
                    case Tool.brush:
                        core.draw_brush(x, y)

                    case Tool.fill_bucket:
                        core.fill_bucket(x, y)

            def consume_finger_event(e: ui.NewFingerEvent) -> bool:
                in_rect = e.finger.in_rect(ctx)
                if in_rect:
                    handle_touch(e.finger)
                    e.finger.on_drag(handle_touch)
                return in_rect
            ctx.context.event_manager.consume_events(ui.NewFingerEvent, consume_finger_event)

            @ctx.deferred_render_tick
            def render():
                ctx.context.renderer.screen_surface.blit(pygame.transform.scale(sur, (ctx.rect.w, ctx.rect.h)), (ctx.rect.x, ctx.rect.y))

        return u.element(place_fn, sur.get_width(), sur.get_height()) \
            .ratio_pad(core.width, core.height)

    def left_panel(self, u: ILoveUI) -> ui.Modifying:
        @ui.column_content(u)
        def top(u: ILoveUI):

            def palette_color(u: ILoveUI, idx: int, color: pygame.Color) -> ui.Modifying:
                def click(_):
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
                    .clickable(ui.highlight, click, ui.Color(color.r, color.g, color.b, color.a))

                if self.core.current_color_idx == idx:
                    v.padding_xy(4, 4) \
                        .background(ui.green)

                return v

            ui.manageable_list(
                u, self.core.palette, palette_color,
                insert_at=lambda idx: self.core.palette.insert(idx, pygame.Color(255, 255, 255)),
            ) \
                .align_xy(0, 0)

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
                ui.text(u, "Export All") \
                    .clickable(ui.highlight, lambda _: print("导出完成：", self.core.export_png())) \
                    .background(ui.gray) \
                    .flex()

        return top

    def right_panel(self, u: ILoveUI) -> ui.Modifying:
        def layer_ui(u: ILoveUI, idx: int, layer: Layer) -> ui.Modifying:
            @ui.column_content(u)
            def top(u: ILoveUI):
                def set_active(_):
                    self.core.active_layer = idx

                v = self.surface_ui(u, layer.surface) \
                    .min_size_xy(80, 80) \
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
