import dataclasses
import pygame
import random
import time

from abc import ABC, abstractmethod
from asyncio import CancelledError
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Any, Callable, Coroutine, Generator, Generic, Hashable, Iterable, Literal, Sequence, Self, TypeVar

T = TypeVar('T')

# ==================== utils ====================

def clamp(min_value: T, value: T, max_value: T) -> T:
    if value < min_value: # type: ignore
        return min_value
    if max_value < value: # type: ignore
        return max_value
    return value

# ==================== api collect ====================

list_modifiers: list[Callable] = []
list_widgets: list[Callable] = []

def modifier_def() -> Callable[[T], T]:
    def decorator(m):
        list_modifiers.append(m)
        return m
    return decorator

def widget_def() -> Callable[[T], T]:
    def decorator(m):
        list_widgets.append(m)
        return m
    return decorator

# ==================== state ====================

@dataclass(frozen=True, slots=True)
class UIPath:
    r'''
    ```
    highlight = Color(255, 255, 255, 127)

    def my_ui(u: ILoveUI, id: UIPath) -> Modifying:
        count_ref = id.remember(lambda: [0])

        def inc_count(_):
            count_ref[0] += 1

        return text(u, f'click me: {count_ref[0]}') \
            .clickable(highlight, inc_count)

    def my_upper_ui_content(u: ILoveUI, id: UIPath):
        my_ui(u, id / 'my ui 1')
        my_ui(u, id / 'my ui 2')
    ```
    '''

    @dataclass(slots=True)
    class StateEntry:
        valid_key: Any
        state_value: Any

    path_tuple: tuple[Hashable, ...]
    state_by_path: dict['UIPath', StateEntry]

    @staticmethod
    def root(state_by_path: dict['UIPath', Any] | None = None) -> 'UIPath':
        return UIPath((), state_by_path if state_by_path is not None else {})

    def __hash__(self) -> int:
        return hash(self.path_tuple)

    def __eq__(self, __value: object) -> bool:
        if self is __value:
            return True
        if not isinstance(__value, UIPath):
            return False
        return (self.state_by_path is __value.state_by_path and
                self.path_tuple == __value.path_tuple)

    def __truediv__(self, key: Hashable) -> 'UIPath':
        '''
        拼接路径
        ```
        new_path = path / 'my btn'
        ```
        '''
        return UIPath((*self.path_tuple, key), self.state_by_path)

    def remember(
        self,
        calc: Callable[[], T],
        valid_key: Any = None,
        on_discard: Callable[[T], None] | None = None,
        need_to_discard: Callable[[T], bool] | None = None,
    ) -> T:
        '''
        当 valid_key 变化时重算
        '''
        state_by_path = self.state_by_path

        entry = state_by_path.get(self)

        def calc_value() -> T:
            value = calc()
            state_by_path[self] = UIPath.StateEntry(valid_key, value)
            return value

        if entry is None:
            return calc_value()

        if (entry.valid_key != valid_key or
            (need_to_discard is not None and need_to_discard(entry.state_value))):

            if on_discard is not None:
                on_discard(entry.state_value)

            return calc_value()

        return entry.state_value

# ==================== coroutine animation ====================

class Suspend:
    def __await__(self):
        yield

suspend = Suspend()


def tick_coroutine_content(id: UIPath, valid_key: Any = None) -> Callable[[Callable[[], Coroutine[Any, Any, None]]], None]:
    '''
    用于协程动画
    '''
    def decorator(async_fn: Callable[[], Coroutine[Any, Any, None]]) -> None:
        tick_coroutine(id, async_fn, valid_key)
    return decorator


def tick_coroutine(id: UIPath, async_fn: Callable[[], Coroutine[Any, Any, None]], valid_key: Any = None) -> None:
    def stop_coroutine(co: Ref[Coroutine[Any, Any, None] | None]) -> None:
        if co.value is not None:
            try:
                co.value.throw(CancelledError)
            except (CancelledError, StopIteration):
                pass

    co = id.remember(lambda: Ref[Coroutine[Any, Any, None] | None].new_box(async_fn()), valid_key, on_discard=stop_coroutine)

    if co.value is not None:
        try:
            co.value.send(None)
        except StopIteration:
            co.value = None

# ==================== events ====================

@dataclass(slots=True)
class Finger:
    """触摸/鼠标指针"""
    x: float
    y: float

    drag_listeners: list[Callable[['Finger'], None]] = field(default_factory=lambda: [])
    release_listeners: list[Callable[['Finger'], None]] = field(default_factory=lambda: [])

    def on_drag(self, listener: Callable[['Finger'], None]) -> None:
        self.drag_listeners.append(listener)

    def on_release(self, listener: Callable[['Finger'], None]) -> None:
        self.release_listeners.append(listener)

    def in_rect(self, ctx: 'PlaceContext', check_scissor_rect: bool = True) -> bool:
        return ((not check_scissor_rect or ctx.context.renderer.contains_point(self.x, self.y)) and
                ctx.rect.contains_point(self.x, self.y))

@dataclass(slots=True)
class NewFingerEvent:
    finger: Finger

@dataclass(slots=True)
class HoveringEvent:
    finger: Finger

@dataclass(slots=True)
class TextInputEvent:
    text: str

@dataclass(slots=True)
class KeyEvent:
    keycode: int
    scancode: int
    unicode: str
    isDown: bool

@dataclass(slots=True)
class ScrollEvent:
    mouse_x: float
    mouse_y: float
    scroll_x: float
    scroll_y: float

    def in_rect(self, ctx: 'PlaceContext', check_scissor_rect: bool) -> bool:
        return ((not check_scissor_rect or ctx.context.renderer.contains_point(self.mouse_x, self.mouse_y)) and
                ctx.rect.contains_point(self.mouse_x, self.mouse_y))

# ==================== core ====================

@dataclass(slots=True)
class Ref(Generic[T]):
    get: Callable[[], T]
    set: Callable[[T], None]

    @property
    def value(self) -> T:
        return self.get()

    @value.setter
    def value(self, value: T) -> None:
        self.set(value)

    @staticmethod
    def from_list_slot(lst: list[T], slot_index: int = 0) -> 'Ref[T]':
        return Ref(lambda: lst[slot_index], lambda value: lst.__setitem__(slot_index, value))

    @staticmethod
    def from_attr(obj: Any, attr_name: str) -> 'Ref[T]':
        return Ref(lambda: getattr(obj, attr_name), lambda value: setattr(obj, attr_name, value))

    @staticmethod
    def new_box(initial_value: T) -> 'Ref[T]':
        lst = [initial_value]
        return Ref.from_list_slot(lst)

    def value_changed(self, callback: Callable[[T, T], None]) -> 'Ref[T]':
        def set_value(value: T):
            old = self.value
            self.value = value # 回调中可能读取 Ref 的数据源, 并且预期数据源已改变, 所以要先赋值, 再回调
            callback(old, value)

        return Ref(self.get, set_value)

    def filter_input(self, predicate: Callable[[T], bool]) -> 'Ref[T]':
        def set_value(value: T):
            if predicate(value):
                self.value = value

        return Ref(self.get, set_value)

    def map_input(self, mapper: Callable[[T], T]) -> 'Ref[T]':
        return Ref(self.get, lambda value: self.set(mapper(value)))



@dataclass(frozen=True, slots=True)
class Color:
    r: int
    g: int
    b: int
    a: int = 255

    def to_tuple(self) -> tuple[int, int, int, int]:
        return (self.r, self.g, self.b, self.a)

highlight = Color(255, 255, 255, 127)
green = Color(20, 255, 20)
gray = Color(20, 20, 20)
white = Color(255, 255, 255)
black = Color(0, 0, 0)



@dataclass(frozen=True, slots=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def center_x(self) -> float:
        return self.x + self.w / 2

    @property
    def center_y(self) -> float:
        return self.y + self.h / 2

    def to_tuple(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.w, self.h)

    def sub_rect_with_align(self, new_w: float, new_h: float, align_x: float, align_y: float) -> 'Rect':
        x = self.x + (self.w - new_w) * align_x
        y = self.y + (self.h - new_h) * align_y
        return Rect(x, y, new_w, new_h)

    def sub_rect_with_offset(self, new_w: float, new_h: float, offset_x: float, offset_y: float) -> 'Rect':
        x = self.x + offset_x
        y = self.y + offset_y
        return Rect(x, y, new_w, new_h)

    def with_padding(self, padding_x: float, padding_y: float) -> 'Rect':
        return Rect(self.x + padding_x, self.y + padding_y, self.w - padding_x * 2, self.h - padding_y * 2)

    def contains_point(self, px: float, py: float) -> bool:
        return (self.x <= px <= self.x + self.w and
                self.y <= py <= self.y + self.h)

    def intersect(self, other: 'Rect') -> 'Rect':
        """
        计算两个矩形的相交矩形（交集）
        如果不相交，返回 x=0,y=0,w=0,h=0 的空矩形
        """
        inter_x = max(self.x, other.x)
        inter_y = max(self.y, other.y)

        inter_right = min(self.x + self.w, other.x + other.w)
        inter_bottom = min(self.y + self.h, other.y + other.h)

        inter_w = max(0, inter_right - inter_x)
        inter_h = max(0, inter_bottom - inter_y)

        return Rect(inter_x, inter_y, inter_w, inter_h)



class Renderer(ABC):
    def get_scissor_enabled(self) -> bool: ...
    def set_scissor_enabled(self, value: bool): ...

    def contains_point(self, x: float, y: float) -> bool:
        scissor = self.scissor_rect
        return scissor is None or scissor.contains_point(x, y)

    @abstractmethod
    def push_scissor(self, rect: Rect, for_render: bool = True) -> None: ...

    @abstractmethod
    def pop_scissor(self) -> None: ...

    @property
    def scissor_rect(self) -> Rect | None: ...

    @abstractmethod
    def get_scissor_count(self) -> int: ...

    @abstractmethod
    def fill_rect(self, rect: Rect, color: Color, line_width: float = 0) -> None: ...

    @dataclass
    class Renderable:
        min_width: float
        min_height: float
        render: Callable[[Rect], None]
        can_render: Callable[[Rect], bool] = field(default=lambda _: True)

    @abstractmethod
    def draw_text(self, text_str: str, color: Color = Color(255, 255, 255)) -> Renderable: ...

    @abstractmethod
    def draw_line(
        self,
        color: Color,
        start_pos: tuple[float, float],
        end_pos: tuple[float, float],
        width: int = 1
    ) -> None: ...

    @abstractmethod
    def fill_circle(
        self,
        x: float,
        y: float,
        radius: float,
        color: Color,
    ) -> None: ...

class RenderOperateType(Enum):
    scissor_op = auto()
    do_render = auto()

@dataclass(slots=True)
class RenderOperate:
    type: RenderOperateType
    operate_fn: Callable[[], None]

@dataclass(slots=True)
class PlaceContext:
    rect: Rect
    context: 'ILoveUIContext'
    deferred_render_tick_listeners: list[RenderOperate]

    def deferred_render_tick(self, operate_fn: Callable[[], None], type: RenderOperateType = RenderOperateType.do_render) -> None:
        self.deferred_render_tick_listeners.append(RenderOperate(type, operate_fn))

@dataclass(slots=True)
class Placeable:
    min_width: float
    min_height: float
    place_fn: Callable[[PlaceContext], None]

@dataclass(slots=True)
class Modifying:
    '''
    包装 placeable 和 flex_weight 的可变对象

    modifier 是顺序相关的
    '''
    placeable: Placeable
    flex_weight: int = 0

    @classmethod
    def all_builtin_modifiers(cls) -> Iterable[str]:
        return filter(lambda s: not s.startswith('_'), dir(cls))

    def flex(self, weight: int = 1) -> Self:
        self.flex_weight = weight
        return self

    def modifier(self, modifier_fn: Callable[[Placeable], Placeable]) -> Self:
        r'''
        ```
        def my_modifier(p: Placeable) -> Placeable:
            ...

        text(u, 'text 1') \
            .modifier(my_modifier)
        ```
        '''
        self.placeable = modifier_fn(self.placeable)
        return self

    def apply(self, operate_fn: Callable[['Modifying'], None]) -> Self:
        r'''
        ```
        def my_ui_style(m: Modifying) -> None:
            m.background(...) \
                .expend(...)

        text(u, 'text 1') \
            .apply(my_ui_style)

        text(u, 'text 2') \
            .apply(my_ui_style)
        ```
        '''
        operate_fn(self)
        return self

    @modifier_def()
    def with_rect(self, rect: Rect, component_min_width: float = 10, component_min_height: float = 10) -> Self:
        '''
        直接指定组件的 rect
        '''
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            p.place_fn(PlaceContext(rect, ctx.context, ctx.deferred_render_tick_listeners))
        self.placeable = Placeable(component_min_width, component_min_height, place_fn)
        return self

    @modifier_def()
    def with_rect_relative(self, rect: Rect, component_min_width: float = 10, component_min_height: float = 10) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            off = ctx.rect
            new_rect = Rect(rect.x + off.x, rect.y + off.y, rect.w, rect.h)
            p.place_fn(PlaceContext(new_rect, ctx.context, ctx.deferred_render_tick_listeners))
        self.placeable = Placeable(component_min_width, component_min_height, place_fn)
        return self

    def map_rect(self, mapper: Callable[[Rect], Rect], component_min_width: float = 10, component_min_height: float = 10) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            p.place_fn(PlaceContext(mapper(ctx.rect), ctx.context, ctx.deferred_render_tick_listeners))
        self.placeable = Placeable(component_min_width, component_min_height, place_fn)
        return self

    def debug_print_rect(self, name: str = 'debug') -> Self:
        p = self.placeable
        min_size = self.placeable.min_width, self.placeable.min_height

        def place_fn(ctx: PlaceContext):
            print(f'[{name}] {min_size=}, {ctx.rect=}')
            p.place_fn(ctx)

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def background(self, color: Color, touch_through: bool = False) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            p.place_fn(ctx)

            if not touch_through:
                ctx.context.event_manager.consume_events(NewFingerEvent, lambda e: e.finger.in_rect(ctx, True))
                ctx.context.event_manager.consume_events(HoveringEvent, lambda e: e.finger.in_rect(ctx, True))

            ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, color))

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def foreground(self, color: Color, touch_through: bool = True) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            if not touch_through:
                ctx.context.event_manager.consume_events(NewFingerEvent, lambda e: e.finger.in_rect(ctx, True))

            ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, color))

            p.place_fn(ctx)

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def clickable(self, hover_color: Color | None, click_callback: Callable[[Finger], None], background_color: Color | None = None, check_scissor_rect: bool = True) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            def consume_new_finger_event(e: NewFingerEvent) -> bool:
                in_rect = e.finger.in_rect(ctx, check_scissor_rect)

                if in_rect:
                    def finger_release_listener(finger):
                        if finger.in_rect(ctx, check_scissor_rect):
                            click_callback(finger)

                    e.finger.on_release(finger_release_listener)

                return in_rect

            ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

            if hover_color is not None:
                def consume_hovering_event(e: HoveringEvent) -> bool:
                    in_rect = e.finger.in_rect(ctx, True)
                    if in_rect:
                        ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, hover_color)) # type: ignore
                    return in_rect

                ctx.context.event_manager.consume_events(HoveringEvent, consume_hovering_event)

            p.place_fn(ctx)

            if background_color is not None:
                ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, background_color)) # type: ignore

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def clickable_background(self, background_color: Color | None, click_callback: Callable[[Finger], None], check_scissor_rect: bool = True) -> Self:
        '''
        用于拦截落在背景而不是 ui 内容的点击,
        可以用来实现点击背景取消弹窗的效果
        '''
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            p.place_fn(ctx)

            def consume_new_finger_event(e: NewFingerEvent) -> bool:
                in_rect = e.finger.in_rect(ctx, check_scissor_rect)

                if in_rect:
                    def release_listener(finger):
                        if e.finger.in_rect(ctx, check_scissor_rect):
                            click_callback(finger)
                    e.finger.on_release(release_listener)

                return in_rect

            ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

            if background_color is not None:
                ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, background_color)) # type: ignore

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def on_touchdown(self, touchdown_callback: Callable[[Finger], None], consume_event: bool = False, check_scissor_rect: bool = True) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            def consume_new_finger_event(e: NewFingerEvent) -> bool:
                in_rect = e.finger.in_rect(ctx, check_scissor_rect)
                if in_rect:
                    touchdown_callback(e.finger)

                return consume_event and in_rect

            ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)
            p.place_fn(ctx)

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def tag_up(self, u: 'ILoveUI', tag_str: str, id: UIPath | None = None, text_color: Color = white) -> Self:
        p = self.placeable

        def box_content(u: ILoveUI):
            text(u, tag_str, id / 'tag_ui' if id is not None else None, color=text_color)
            u.element_placeable(p)

        self.placeable = u.context.to_placeable(box_content, box)
        return self

    def tag_left(self, u: 'ILoveUI', tag_str: str, id: UIPath | None = None, with_spacing: bool = True, min_size: float = 0) -> Self:
        p = self.placeable

        def row_content(u: ILoveUI):
            tag_ui = text(u, tag_str, id / 'tag_ui' if id is not None else None) \
                .min_size_xy(min_size, 0)
            u.element_placeable(p).flex()
            if with_spacing:
                spacing_copy_size(u, tag_ui) # 为了居中

        self.placeable = u.context.to_placeable(row_content, row)
        return self

    def tag_right(self, u: 'ILoveUI', tag_str: str, id: UIPath | None = None, min_size: float = 0) -> Self:
        p = self.placeable

        def row_content(u: ILoveUI):
            u.element_placeable(p).flex()
            text(u, tag_str, id / 'tag_ui' if id is not None else None) \
                .min_size_xy(min_size, 0)

        self.placeable = u.context.to_placeable(row_content, row)
        return self

    def tag_left_right(self, u: 'ILoveUI', tag_left_str: str, tag_right_str: str, id: UIPath | None = None, tag_min_size: float = 0) -> Self:
        p = self.placeable

        def row_content(u: ILoveUI):
            tag_left_ui = text(u, tag_left_str, id / 'tag_left_str' if id is not None else None) \
                .min_size_xy(tag_min_size, 0)

            u.element_placeable(p).flex()

            tag_right_ui = text(u, tag_right_str, id / 'tag_right_str' if id is not None else None) \
                .min_size_xy(tag_min_size, 0)

            mw = max(tag_left_ui.placeable.min_width, tag_right_ui.placeable.min_width)
            mh = max(tag_left_ui.placeable.min_height, tag_right_ui.placeable.min_height)
            tag_left_ui.placeable = Placeable(mw, mh, tag_left_ui.placeable.place_fn)
            tag_right_ui.placeable = Placeable(mw, mh, tag_right_ui.placeable.place_fn)

        self.placeable = u.context.to_placeable(row_content, row)
        return self

    def repaint_flash(self, color: Color = highlight) -> Self:
        '''
        用于测试
        '''
        p = self.placeable
        paint_time = time.time()
        def place_fn(ctx: PlaceContext):
            def render():
                if time.time() - paint_time < 0.1:
                    ctx.context.renderer.fill_rect(ctx.rect, color)

            ctx.deferred_render_tick(render)
            p.place_fn(ctx)

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def memo_max_size(self, id: UIPath) -> Self:
        size_ref = (id / 'size').remember(lambda: Ref[tuple[float, float]].new_box((0, 0)))

        p = self.placeable

        w, h = size_ref.value
        w = max(w, p.min_width)
        h = max(h, p.min_height)
        size_ref.value = (w, h)

        self.placeable = Placeable(w, h, p.place_fn)
        return self

    def animated_rect(self, id: UIPath, init_rect: Callable[[Rect], Rect] | None = None, mix_factor: int = 3) -> Self:
        def mix(a: float, b: float) -> float:
            if abs(a - b) < 1:
                return b
            return (a * mix_factor + b) / (mix_factor + 1)

        last_rect = (id / 'last_rect').remember(lambda: Ref[Rect | None].new_box(None))

        p = self.placeable

        def place_fn(ctx: PlaceContext):
            if last_rect.value is None:
                initial_rect = init_rect(ctx.rect) if init_rect is not None else ctx.rect.sub_rect_with_align(0, 0, 0.5, 0.5)
                last_rect.value = initial_rect
                new_rect = initial_rect
            else:
                lr = last_rect.value
                cr = ctx.rect
                new_rect = Rect(mix(lr.x, cr.x), mix(lr.y, cr.y), mix(lr.w, cr.w), mix(lr.h, cr.h))
                last_rect.value = new_rect

            p.place_fn(PlaceContext(new_rect, ctx.context, ctx.deferred_render_tick_listeners))

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def expend_xy(self, expend_x: float, expend_y: float) -> Self:
        '''
        增加组件的 min_width / min_height
        '''
        p = self.placeable
        self.placeable = Placeable(p.min_width + expend_x, p.min_height + expend_y, p.place_fn)
        return self

    def min_size_xy(self, min_w: float, min_h: float) -> Self:
        p = self.placeable
        if min_w > p.min_width or min_h > p.min_height:
            self.placeable = Placeable(max(p.min_width, min_w), max(p.min_height, min_h), p.place_fn)
        return self

    def ratio_expend(self, ratio_x: int, ratio_y: int) -> Self:
        p = self.placeable

        unit = max(p.min_width / ratio_x, p.min_height / ratio_y)

        self.placeable = Placeable(ratio_x * unit, ratio_y * unit, p.place_fn)
        return self

    def square_expend(self) -> Self:
        p = self.placeable

        size = max(p.min_width, p.min_height)

        self.placeable = Placeable(size, size, p.place_fn)
        return self

    def padding_xy(self, padding_x: float, padding_y: float) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            new_rect = ctx.rect.with_padding(padding_x, padding_y)
            p.place_fn(PlaceContext(new_rect, ctx.context, ctx.deferred_render_tick_listeners))
        self.placeable = Placeable(p.min_width + 2 * padding_x, p.min_height + 2 * padding_y, place_fn)
        return self

    def align_xy(self, align_x: float | None, align_y: float | None) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            new_rect = ctx.rect.sub_rect_with_align(
                p.min_width if align_x is not None else ctx.rect.w,
                p.min_height if align_y is not None else ctx.rect.h,
                align_x if align_x is not None else 0,
                align_y if align_y is not None else 0
            )
            p.place_fn(PlaceContext(new_rect, ctx.context, ctx.deferred_render_tick_listeners))
        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def offset_xy(self, offset_x: float | None, offset_y: float | None) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            new_rect = ctx.rect.sub_rect_with_offset(
                p.min_width if offset_x is not None else ctx.rect.w,
                p.min_height if offset_y is not None else ctx.rect.h,
                offset_x if offset_x is not None else 0,
                offset_y if offset_y is not None else 0
            )
            p.place_fn(PlaceContext(new_rect, ctx.context, ctx.deferred_render_tick_listeners))
        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def getRect(self, outRect: Ref[Rect]) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            outRect.value = ctx.rect
            p.place_fn(ctx)
        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def scissor(self) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            ctx.context.renderer.push_scissor(ctx.rect, for_render=False) # 用于拦截事件
            ctx.deferred_render_tick(lambda: ctx.context.renderer.pop_scissor(), RenderOperateType.scissor_op) # defer 从下到上执行

            p.place_fn(ctx)

            ctx.context.renderer.pop_scissor() # 用于拦截事件
            ctx.deferred_render_tick(lambda: ctx.context.renderer.push_scissor(ctx.rect), RenderOperateType.scissor_op) # defer 从下到上执行
        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def v_scroll(
        self,
        id: UIPath,
        friction: float = 0.92,
        mouse_wheel_speed: float = -8,
        scissor: bool = True,
        out_scope: 'ScrollScope | None' = None
    ) -> Self:
        p = self.placeable
        state = id.remember(ScrollState)
        self.placeable = scroll_modifier(state, p, horizontal=False, friction=friction, mouse_wheel_speed=mouse_wheel_speed, scissor=scissor, out_scope=out_scope)
        return self

    def h_scroll(
        self,
        id: UIPath,
        friction: float = 0.92,
        mouse_wheel_speed: float = -8,
        scissor: bool = True,
        out_scope: 'ScrollScope | None' = None
    ) -> Self:
        p = self.placeable
        state = id.remember(ScrollState)
        self.placeable = scroll_modifier(state, p, horizontal=True, friction=friction, mouse_wheel_speed=mouse_wheel_speed, scissor=scissor, out_scope=out_scope)
        return self



@dataclass(slots=True)
class ScrollState:
    scroll: float = 0
    drag_start: float = 0
    drag_start_scroll: float = 0
    last_drag: float = 0
    velocity: float = 0
    last_time: float = 0
    dragging: bool = False

@dataclass(slots=True)
class ScrollScope:
    viewport_offset: float = 0
    viewport_length: float = float('inf')

def scroll_modifier(
    state: ScrollState,
    element_ui: Placeable,
    horizontal: bool = False,
    friction: float = 0.92,
    mouse_wheel_speed: float = -8,
    scissor: bool = True,
    check_scissor_rect: bool = True,
    out_scope: ScrollScope | None = None
) -> Placeable:

    def place_fn(ctx: PlaceContext):
        nonlocal element_ui
        total_content_size = element_ui.min_width if horizontal else element_ui.min_height
        view_size = ctx.rect.w if horizontal else ctx.rect.h
        max_scroll = max(0, total_content_size - view_size)
        now = time.time()
        dt = now - state.last_time if state.last_time > 0 else 0.016
        state.last_time = now

        #惯性
        if abs(state.velocity) > 0.1:
            state.scroll += state.velocity * dt
            state.velocity *= friction

        #边界回弹
        if not state.dragging:
            if state.scroll < 0:
                state.scroll *= 0.8
                state.velocity = 0
            elif state.scroll > max_scroll:
                state.scroll = max_scroll + (state.scroll - max_scroll) * 0.8
                state.velocity = 0

        def consume_scroll_event(e: ScrollEvent) -> bool:
            in_rect = e.in_rect(ctx, check_scissor_rect)
            if not in_rect:
                return False

            d = e.scroll_x if horizontal else e.scroll_y
            d *= mouse_wheel_speed
            state.scroll += d
            state.velocity = d / dt

            return d != 0

        ctx.context.event_manager.consume_events(ScrollEvent, consume_scroll_event)

        #拖拽
        def consume_finger(e: NewFingerEvent) -> Literal[False]:
            in_rect = e.finger.in_rect(ctx, check_scissor_rect)
            if not in_rect:
                return False

            def on_drag(f: Finger):
                f_pos = f.x if horizontal else f.y
                d = f_pos - state.last_drag
                state.scroll = state.drag_start_scroll - (f_pos - state.drag_start)
                state.velocity = -d / dt
                state.last_drag = f_pos

            def on_release(_):
                state.dragging = False

            e.finger.on_drag(on_drag)
            e.finger.on_release(on_release)

            state.dragging = True
            state.drag_start = e.finger.x if horizontal else e.finger.y
            state.last_drag = state.drag_start
            state.drag_start_scroll = state.scroll

            return False # 不消耗事件

        ctx.context.event_manager.consume_events(NewFingerEvent, consume_finger)

        if horizontal:
            content_rect = Rect(
                ctx.rect.x - state.scroll,
                ctx.rect.y,
                total_content_size,
                ctx.rect.h,
            )
        else:
            content_rect = Rect(
                ctx.rect.x,
                ctx.rect.y - state.scroll,
                ctx.rect.w,
                total_content_size,
            )

        if out_scope is not None:
            out_scope.viewport_offset = state.scroll
            out_scope.viewport_length = ctx.rect.w if horizontal else ctx.rect.h

        child_ctx = PlaceContext(content_rect, ctx.context, ctx.deferred_render_tick_listeners)

        if scissor:
            ctx.context.renderer.push_scissor(ctx.rect, for_render=False) # 用于拦截事件
            ctx.deferred_render_tick(lambda: ctx.context.renderer.pop_scissor(), RenderOperateType.scissor_op) # defer 从下到上执行

        element_ui.place_fn(child_ctx)

        if scissor:
            ctx.context.renderer.pop_scissor() # 用于拦截事件
            ctx.deferred_render_tick(lambda: ctx.context.renderer.push_scissor(ctx.rect), RenderOperateType.scissor_op) # defer 从下到上执行

        ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, Color(30, 30, 30)))

    return Placeable(40, element_ui.min_height, place_fn) if horizontal else Placeable(element_ui.min_width, 40, place_fn)



class EventManager:
    def __init__(self) -> None:
        self.event_by_type: dict[Any, list[Any]] = {}
        self.new_events: list[tuple[Any, Any]] = []

    def before_render(self) -> None:
        self.event_by_type.clear()

        for type, e in self.new_events:
            if type not in self.event_by_type:
                self.event_by_type[type] = []

            self.event_by_type[type].append(e)

        self.new_events.clear()

    def send_event(self, type: type[T], e: T) -> None:
        self.new_events.append((type, e))

    def send_event_instantly(self, type: type[T], e: T) -> None:
        events = self.event_by_type.get(type)
        if events is None:
            events = []
            self.event_by_type[type] = events

        events.append(e)

    def consume_events(self, type: type[T], consume: Callable[[T], bool]) -> None:
        events = self.event_by_type.get(type)
        if events is None:
            return
        self.event_by_type[type] = [e for e in events if not consume(e)]

class TypeValueMap:
    def __init__(self) -> None:
        self.instance_by_type: dict[type, Any] = {}

    def get(self, cls_as_key: type[T]) -> T | None:
        return self.instance_by_type.get(cls_as_key)

    def set(self, cls_as_key: type[T], value: T) -> None:
        self.instance_by_type[cls_as_key] = value

    def remember(self, cls_as_key: type[T], calc: Callable[[], T]) -> T:
        instance = self.instance_by_type.get(cls_as_key)
        if instance is not None:
            return instance

        instance = calc()
        self.instance_by_type[cls_as_key] = instance
        return instance

class ILoveUIContext:
    def __init__(self, renderer: Renderer) -> None:
        self.renderer = renderer
        self.event_manager = EventManager()
        self.fingers: list[Finger] = []
        self.type_value_map: TypeValueMap = TypeValueMap()

    def get(self, cls_as_key: type[T]) -> T | None:
        return self.type_value_map.get(cls_as_key)

    def set(self, cls_as_key: type[T], value: T) -> None:
        self.type_value_map.set(cls_as_key, value)

    def remember(self, cls_as_key: type[T], calc: Callable[[], T]) -> T:
        return self.type_value_map.remember(cls_as_key, calc)

    def place_in(self, rect: Rect, place_fn: Callable[[PlaceContext], None]) -> None:
        render_tick_listeners: list[RenderOperate] = []

        place_ctx = PlaceContext(rect, self, render_tick_listeners)
        place_fn(place_ctx)

        for operate in reversed(render_tick_listeners):
            operate.operate_fn()

    def to_placeable(
        self,
        content: Callable[['ILoveUI'], None],
        layout: Callable[['ILoveUI', Callable[['ILoveUI'], None]], Modifying] | None = None
    ) -> Placeable:
        if layout is None:
            layout = box

        u = ILoveUI(self)
        return layout(u, content).placeable

    def render_in(
        self,
        rect: Rect,
        content: Callable[['ILoveUI'], None],
        layout: Callable[['ILoveUI', Callable[['ILoveUI'], None]], Modifying] | None = None
    ) -> None:
        placeable = self.to_placeable(content, layout=layout)
        self.place_in(rect, placeable.place_fn)

class ILoveUI:
    '''
    立即模式 ui 库
    在主循环中调用 ILoveUIContext.render_in 来绘制 ui

    ui: 内部直接调用 ILoveUI.element 一次, 返回 Modifying 的函数
    ui_content: 内部直接调用 ILoveUI.element 任意次, 不返回 Modifying 的函数
    modifier: 修改 Modifying 的函数

    '''
    def __init__(self, context: ILoveUIContext) -> None:
        self.context = context
        self.children: list[Modifying] = []

    def element_placeable(self, placeable: Placeable) -> Modifying:
        modifying = Modifying(placeable)
        self.children.append(modifying)
        return modifying

    def element(self, place_fn: Callable[[PlaceContext], None], min_width: float = 10, min_height: float = 10) -> Modifying:
        placeable = Placeable(min_width=min_width, min_height=min_height, place_fn=place_fn)
        return self.element_placeable(placeable)

# ==================== popup system ====================

@dataclass(slots=True)
class PopupContext:
    close: Callable[[], None]
    set_to_top: Callable[[], None]

@dataclass(slots=True)
class Popup:
    popup_content: Callable[[ILoveUI, PopupContext], Any]
    removed: bool = False
    to_top: bool = False

    def remove(self):
        self.removed = True

    def set_to_top(self):
        self.to_top = True

@dataclass(slots=True)
class PopupManager:
    popups: list[Popup] = field(default_factory=lambda: [])

    def add(self, popup_content: Callable[[ILoveUI, PopupContext], Any]) -> None:
        self.popups.append(Popup(popup_content))

def popup_layer(u: ILoveUI) -> None:
    '''
    在 ui 最上层的第一行调用
    '''
    popupManager = u.context.remember(PopupManager, PopupManager)

    def box_content(u: ILoveUI):
        to_top_popups: list[Popup] = []

        for i in range(len(popupManager.popups) - 1, -1, -1):
            popup_instance = popupManager.popups[i]

            ctx = PopupContext(popup_instance.remove, popup_instance.set_to_top)
            popup_instance.popup_content(u, ctx)

            if popup_instance.removed:
                del popupManager.popups[i]

            elif popup_instance.to_top:
                popup_instance.to_top = False
                del popupManager.popups[i]
                to_top_popups.append(popup_instance)

        popupManager.popups += to_top_popups

    box(u, box_content)


def popup_content(u: ILoveUI) -> Callable[[Callable[[ILoveUI, PopupContext], None]], None]:
    '''
    ```
    @popup_content(u)
    def my_ui(u: ILoveUI):
        ...
    ```
    相当于
    def my_ui(u: ILoveUI):
        ...
    popup(u, my_ui)

    '''
    def decorator(content: Callable[[ILoveUI, PopupContext], None]) -> None:
        return popup(u, content)
    return decorator

def popup(u: ILoveUI, popup_content: Callable[[ILoveUI, PopupContext], Any]) -> None:
    popupManager = u.context.get(PopupManager)
    if popupManager is None:
        raise ValueError("must call 'popup_layer' before call 'popup', 在使用 'popup' 前，需要先在 UI 最上层的第一行调用 'popup_layer' 函数")
    popupManager.add(popup_content)

# ==================== popups ====================

TOAST_DURATION_SECONDS = 2

def toast(u: ILoveUI, toast_str: str, duration_seconds: float = TOAST_DURATION_SECONDS) -> None:
    create_time = time.time()
    offset = 0
    state = UIPath.root()

    @popup_content(u)
    def toast_popup(u: ILoveUI, ctx: PopupContext) -> None:
        nonlocal offset

        current_time = time.time()
        if current_time - create_time > duration_seconds:
            ctx.close()

        t = text(u, toast_str, state / 'toast_str')
        min_w, min_h = t.placeable.min_width, t.placeable.min_height
        t.expend_xy(20, 20) \
            .background(Color(0, 0, 0, 127), touch_through=True) \
            .animated_rect(state / 'animated_rect', lambda r: r.sub_rect_with_align(min_w, min_h, 0.5, 0.5)) \
            .offset_xy(0, offset) \
            .align_xy(0.5, 0.85)

        offset -= 0.8

def dialog(
    u: ILoveUI,
    text_str: str,
    yes_or_no: Callable[[bool], None],
    cancel: Callable[[], bool]
) -> None:
    popup_state = UIPath.root()

    @popup_content(u)
    def dialog_popup(u: ILoveUI, ctx: PopupContext):
        def cancel_dialog(_):
            if cancel():
                ctx.close()

        def chosen(value: bool):
            yes_or_no(value)
            ctx.close()

        @column_content(u)
        def top_column(u: ILoveUI):
            text(u, text_str, popup_state / 'text_str') \
                .expend_xy(20, 20) \
                .flex()

            @row_content(u)
            def yes_or_no_row(u: ILoveUI):
                text(u, 'no') \
                    .flex() \
                    .expend_xy(20, 20) \
                    .clickable(highlight, lambda _: chosen(False))

                text(u, 'yes') \
                    .flex() \
                    .expend_xy(20, 20) \
                    .clickable(highlight, lambda _: chosen(True))

        top_column \
            .background(Color(80, 80, 80)) \
            .animated_rect(popup_state / 'animated_rect') \
            .align_xy(0.5, 0.5) \
            .clickable_background(Color(0, 0, 0, 80), cancel_dialog)

def window_content(
    u: ILoveUI,
    initial_x: float = 100,
    initial_y: float = 200,
    layout: Callable[[ILoveUI, Callable[[ILoveUI], None]], Modifying] | None = None,
    with_close_button: bool = True,
    single_window_key: UIPath | None = None,
) -> Callable[[Callable[[ILoveUI, PopupContext], None]], None]:
    def decorator(content: Callable[[ILoveUI, PopupContext], None]) -> None:
        window(u, content, initial_x, initial_y, layout, with_close_button, single_window_key)
    return decorator

WINDOW_FRAME_SIZE = 14

@dataclass(slots=True)
class SingleWindowModeSupport:
    close_last_window: Callable[[], None] | None = None

    def before_create_window(self) -> None:
        if self.close_last_window is not None:
            self.close_last_window()
            self.close_last_window = None

    def window_running(self, popup_ctx: PopupContext) -> None:
        if self.close_last_window is None:
            self.close_last_window = popup_ctx.close

def window(
    u: ILoveUI,
    content: Callable[[ILoveUI, PopupContext], None],
    initial_x: float = 100,
    initial_y: float = 200,
    layout: Callable[[ILoveUI, Callable[[ILoveUI], None]], Modifying] | None = None,
    with_close_button: bool = True,
    single_window_key: UIPath | None = None,
) -> None:
    if layout is None:
        layout = box

    if single_window_key is None:
        single_window_mode = None
    else:
        single_window_mode = (single_window_key / 'close_last_window').remember(SingleWindowModeSupport)
        single_window_mode.before_create_window()

    rect_x = initial_x
    rect_y = initial_y
    state = UIPath.root()

    def draggable_modifier(p: Placeable) -> Placeable:
        def place_fn(ctx: PlaceContext):
            p.place_fn(ctx)

            def consume_new_finger_events(e: NewFingerEvent) -> bool:
                in_rect = e.finger.in_rect(ctx, True)

                offset_x = e.finger.x - ctx.rect.x
                offset_y = e.finger.y - ctx.rect.y

                if in_rect:
                    def finger_drag_listener(finger: Finger):
                        nonlocal rect_x, rect_y
                        rect_x = finger.x - offset_x
                        rect_y = finger.y - offset_y

                    e.finger.on_drag(finger_drag_listener)

                return in_rect

            ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_events)

            frame_rect = ctx.rect
            content_rect = frame_rect.with_padding(WINDOW_FRAME_SIZE, WINDOW_FRAME_SIZE)

            def consume_hovering_event(e: HoveringEvent) -> bool:
                finger = e.finger
                in_frame = frame_rect.contains_point(finger.x, finger.y) and not content_rect.contains_point(finger.x, finger.y)
                if in_frame:
                    ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, highlight))
                return in_frame

            ctx.context.event_manager.consume_events(HoveringEvent, consume_hovering_event)

        return Placeable(p.min_width, p.min_height, place_fn)

    if with_close_button:
        old_content = content
        def wrapped_content(u: ILoveUI, ctx: PopupContext) -> None:
            window_close_button(u, ctx.close)
            old_content(u, ctx)
        content = wrapped_content

    frame_color = Color(80, 80, 80)
    bg_color = Color(40, 40, 40)

    @popup_content(u)
    def window_popup(u: ILoveUI, ctx: PopupContext) -> None:
        if single_window_mode is not None:
            single_window_mode.window_running(ctx)

        content_ui = layout(u, lambda u: content(u, ctx))

        content_ui \
            .background(bg_color, touch_through=True) \
            .padding_xy(WINDOW_FRAME_SIZE, WINDOW_FRAME_SIZE) \
            .modifier(draggable_modifier) \
            .background(frame_color, touch_through=True) \
            .on_touchdown(lambda _: ctx.set_to_top()) \
            .animated_rect(state)

        min_w, min_h = content_ui.placeable.min_width, content_ui.placeable.min_height
        content_ui.with_rect(Rect(rect_x, rect_y, min_w, min_h))

# ==================== layouts ====================

def lazy_list_column_content(
    u: ILoveUI, id: UIPath,
    lst: Sequence[T],
    list_spacing: float = 4
) -> Callable[[Callable[[ILoveUI, T], Modifying]], Modifying]:
    def decorator(lst_element_ui: Callable[[ILoveUI, T], Modifying]) -> Modifying:
        return lazy_list_column(u, id, lst, lst_element_ui=lst_element_ui, list_spacing=list_spacing)
    return decorator

def lazy_list_row_content(
    u: ILoveUI, id: UIPath,
    lst: Sequence[T],
    list_spacing: float = 4
) -> Callable[[Callable[[ILoveUI, T], Modifying]], Modifying]:
    def decorator(lst_element_ui: Callable[[ILoveUI, T], Modifying]) -> Modifying:
        return lazy_list_row(u, id, lst, lst_element_ui=lst_element_ui, list_spacing=list_spacing)
    return decorator

def lazy_list_column(
    u: ILoveUI, id: UIPath,
    lst: Sequence[T],
    lst_element_ui: Callable[[ILoveUI, T], Modifying],
    list_spacing: float = 4
) -> Modifying:
    return lazy_list_linear(u, id, lst, horizontal=False, lst_element_ui=lst_element_ui, list_spacing=list_spacing)

def lazy_list_row(
    u: ILoveUI, id: UIPath,
    lst: Sequence[T],
    lst_element_ui: Callable[[ILoveUI, T], Modifying],
    list_spacing: float = 4
) -> Modifying:
    return lazy_list_linear(u, id, lst, horizontal=True, lst_element_ui=lst_element_ui, list_spacing=list_spacing)

LAZY_LIST_TRY_RENDER_COUNT = 4
LAZY_LIST_TAIL_SPACING = 1024

@dataclass(slots=True)
class LazyListState:
    first: bool = True
    start_index: int = 0
    start_offset: float = 0
    scroll_scope: ScrollScope = field(default_factory=ScrollScope)
    scroll_state: ScrollState = field(default_factory=ScrollState)

def lazy_list_linear(
    u: ILoveUI, id: UIPath,
    lst: Sequence[T],
    horizontal: bool,
    lst_element_ui: Callable[[ILoveUI, T], Modifying],
    list_spacing: float = 4
) -> Modifying:
    state = (id / 'lazy_list_state').remember(LazyListState)

    if state.first:
        state.first = False
        def linear_content(u: ILoveUI):
            for i in range(min(LAZY_LIST_TRY_RENDER_COUNT, len(lst))):
                lst_element_ui(u, lst[i])

    else:
        def linear_content(u: ILoveUI):
            idx = clamp(0, state.start_index, len(lst))
            space = state.scroll_scope.viewport_length

            pad_head_spacing = spacing(u, state.start_offset, 0) if horizontal else spacing(u, 0, state.start_offset)

            if idx >= 1 and state.scroll_scope.viewport_offset - state.start_offset < 0: # 列表上有空间时移动元素窗口
                ui = lst_element_ui(u, lst[idx - 1])
                ui_size = ui.placeable.min_width if horizontal else ui.placeable.min_height

                state.start_offset -= ui_size + list_spacing
                state.start_index -= 1

                p = pad_head_spacing.placeable
                if horizontal:
                    pad_head_spacing.placeable = Placeable(p.min_width - ui_size - list_spacing, p.min_height, p.place_fn)
                else:
                    pad_head_spacing.placeable = Placeable(p.min_width, p.min_height - ui_size - list_spacing, p.place_fn)

            while True:
                if idx >= len(lst):
                    break

                if space <= 0:
                    break

                ui = lst_element_ui(u, lst[idx])
                ui_size = ui.placeable.min_width if horizontal else ui.placeable.min_height

                if idx < len(lst) - 1 and state.scroll_scope.viewport_offset - state.start_offset > ui_size + list_spacing: # 元素被上滑出列表时移动元素窗口
                    state.start_offset += ui_size + list_spacing
                    state.start_index += 1

                space -= ui_size + list_spacing
                idx += 1

            if idx < len(lst):
                spacing(u, LAZY_LIST_TAIL_SPACING, 0) if horizontal else spacing(u, 0, LAZY_LIST_TAIL_SPACING)

    ui = linear(u, horizontal=horizontal, content=linear_content, spacing=list_spacing)

    ui.placeable = scroll_modifier(state.scroll_state, ui.placeable, horizontal=horizontal, out_scope=state.scroll_scope)

    return ui



def memo_content(
    u: ILoveUI,
    id: UIPath,
    valid_key: Any = None,
    layout: Callable[[ILoveUI, Callable[[ILoveUI], None]], Modifying] | None = None
) -> Callable[[Callable[[ILoveUI], None]], Modifying]:
    def decorator(content: Callable[[ILoveUI], None]) -> Modifying:
        return memo(u, id, content, valid_key, layout)
    return decorator

@dataclass(slots=True)
class Memo:
    memo_placeable: Placeable
    valid_key: Any
    new_memo: bool = True
    memo_rect: Rect | None = None

def memo(
    u: ILoveUI,
    id: UIPath,
    content: Callable[[ILoveUI], None],
    valid_key: Any,
    layout: Callable[[ILoveUI, Callable[[ILoveUI], None]], Modifying] | None = None
) -> Modifying:
    if layout is None:
        layout = box

    def layout_component() -> Placeable:
        return u.context.to_placeable(content, layout=layout)

    state = (id / 'memo').remember(lambda: Memo(layout_component(), valid_key))

    if not state.new_memo and state.valid_key != valid_key:
        state.memo_placeable = layout_component()
        state.new_memo = True
        state.valid_key = valid_key

    def place_fn(ctx: PlaceContext):
        if not state.new_memo and state.memo_rect != ctx.rect:
            state.memo_placeable = layout_component() # 在矩形变化时重新布局

        state.memo_rect = ctx.rect
        state.new_memo = False
        state.memo_placeable.place_fn(ctx)

    return u.element(place_fn, state.memo_placeable.min_width, state.memo_placeable.min_height)



def box_content(u: ILoveUI) -> Callable[[Callable[[ILoveUI], None]], Modifying]:
    '''
    ```
    @box_content(u)
    def my_ui(u: ILoveUI):
        ...
    ```
    相当于
    ```
    def my_ui(u: ILoveUI):
        ...
    box(u, my_ui)
    ```
    '''
    def decorator(content: Callable[[ILoveUI], None]) -> Modifying:
        return box(u, content)
    return decorator

def box(u: ILoveUI, content: Callable[[ILoveUI], None]) -> Modifying:
    '''
    默认拉伸所有子元素
    可以通过指定子元素的 align 或 offset 的方式来避免
    '''
    child_u = ILoveUI(u.context)
    content(child_u)

    min_width = 0
    min_height = 0

    for ui in child_u.children:
        min_width = max(min_width, ui.placeable.min_width)
        min_height = max(min_height, ui.placeable.min_height)

    def place_fn(ctx: PlaceContext):
        for ui in child_u.children:
            ui.placeable.place_fn(ctx)

    return u.element(place_fn, min_width, min_height)

def row_content(u: ILoveUI, spacing: float = 4) -> Callable[[Callable[[ILoveUI], None]], Modifying]:
    '''
    ```
    @row_content(u)
    def my_ui(u: ILoveUI):
        ...
    ```
    相当于
    ```
    def my_ui(u: ILoveUI):
        ...
    row(u, my_ui)
    ```
    '''
    def decorator(content: Callable[[ILoveUI], None]) -> Modifying:
        return row(u, content, spacing=spacing)
    return decorator

def row(u: ILoveUI, content: Callable[[ILoveUI], None], spacing: float = 4) -> Modifying:
    '''
    默认在交叉轴拉伸所有子元素
    可以通过指定子元素在交叉轴的 align 或 offset 的方式来避免
    '''
    return linear(u, horizontal=True, spacing=spacing, content=content)

def column_content(u: ILoveUI, spacing: float = 4) -> Callable[[Callable[[ILoveUI], None]], Modifying]:
    '''
    ```
    @column_content(u)
    def my_ui(u: ILoveUI):
        ...
    ```
    相当于
    ```
    def my_ui(u: ILoveUI):
        ...
    column(u, my_ui)
    ```
    '''
    def decorator(content: Callable[[ILoveUI], None]) -> Modifying:
        return column(u, content, spacing=spacing)
    return decorator

def column(u: ILoveUI, content: Callable[[ILoveUI], None], spacing: float = 4) -> Modifying:
    '''
    默认在交叉轴拉伸所有子元素
    可以通过指定子元素在交叉轴的 align 或 offset 的方式来避免
    '''
    return linear(u, horizontal=False, spacing=spacing, content=content)

def linear(u: ILoveUI, horizontal: bool, spacing: float, content: Callable[[ILoveUI], None]) -> Modifying:
    child_u = ILoveUI(u.context)
    content(child_u)

    min_width = 0
    min_height = 0
    fixed_size = 0
    total_weight = 0

    for ui in child_u.children:
        total_weight += ui.flex_weight

        if ui.flex_weight == 0:
            fixed_size += ui.placeable.min_width if horizontal else ui.placeable.min_height

        if horizontal:
            min_width += ui.placeable.min_width
            min_height = max(min_height, ui.placeable.min_height)
        else:
            min_width = max(min_width, ui.placeable.min_width)
            min_height += ui.placeable.min_height

    total_spacing = max(0, len(child_u.children) - 1) * spacing
    if horizontal:
        min_width += total_spacing
    else:
        min_height += total_spacing

    def place_fn(ctx: PlaceContext):
        nonlocal fixed_size, total_weight

        total_flex_size = ctx.rect.w if horizontal else ctx.rect.h
        total_flex_size -= total_spacing + fixed_size

        weight_to_flex_size_factor = total_flex_size / total_weight if total_weight != 0 else 0

        # 如果比例分配的大小不够, 转为固定大小
        for ui in child_u.children:
            if ui.flex_weight != 0:
                flex_size = ui.flex_weight * weight_to_flex_size_factor
                required_size = ui.placeable.min_width if horizontal else ui.placeable.min_height
                if flex_size < required_size:
                    total_flex_size -= required_size
                    total_weight -= ui.flex_weight
                    weight_to_flex_size_factor = total_flex_size / total_weight if total_weight != 0 else 0
                    ui.flex_weight = 0

        base = ctx.rect.x if horizontal else ctx.rect.y
        for ui in child_u.children:

            if ui.flex_weight == 0:
                child_size = ui.placeable.min_width if horizontal else ui.placeable.min_height
            else:
                child_size = ui.flex_weight * weight_to_flex_size_factor

            child_rect = Rect(base, ctx.rect.y, child_size, ctx.rect.h) if horizontal else Rect(ctx.rect.x, base, ctx.rect.w, child_size)
            child_ctx = PlaceContext(child_rect, ctx.context, ctx.deferred_render_tick_listeners)
            ui.placeable.place_fn(child_ctx)
            base += child_size + spacing

    return u.element(place_fn, min_width=min_width, min_height=min_height)

# ==================== widgets ====================

def spacing_copy_size(u: ILoveUI, copy_size_from: Modifying) -> Modifying:
    return spacing(u, copy_size_from.placeable.min_width, copy_size_from.placeable.min_height)

def spacing(u: ILoveUI, width: float = 10, height: float = 10) -> Modifying:
    return u.element(lambda _: None, width, height)

def text(u: ILoveUI, s: str, id: UIPath | None = None, color: Color = white) -> Modifying:
    if id is None:
        text_renderer = u.context.renderer.draw_text(s, color)
    else:
        text_renderer = id.remember(lambda: u.context.renderer.draw_text(s, color), valid_key=s)

    def place_fn(ctx: PlaceContext):
        ctx.deferred_render_tick(lambda: text_renderer.render(ctx.rect))

    return u.element(
        place_fn=place_fn,
        min_width=text_renderer.min_width,
        min_height=text_renderer.min_height
    )

@dataclass(slots=True)
class FocusManager:
    focused_ui_path: UIPath | None = None

@dataclass(slots=True)
class TextFieldState:
    last_blink: float = 0
    blink_state: bool = True
    last_cursor_visual_x: float = 0
    last_cursor_visual_y: float = 0
    min_width: float = 60
    min_height: float = 30

    cursor_pos: int = 0

    def show_cursor(self) -> None:
        self.last_blink = time.time()
        self.blink_state = True

def get_cursor_prefix(lines: list[str], row: int, col: int) -> str:
    if not (0 <= row < len(lines)):
        return ''
    row_str = lines[row]
    return row_str[:col]

def text_field(u: ILoveUI, id: UIPath, text_ref: Ref[str], placeholder: str = "type something...") -> Modifying:
    focus_manager = u.context.remember(FocusManager, FocusManager)

    def add_invisible_unfocus_click_layer():
        @popup_content(u)
        def popup_layer(u: ILoveUI, ctx: PopupContext):
            def unfocus(_):
                ctx.close()
                if focus_manager.focused_ui_path == id:
                    focus_manager.focused_ui_path = None

            if focus_manager.focused_ui_path != id:
                ctx.close()

            ctx.set_to_top()
            spacing(u).on_touchdown(unfocus)

    state = id.remember(TextFieldState)

    def place_fn(ctx: PlaceContext):
        active = (focus_manager.focused_ui_path == id)

        def consume_new_finger_event(e: NewFingerEvent) -> bool:
            in_rect = e.finger.in_rect(ctx, True)
            if in_rect and focus_manager.focused_ui_path != id:
                focus_manager.focused_ui_path = id
                state.cursor_pos = len(text_ref.value)
                add_invisible_unfocus_click_layer()
                state.show_cursor()

            return in_rect
        ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

        if active:
            def consume_text_input_event(e: TextInputEvent) -> bool:
                text = text_ref.value
                # 在光标位置插入字符，而不是追加
                text_ref.value = text[:state.cursor_pos] + e.text + text[state.cursor_pos:]
                state.cursor_pos += len(e.text)  # 输入后光标右移
                state.show_cursor()
                return True
            ctx.context.event_manager.consume_events(TextInputEvent, consume_text_input_event)

            def consume_key_event(e: KeyEvent) -> bool:
                if e.isDown:
                    text = text_ref.value
                    # 左箭头：光标左移
                    if e.keycode == pygame.K_LEFT:
                        state.cursor_pos = max(0, state.cursor_pos - 1)
                        state.show_cursor()
                        return True
                    # 右箭头：光标右移
                    elif e.keycode == pygame.K_RIGHT:
                        state.cursor_pos = min(len(text), state.cursor_pos + 1)
                        state.show_cursor()
                        return True
                    # HOME 键：跳到开头
                    elif e.keycode == pygame.K_HOME:
                        state.cursor_pos = 0
                        state.show_cursor()
                        return True
                    # END 键：跳到末尾
                    elif e.keycode == pygame.K_END:
                        state.cursor_pos = len(text)
                        state.show_cursor()
                        return True
                    elif e.keycode == pygame.K_RETURN:
                        text_ref.value = text[:state.cursor_pos] + '\n' + text[state.cursor_pos:]
                        state.cursor_pos += len('\n')  # 输入后光标右移
                        state.show_cursor()
                        return True
                    # ====================== 精准删除功能 ↓↓↓ ======================
                    # 退格键：删除光标左侧字符
                    elif e.keycode == pygame.K_BACKSPACE:
                        if state.cursor_pos > 0:
                            text_ref.value = text[:state.cursor_pos-1] + text[state.cursor_pos:]
                            state.cursor_pos -= 1  # 光标同步左移
                        state.show_cursor()
                        return True
                    # 删除键：删除光标右侧字符
                    elif e.keycode == pygame.K_DELETE:
                        if state.cursor_pos < len(text):
                            text_ref.value = text[:state.cursor_pos] + text[state.cursor_pos+1:]
                        state.show_cursor()
                        return True
                return False
            ctx.context.event_manager.consume_events(KeyEvent, consume_key_event)

            now = time.time()
            if now - state.last_blink > 0.5:
                state.blink_state = not state.blink_state
                state.last_blink = now

        lines = (id / 'lines').remember(lambda: text_ref.value.splitlines(), text_ref.value)

        def render():
            ctx.context.renderer.fill_rect(ctx.rect, Color(60, 60, 60))
            ctx.context.renderer.fill_rect(ctx.rect, Color(200, 200, 200), line_width = 2 if active else 1)

            if not lines and not active:
                textRenderers = [ctx.context.renderer.draw_text(placeholder, color=Color(160, 160, 160))]
            else:
                textRenderers = list(map(lambda s: ctx.context.renderer.draw_text(s), lines))

            r = ctx.rect
            y_offset = 0
            min_w = 60
            for textRenderer in textRenderers:
                rect = Rect(r.x+8, y_offset + r.y, textRenderer.min_width, textRenderer.min_height)
                textRenderer.render(rect)
                y_offset += textRenderer.min_height
                min_w = max(min_w, textRenderer.min_width)

            state.min_width = min_w
            state.min_height = max(y_offset, 30)

            if active: # todo 优化
                def mix(a: float, b: float) -> float:
                    return (a * 3 + b) / 4

                row_number = 0
                col_number = 0
                for i in range(min(state.cursor_pos, len(text_ref.value))):
                    match text_ref.value[i]:
                        case '\n':
                            row_number += 1
                            col_number = 0
                        case _:
                            col_number += 1

                cursor_prefix = text_ref.value[state.cursor_pos - col_number:state.cursor_pos]
                rendered_cursor_prefix = u.context.renderer.draw_text(cursor_prefix)
                cx = r.x + 8 + rendered_cursor_prefix.min_width
                cy = r.y + sum(map(lambda n: textRenderers[n].min_height, range(row_number)))

                cx = mix(state.last_cursor_visual_x, cx)
                cy = mix(state.last_cursor_visual_y, cy)

                state.last_cursor_visual_x = cx
                state.last_cursor_visual_y = cy

                if state.blink_state:
                    cy1 = cy
                    cy2 = cy + rendered_cursor_prefix.min_height
                    ctx.context.renderer.draw_line(Color(255,255,255), (cx, cy1), (cx, cy2), 2)

        ctx.deferred_render_tick(render)

    return u.element(place_fn, state.min_width, state.min_height)

def slider(u: ILoveUI, value_ref: Ref[float], min_val: float, max_val: float, check_scissor_rect: bool = True) -> Modifying:
    def place_fn(ctx: PlaceContext):
        def consume_new_finger_event(e: NewFingerEvent) -> bool:
            in_rect = e.finger.in_rect(ctx, check_scissor_rect)

            def handle_finger(finger):
                t = max(0.0, min(1.0, (finger.x - ctx.rect.x) / ctx.rect.w))
                value_ref.value = min_val + t * (max_val - min_val)

            if in_rect:
                handle_finger(e.finger)
                e.finger.on_drag(handle_finger)

            return in_rect
        ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

        def render():
            r = ctx.rect
            yh = r.h / 3

            ctx.context.renderer.fill_rect(Rect(r.x, r.y + yh, r.w, yh), Color(80, 80, 80))
            t = (value_ref.value - min_val) / (max_val - min_val) if max_val != min_val else 0
            fill_w = r.w * t
            ctx.context.renderer.fill_rect(Rect(r.x, r.y + yh, fill_w, yh), Color(100,200,100))

            cr = r.h * 0.4
            cx = r.x + fill_w
            cy = r.y + r.h/2
            ctx.context.renderer.fill_circle(cx, cy, cr, Color(255,255,255))

        ctx.deferred_render_tick(render)

    return u.element(place_fn, 30, 30)

def number_input(u: ILoveUI, name_tag: str, value_ref: Ref[float], value_text_min_width: float = 0, level: int = 2, step: int = 10) -> Modifying:
    @row_content(u)
    def top_row(u: ILoveUI):

        def number_modify_button(u: ILoveUI, show: str, delta_value: int) -> Modifying:
            def set_value(_) -> None:
                value_ref.set(value_ref.value + delta_value)
            return text(u, show) \
                .square_expend() \
                .clickable(highlight, set_value)

        if level >= 3:
            number_modify_button(u, '<<<', -step * step)

        if level >= 2:
            number_modify_button(u, '<<', -step)

        number_modify_button(u, '<', -1)

        text(u, str(value_ref.value)) \
            .min_size_xy(value_text_min_width, 0) \
            .tag_left(u, name_tag, with_spacing=False)

        number_modify_button(u, '>', 1)

        if level >= 2:
            number_modify_button(u, '>>', step)

        if level >= 3:
            number_modify_button(u, '>>>', step * step)

    return top_row

def number_pad(u: ILoveUI, number_typed: Callable[[int], None], id: UIPath | None = None) -> Modifying:
    def number_button(u: ILoveUI, number: int) -> Modifying:
        return text(u, str(number), id = id / number if id is not None else None) \
            .flex() \
            .clickable(highlight, lambda _: number_typed(number), background_color=Color(40, 40, 40))

    def number_row(u: ILoveUI, n1: int, n2: int, n3: int) -> Modifying:
        @row_content(u)
        def number_row_ui(u: ILoveUI):
            number_button(u, n1)
            number_button(u, n2)
            number_button(u, n3)

        return number_row_ui.flex()

    @column_content(u)
    def top_column(u: ILoveUI):
        number_row(u, 1, 2, 3)
        number_row(u, 4, 5, 6)
        number_row(u, 7, 8, 9)

        @row_content(u)
        def number0_row(u: ILoveUI):
            spacing(u).flex()
            number_button(u, 0)
            spacing(u).flex()

        number0_row.flex()

    return top_column

def default_touchpad_handle(u: ILoveUI) -> Modifying:
    return text(u, 'O') \
        .background(Color(180, 20, 20)) \

def touchpad(u: ILoveUI, touchpad_vec: Ref[tuple[float, float]], touchpad_handle: Callable[[ILoveUI], Modifying] | None = None, check_scissor_rect: bool = True) -> Modifying:

    if touchpad_handle is None:
        touchpad_handle = default_touchpad_handle

    def touchpad_modifier(p: Placeable) -> Placeable:
        def place_fn(ctx: PlaceContext):
            def consume_new_finger_events(e: NewFingerEvent) -> bool:
                in_rect = e.finger.in_rect(ctx, check_scissor_rect)

                def handle_finger(finger: Finger):
                    touchpad_vec.value = ((finger.x - ctx.rect.x) / ctx.rect.w, (finger.y - ctx.rect.y) / ctx.rect.h)

                def finger_release_listener(_):
                    touchpad_vec.value = (0.5, 0.5)

                if in_rect:
                    handle_finger(e.finger)
                    e.finger.on_drag(handle_finger)
                    e.finger.on_release(finger_release_listener)

                return in_rect

            ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_events)
            p.place_fn(ctx)
        return Placeable(p.min_width, p.min_height, place_fn)

    @box_content(u)
    def touchpad_box(u: ILoveUI):
        touchpad_handle(u) \
            .square_expend() \
            .align_xy(touchpad_vec.value[0], touchpad_vec.value[1])

    return touchpad_box \
        .expend_xy(20, 20) \
        .modifier(touchpad_modifier)



def checkbox(u: ILoveUI, checked: Ref[bool], id: UIPath | None = None) -> Modifying:
    def place_fn(ctx: PlaceContext):
        align_x = 1 if checked.value else 0

        if id is not None:
            last_align_x: list[float] = (id / 'checkbox state').remember(lambda: [align_x])
            align_x = (3 * last_align_x[0] + align_x) / 4
            last_align_x[0] = align_x

        def render():
            rect = ctx.rect
            slider_rect = ctx.rect.sub_rect_with_align(ctx.rect.h, ctx.rect.h, align_x, 0)
            ctx.context.renderer.fill_rect(rect, gray)
            ctx.context.renderer.fill_rect(Rect(rect.x, rect.y, slider_rect.x - rect.x, rect.h), green)
            ctx.context.renderer.fill_rect(slider_rect, white)

        ctx.deferred_render_tick(render)

    return u.element(place_fn) \
        .clickable(highlight, lambda _: checked.set(not checked.value))



def rect_control_ui(u: ILoveUI, rect_ref: Ref[Rect]) -> Modifying:
    @column_content(u)
    def control_column(u: ILoveUI):
        number_input(u, 'x: ', Ref(lambda: rect_ref.value.x, lambda value: rect_ref.set(dataclasses.replace(rect_ref.value, x=value))), value_text_min_width=80, level=3)
        number_input(u, 'y: ', Ref(lambda: rect_ref.value.y, lambda value: rect_ref.set(dataclasses.replace(rect_ref.value, y=value))), value_text_min_width=80, level=3)
        number_input(u, 'w: ', Ref(lambda: rect_ref.value.w, lambda value: rect_ref.set(dataclasses.replace(rect_ref.value, w=value))), value_text_min_width=80, level=3)
        number_input(u, 'h: ', Ref(lambda: rect_ref.value.h, lambda value: rect_ref.set(dataclasses.replace(rect_ref.value, h=value))), value_text_min_width=80, level=3)

    return control_column



def window_close_button(u: ILoveUI, close_window: Callable[[], None]) -> Modifying:
    return text(u, 'x') \
        .square_expend() \
        .clickable(highlight, lambda _: close_window(), background_color=Color(255, 80, 80)) \
        .align_xy(1, 0)



def manageable_list(
    u: ILoveUI,
    lst: list[T],
    element_ui: Callable[[ILoveUI, int, T], Modifying],
    insert_at: Callable[[int], None] | None = None,
    remove_at: Callable[[int], None] | None = None,
    swap_at: Callable[[int, int], None] | None = None,
) -> Modifying:

    def insert_and_swap_button(u: ILoveUI, idx: int) -> Modifying:
        @row_content(u)
        def buttons_row(u: ILoveUI):
            text(u, '+') \
                .clickable(highlight, lambda _: insert_at(idx)) # type: ignore

            if swap_at is not None and (0 < idx < len(lst)):
                text(u, '^v') \
                    .clickable(highlight, lambda _: swap_at(idx - 1, idx)) # type: ignore

        return buttons_row


    def enable_if_hover(p: Placeable) -> Placeable:
        def place_fn(ctx: PlaceContext):
            hover = False
            def consume_event(e: HoveringEvent) -> bool:
                nonlocal hover
                hover = e.finger.in_rect(ctx, True)
                return False

            ctx.context.event_manager.consume_events(HoveringEvent, consume_event)

            if hover:
                p.place_fn(ctx)

        return Placeable(p.min_width, p.min_height, place_fn)


    def in_list_element_ui(u: ILoveUI, idx: int, e: T) -> Modifying:
        if remove_at is None:
            return element_ui(u, idx, e)

        @row_content(u)
        def with_remove_button_row(u: ILoveUI):
            text(u, '-') \
                .min_size_xy(12, 0) \
                .clickable(highlight, lambda _: remove_at(idx)) \
                .modifier(enable_if_hover)

            element_ui(u, idx, e)

        return with_remove_button_row


    @column_content(u)
    def elements_col(u: ILoveUI):
        for i, e in enumerate(lst):
            if insert_at is not None:
                insert_and_swap_button(u, i) \
                    .modifier(enable_if_hover)

            in_list_element_ui(u, i, e)

        if insert_at is not None:
            ui = insert_and_swap_button(u, len(lst))

            if lst:
                ui.modifier(enable_if_hover)

    return elements_col



@dataclass(slots=True)
class RenderTimeText:
    time_seconds: float = 0
    max_time_seconds: float = 0

    def set_time_seconds(self, value: float) -> None:
        self.time_seconds = value
        self.max_time_seconds = max(self.max_time_seconds, value)

def render_time_text(u: ILoveUI, id: UIPath) -> Modifying:
    '''
    测量本组件和之后的所有组件从调用到 deferred_render_tick 的时间,
    放在 ui 最上层第一行来测量 ui 耗时
    '''
    time_start = time.time()
    state = id.remember(RenderTimeText)

    def measure_time_modifier(p: Placeable) -> Placeable:
        def place_fn(ctx: PlaceContext):
            ctx.deferred_render_tick(lambda: state.set_time_seconds(time.time() - time_start))
            p.place_fn(ctx)
        return Placeable(p.min_width, p.min_height, place_fn)

    return text(u, f'cur: {state.time_seconds:.4f}s, max: {state.max_time_seconds:.4f}s') \
        .modifier(measure_time_modifier) \
        .expend_xy(0, 10)



def bitmap_advanced_ui(
    u: ILoveUI, id: UIPath,
    bitmap: bytearray,
    total_bytes_count: int = -1,
    flip_byte_at: Callable[[int], None] | None = None,
    row_byte_count: int = 8
) -> Modifying:
    """
    高级位图控制组件：
    - 范围翻转 / 范围填充
    - 全选、全清、全翻转
    - 数字输入框控制索引
    """
    if total_bytes_count < 0:
        total_bytes_count = len(bitmap)

    def clamp_start(i: int) -> int:
        if i > end_ref.value:
            return end_ref.value
        return clamp(0, i, total_bytes_count)

    def clamp_end(i: int) -> int:
        if i < start_ref.value:
            return start_ref.value
        return clamp(0, i, total_bytes_count)

    # ======================
    # 控制面板：数值引用
    # ======================
    start_ref = (id / 'start_ref').remember(lambda: Ref.new_box(0).map_input(clamp_start))          # 范围起始
    end_ref = (id / 'end_ref').remember(lambda: Ref.new_box(total_bytes_count - 1).map_input(clamp_end))  # 范围结束

    # ======================
    # 基础操作：单个/整行翻转（复用原有逻辑）
    # ======================
    def flip_index(index: int) -> None:
        if 0 <= index < total_bytes_count:
            if flip_byte_at is None:
                bitmap[index] = 0 if bitmap[index] != 0 else 1
            else:
                flip_byte_at(index)

    # ======================
    # 高级操作：范围/批量
    # ======================
    def reset_range(_) -> None:
        start_ref.value = 0
        end_ref.value = total_bytes_count

    def flip_range(_) -> None:
        """翻转 [start, end] 范围内所有位"""
        s = int(start_ref.value)
        e = int(end_ref.value)
        s = max(0, s)
        e = min(total_bytes_count - 1, e)
        for i in range(s, e + 1):
            flip_index(i)

    def fill_range(val: int) -> None:
        """填充 [start, end] 为指定值（0/1）"""
        s = int(start_ref.value)
        e = int(end_ref.value)

        s = max(0, s)
        e = min(total_bytes_count - 1, e)
        for i in range(s, e + 1):
            if flip_byte_at is None:
                bitmap[i] = val
            else:
                # 如果有自定义翻转，用两次翻转模拟设置值
                if bitmap[i] != val:
                    flip_byte_at(i)

    def set_all(_, val: int) -> None:
        """全部设为 val"""
        for i in range(total_bytes_count):
            if flip_byte_at is None:
                bitmap[i] = val
            else:
                if bitmap[i] != val:
                    flip_byte_at(i)

    def flip_all(_) -> None:
        """全部翻转"""
        for i in range(total_bytes_count):
            flip_index(i)

    highlighted_green = Color(180, 255, 180)
    highlighted_gray = Color(100, 100, 100)

    def byte_ui_by_index(u: ILoveUI, index: int) -> Modifying:
        if start_ref.value <= index <= end_ref.value:
            color = highlighted_green if bitmap[index] != 0 else highlighted_gray
        else:
            color = green if bitmap[index] != 0 else gray

        return spacing(u) \
            .background(color)

    # ======================
    # 布局：组合所有内容
    # ======================
    @column_content(u)
    def root(u: ILoveUI):

        # 控制面板
        # ======================
        # 布局：控制面板行
        # ======================
        @row_content(u)
        def control_panel(u: ILoveUI):

            @column_content(u)
            def range_column(u: ILoveUI):
                number_input(u, "Start", start_ref, step=row_byte_count).flex() # type: ignore
                number_input(u, "End", end_ref, step=row_byte_count).flex() # type: ignore

            range_column.flex()

            @column_content(u)
            def range_buttons(u: ILoveUI):
                text(u, "flip range").clickable(highlight, flip_range).flex()
                text(u, "fill range 0").clickable(highlight, lambda _: fill_range(0)).flex()
                text(u, "fill range 1").clickable(highlight, lambda _: fill_range(1)).flex()

            range_buttons.flex()

            @column_content(u)
            def global_buttons(u: ILoveUI):
                text(u, "flip all").clickable(highlight, flip_all).flex()
                text(u, "all 1").clickable(highlight, lambda _: set_all(_, 1)).flex()
                text(u, "all 0").clickable(highlight, lambda _: set_all(_, 0)).flex()

            global_buttons.flex()

        # 分隔线
        spacing(u, 0, 8)

        # 原始位图UI（完全复用）
        bitmap_ui(
            u, id / "bitmap",
            bitmap, total_bytes_count,
            flip_byte_at, row_byte_count,
            byte_ui_by_index=byte_ui_by_index
        ).flex()

    return root

def bitmap_ui(
    u: ILoveUI, id: UIPath,
    bitmap: bytearray,
    total_bytes_count: int = -1,
    flip_byte_at: Callable[[int], None] | None = None,
    row_byte_count: int = 8,
    byte_ui_by_index: Callable[[ILoveUI, int], Modifying] | None = None
) -> Modifying:
    '''
    用 byte 表示 bool
    '''
    if total_bytes_count < 0:
        total_bytes_count = len(bitmap)
    else:
        total_bytes_count = min(total_bytes_count, len(bitmap))


    def flip_index(index: int) -> None:
        if flip_byte_at is None:
            bitmap[index] = 0 if bitmap[index] != 0 else 1
        else:
            flip_byte_at(index)

    if byte_ui_by_index is not None:
        def byte_ui(u: ILoveUI, index: int) -> Modifying:
            ui = byte_ui_by_index(u, index) \
                .flex() \
                .clickable(highlight, lambda _: flip_index(index))

            return ui
    else:
        def byte_ui(u: ILoveUI, index: int) -> Modifying:
            ui = spacing(u) \
                .flex() \
                .clickable(highlight, lambda _: flip_index(index), background_color=green if bitmap[index] != 0 else gray)

            return ui

    row_numbers = range((total_bytes_count + row_byte_count - 1) // row_byte_count)

    @lazy_list_column_content(u, id / 'lazy_list_column_content', row_numbers)
    def byte_rows_col(u: ILoveUI, row_number: int) -> Modifying:
        row_start_index = row_number * row_byte_count

        @row_content(u)
        def bytes_row(u: ILoveUI) -> None:
            text(u, str(row_start_index), id / row_start_index) \
                .min_size_xy(40, 0)

            for col_number in range(row_byte_count):
                index = row_start_index + col_number

                if index >= total_bytes_count:
                    spacing(u).flex() # 代替缺失的位参与布局, 保持最后一行布局正常
                    continue

                byte_ui(u, index)

            def flip_row(_, row_start_index = row_start_index) -> None:
                for col_number in range(row_byte_count):
                    index = row_start_index + col_number
                    if index < total_bytes_count:
                        flip_index(index)

            text(u, 'flip', id / 'flip' / row_start_index) \
                .min_size_xy(40, 40) \
                .clickable(highlight, flip_row)

        return bytes_row \
            .ratio_expend(row_byte_count, 1)

    return byte_rows_col

def single_component_rgba_color_selector(u: ILoveUI, component_ref: Ref[int]) -> Modifying:
    return slider(u, Ref(component_ref.get, lambda value: component_ref.set(int(value))), 0, 255)

def rgba_color_selector(u: ILoveUI, color_ref: Ref[Color]) -> Modifying:
    @row_content(u)
    def top_row(u: ILoveUI):

        @column_content(u)
        def rgba_sliders_col(u: ILoveUI):
            c = color_ref.value
            single_component_rgba_color_selector(u, Ref(lambda: color_ref.value.r, lambda value: color_ref.set(Color(value, c.g, c.b, c.a)))).flex()
            single_component_rgba_color_selector(u, Ref(lambda: color_ref.value.g, lambda value: color_ref.set(Color(c.r, value, c.b, c.a)))).flex()
            single_component_rgba_color_selector(u, Ref(lambda: color_ref.value.b, lambda value: color_ref.set(Color(c.r, c.g, value, c.a)))).flex()
            single_component_rgba_color_selector(u, Ref(lambda: color_ref.value.a, lambda value: color_ref.set(Color(c.r, c.g, c.b, value)))).flex()

        rgba_sliders_col.flex(4)

        spacing(u) \
            .background(color_ref.value) \
            .flex()

    return top_row \
        .min_size_xy(40, 0) \
        .ratio_expend(5, 1)



# ==================== preview ====================



preview_widgets: list[Callable[[ILoveUI], None]] | None = None



def preview(*args, **kwargs) -> Callable[[Callable], Callable]:
    '''
    需要最终调用 fast_preview 才能看见效果
    '''
    def decorator(f: Callable) -> Callable:
        global preview_widgets

        def widget(u: ILoveUI):
            f(u, *args, **kwargs)

        if preview_widgets is None:
            preview_widgets = []

        preview_widgets.append(widget)
        return f

    return decorator



def preview_layer(u: ILoveUI, id: UIPath):
    @column_content(u)
    def top(u: ILoveUI):
        for widget in preview_widgets or ():
            widget(u)

    top.v_scroll(id)



def fast_preview():
    id = UIPath.root()
    fast_debug(lambda u, _: preview_layer(u, id))



# ==================== renderer ====================



class PygameILoveUIRenderer(Renderer):
    def __init__(
        self,
        screen_surface: pygame.Surface,
    ) -> None:
        super().__init__()
        self.screen_surface = screen_surface
        self.buffer_surface = pygame.Surface(screen_surface.get_size(), pygame.SRCALPHA)

        self.scissor_stack: list[Rect] = []
        self.scissor_enabled = True

        self.font = pygame.font.SysFont(['Arial', 'SimHei'], 24)

    def _bilt_screen(self):
        self.screen_surface.blit(self.buffer_surface, (0, 0))
        self.buffer_surface.fill((0, 0, 0, 0))

    def _sync_buffer_size(self):
        bw, bh = self.buffer_surface.get_size()
        sw, sh = self.screen_surface.get_size()
        if bw < sw or bh < sh:
            self.buffer_surface = pygame.Surface((max(bw, sw), max(bh, sh)), pygame.SRCALPHA)

    def fill_rect(self, rect: Rect, color: Color, line_width: float = 0) -> None:
        color_tuple = color.to_tuple()

        if color.a != 255:
            self._sync_buffer_size()
            pygame.draw.rect(
                self.buffer_surface,
                color_tuple,
                rect.to_tuple(),
                width=int(line_width)
            )
            self._bilt_screen()
        else:
            pygame.draw.rect(
                self.screen_surface,
                color_tuple,
                rect.to_tuple(),
                width=int(line_width)
            )


    def draw_text(self, text_str: str, color: Color = white) -> Renderer.Renderable:
        surf = self.font.render(text_str, True, color.to_tuple())
        min_width = surf.get_width()
        min_height = surf.get_height()

        def render(rect: Rect):
            # 文本居中绘制
            blit_x = rect.x + (rect.w - surf.get_width()) / 2
            blit_y = rect.y + (rect.h - surf.get_height()) / 2
            self.screen_surface.blit(surf, (blit_x, blit_y))

        return Renderer.Renderable(min_width, min_height, render)


    def draw_line(self, color: Color, start_pos: tuple[float, float], end_pos: tuple[float, float], width: int = 1) -> None:
        pygame.draw.line(self.screen_surface, color.to_tuple(), start_pos, end_pos, width)

    def fill_circle(self, x: float, y: float, radius: float, color: Color) -> None:
        pygame.draw.circle(self.screen_surface, color.to_tuple(), (x, y), radius)

    def push_scissor(self, rect: Rect, for_render: bool = True) -> None:
        # 计算当前有效裁剪 = 上一层裁剪 ∩ 新矩形
        if self.scissor_stack:
            last_effective = self.scissor_stack[-1]
            effective_rect = last_effective.intersect(rect)
        else:
            effective_rect = rect

        # 入栈
        self.scissor_stack.append(effective_rect)
        # 应用最终裁剪
        if for_render and self.scissor_enabled:
            self.screen_surface.set_clip(effective_rect.to_tuple())

    def pop_scissor(self) -> None:
        if not self.scissor_stack:
            raise IndexError("pop_scissor() called without matching push_scissor()")

        # 弹出栈顶
        self.scissor_stack.pop()

        if self.scissor_enabled:
            # 恢复新的栈顶裁剪
            if self.scissor_stack:
                new_top_effective = self.scissor_stack[-1]
                self.screen_surface.set_clip(new_top_effective.to_tuple())
            else:
                self.screen_surface.set_clip(None)

    @property
    def scissor_rect(self) -> Rect | None:
        return self.scissor_stack[-1] if self.scissor_stack else None

    def get_scissor_count(self) -> int:
        return len(self.scissor_stack)

    def get_scissor_enabled(self) -> bool:
        return self.scissor_enabled

    def set_scissor_enabled(self, value: bool) -> None:
        self.scissor_enabled = value
        if value:
            if self.scissor_stack:
                new_top_effective = self.scissor_stack[-1]
                self.screen_surface.set_clip(new_top_effective.to_tuple())
        else:
            self.screen_surface.set_clip(None)



# ==================== fast debug ====================



class RenderLayerMode(Enum):
    all = auto()
    exactly = auto()
    before = auto()
    after = auto()
    mask = auto()

    def next_mode(self) -> 'RenderLayerMode':
        members = list(RenderLayerMode)
        current_index = members.index(self)
        next_index = (current_index + 1) % len(members)
        return members[next_index]

@dataclass(slots=True)
class RenderLayerManager:
    layer: int = 10
    render_mode: RenderLayerMode = RenderLayerMode.all
    render_mask: bytearray = field(default_factory=lambda: bytearray(b'\xFF' * 512))
    id: UIPath = field(default_factory=UIPath.root)

    def get_mask(self, required_count: int) -> bytearray:
        deficit = required_count - len(self.render_mask)
        if deficit > 0:
            self.render_mask += b'\xFF' * deficit

        return self.render_mask

    def render_mode_to_list_mapper(self) -> Callable[[list[RenderOperate]], list[RenderOperate]]:
        match self.render_mode:
            case RenderLayerMode.all:
                return lambda x: x

            case RenderLayerMode.exactly:
                def exactly_mapper(lst: list[RenderOperate]) -> list[RenderOperate]:
                    if self.layer not in range(len(lst)):
                        return []
                    op = lst[self.layer]
                    if op.type == RenderOperateType.scissor_op: # 要么不做 scissor_op, 要么保留所有 scissor_op
                        return []
                    return [op]
                return exactly_mapper

            case RenderLayerMode.before:
                def before_mapper(lst: list[RenderOperate]) -> list[RenderOperate]:
                    return [e for i, e in enumerate(lst) if i <= self.layer or e.type == RenderOperateType.scissor_op] # 要么不做 scissor_op, 要么保留所有 scissor_op
                return before_mapper

            case RenderLayerMode.after:
                def after_mapper(lst: list[RenderOperate]) -> list[RenderOperate]:
                    return [e for i, e in enumerate(lst) if i >= self.layer or e.type == RenderOperateType.scissor_op] # 要么不做 scissor_op, 要么保留所有 scissor_op
                return after_mapper

            case RenderLayerMode.mask:
                def mask_mapper(lst: list[RenderOperate]) -> list[RenderOperate]:
                    mask = self.get_mask(len(lst))
                    return [e for i, e in enumerate(lst) if mask[i] != 0 or e.type == RenderOperateType.scissor_op] # 要么不做 scissor_op, 要么保留所有 scissor_op
                return mask_mapper

            case _:
                raise ValueError('unreachable')

def render_layer_control_ui(u: ILoveUI, max_layer: int, state: RenderLayerManager) -> Modifying:
    layer = state.layer

    def set_layer(value: int) -> None:
        nonlocal layer
        layer = value
        state.layer = value

    @column_content(u)
    def top_col(u: ILoveUI):

        spacing(u, 20, 20)

        @row_content(u)
        def slider_row(u: ILoveUI):
            text(u, '<') \
                .square_expend() \
                .clickable(highlight, lambda _: set_layer(layer - 1))

            slider(u, Ref(lambda: layer, lambda value: set_layer(round(value))), 0, max_layer, check_scissor_rect=False) \
                .flex() \
                .tag_left_right(u, f'layer: {layer}  ', f'  {max_layer}', tag_min_size=40) \
                .min_size_xy(280, 0)

            text(u, '>') \
                .square_expend() \
                .clickable(highlight, lambda _: set_layer(layer + 1))

        @row_content(u)
        def buttons_row(u: ILoveUI):

            def toggle_mode(_) -> None:
                state.render_mode = state.render_mode.next_mode()

            text(u, state.render_mode.name) \
                .flex() \
                .clickable(highlight, toggle_mode, check_scissor_rect=False) \
                .tag_left(u, 'layer render mode') \
                .expend_xy(0, 10)

        bitmap_advanced_ui(u, state.id / 'bitmap_ui', state.render_mask, total_bytes_count=max_layer, row_byte_count=12) \
            .flex() \
            .background(gray)

    return top_col \
        .square_expend()

@dataclass(slots=True)
class UIRendererUIState:
    fast_start_ctx: 'FastStartContext'
    original_target_ui: Callable[[ILoveUI, 'FastStartContext'], None]
    target_ui: Callable[[ILoveUI, 'FastStartContext'], None]
    target_ui_u: ILoveUI
    single_step_mode: bool = False
    step: bool = False
    cached_render_tick_listeners: list[RenderOperate] | None = None
    sync_events: bool = True

    def toggle_mode(self) -> None:
        self.single_step_mode = not self.single_step_mode

    def toggle_step(self) -> None:
        self.step = not self.step

def ui_renderer_ui(
    u: ILoveUI,
    state: UIRendererUIState,
    map_render_tick_listeners: Callable[[list[RenderOperate]], list[RenderOperate]] | None = None,
    rect: Rect | None = None,
    before_step: Callable[[], None] | None = None
) -> Modifying:
    '''
    用于 ui 调试器
    '''

    def place_component(ctx: PlaceContext) -> list[RenderOperate]:
        '''
        收集绘制指令到 list
        '''
        if before_step is not None:
            before_step()

        p = state.target_ui_u.context.to_placeable(lambda u: state.target_ui(u, state.fast_start_ctx))
        render_tick_listeners: list[RenderOperate] = []

        context = state.target_ui_u.context
        if state.sync_events:
            state.target_ui_u.context.event_manager.before_render()
            for type, events in ctx.context.event_manager.event_by_type.items():
                for event in events:
                    context.event_manager.send_event_instantly(type, event)

        p.place_fn(PlaceContext(rect if rect is not None else ctx.rect, context, render_tick_listeners))
        return render_tick_listeners

    def place_fn(ctx: PlaceContext):
        if not state.single_step_mode or state.step:
            state.step = False
            try:
                lst = place_component(ctx)
            except Exception as e:
                dialog(u, f'{e}, {e.args}', lambda _: None, lambda: True)
                state.target_ui = state.original_target_ui
                lst = []
            state.cached_render_tick_listeners = lst

        lst = state.cached_render_tick_listeners

        if lst is None:
            toast(u, 'error', 1)
            return

        if map_render_tick_listeners is not None:
            lst = map_render_tick_listeners(lst)

        ctx.deferred_render_tick_listeners += lst

    return u.element(place_fn)



def debug_ui_rect_control_ui(u: ILoveUI, ui_rect_ref: Ref[Rect | None], show_rect_ref: Ref[bool]) -> Modifying:
    @row_content(u)
    def rect_control_row(u: ILoveUI):
        def get_rect() -> Rect:
            return ui_rect_ref.value if ui_rect_ref.value is not None else Rect(0, 0, 200, 200)

        def set_rect(value: Rect) -> None:
            ui_rect_ref.value = value

        rect_control_ui(u, Ref(get_rect, set_rect))

        def flip_show_rect(_):
            show_rect_ref.value = not show_rect_ref.value

        @column_content(u)
        def buttons_col(u: ILoveUI):
            text(u, 'show rect') \
                .clickable(highlight, flip_show_rect, background_color=green if show_rect_ref.value else gray)

            text(u, 'reset') \
                .clickable(highlight, lambda _: ui_rect_ref.set(None), background_color=gray)

        buttons_col.align_xy(None, 0.5)

    return rect_control_row

def render_code_ui(u: ILoveUI, id: UIPath, target_ui_ref: Ref[Callable[[ILoveUI, 'FastStartContext'], None]]) -> Modifying:
    code_ref = (id / 'code_ref').remember(lambda: Ref.new_box(''))

    def submit_code(_):
        try:
            obj = eval(code_ref.value)
            target_ui_ref.value = obj
        except Exception as e:
            dialog(u, f'{e}, {e.args}', lambda _: None, lambda: True)

    @column_content(u)
    def top(u: ILoveUI):

        text_field(u, id / 'code input', code_ref) \
            .flex() \
            .min_size_xy(0, 1000) \
            .v_scroll(id / 'scroll')

        text(u, 'submit') \
            .clickable(highlight, submit_code, gray)

    return top



class VFingerState(Enum):
    up = auto()
    to_down = auto()
    down = auto()
    to_up = auto()



@dataclass(slots=True)
class VFinger:
    finger: Finger = field(default_factory=lambda: Finger(0, 0))
    x: float = 0
    y: float = 0
    state: VFingerState = VFingerState.up
    id: UIPath = field(default_factory=UIPath.root)


    def send_event(self, u: ILoveUI):
        u.context.event_manager.send_event_instantly(HoveringEvent, HoveringEvent(self.finger))

        match self.state:
            case VFingerState.up: ...
            case VFingerState.to_down:
                u.context.event_manager.send_event_instantly(NewFingerEvent, NewFingerEvent(self.finger))
                self.state = VFingerState.down

            case VFingerState.down:
                if self.x != self.finger.x or self.y != self.finger.y:
                    self.finger.x = self.x
                    self.finger.y = self.y
                    for listener in self.finger.drag_listeners:
                        listener(self.finger)

            case VFingerState.to_up:
                for listener in self.finger.release_listeners:
                    listener(self.finger)
                self.finger.drag_listeners.clear()
                self.finger.release_listeners.clear()
                self.state = VFingerState.up

        self.finger.x = self.x
        self.finger.y = self.y


    def set_state(self, value: VFingerState):
        self.state = value


    def v_finger(self, u: ILoveUI):
        def draggable_modifier(p: Placeable) -> Placeable:
            def place_fn(ctx: PlaceContext):
                new_rect = Rect(self.x, self.y - p.min_height / 2, p.min_width, p.min_height)
                ctx = PlaceContext(new_rect, ctx.context, ctx.deferred_render_tick_listeners)
                p.place_fn(ctx)

                def consume_new_finger_event(e: NewFingerEvent) -> bool:
                    in_rect = e.finger.in_rect(ctx)

                    if in_rect:
                        def handle_finger(finger: Finger):
                            self.x = finger.x
                            self.y = finger.y

                        e.finger.on_drag(handle_finger)

                    return in_rect

                ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

                hover = False

                def consume_hovering_event(e: HoveringEvent) -> bool:
                    nonlocal hover
                    in_rect = e.finger.in_rect(ctx)
                    if in_rect:
                        hover = True
                    return in_rect

                ctx.context.event_manager.consume_events(HoveringEvent, consume_hovering_event)

                if hover:
                    ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, highlight))

            return Placeable(p.min_width, p.min_height, place_fn)

        @row_content(u)
        def top(u: ILoveUI):
            text(u, '<- v finger', color=black)

            match self.state:
                case VFingerState.up:
                    text(u, 'curr up', color=black) \
                        .clickable(highlight, lambda _: self.set_state(VFingerState.to_down))
                case VFingerState.to_down:
                    text(u, 'curr to down', color=black) \
                        .clickable(highlight, lambda _: self.set_state(VFingerState.up))
                case VFingerState.down:
                    text(u, 'curr down', color=black) \
                        .clickable(highlight, lambda _: self.set_state(VFingerState.to_up))
                case VFingerState.to_up:
                    text(u, 'curr to up', color=black) \
                        .clickable(highlight, lambda _: self.set_state(VFingerState.down))

        top \
            .background(highlight, touch_through=True) \
            .modifier(draggable_modifier)



@dataclass(slots=True)
class FastStartContext:
    fps: float

checkbox_text_color = Color(220, 20, 220)

@dataclass(slots=True)
class FastDebug:
    ui_renderer_ui_state: UIRendererUIState
    intercept_events: bool = False
    v_finger: VFinger = field(default_factory=VFinger)
    show_v_finger: bool = True
    ui_rect: Rect | None = None
    show_rect: bool = True

    render_layer_manager: RenderLayerManager = field(default_factory=RenderLayerManager)
    color_ref: Ref[Color] = field(default_factory=lambda: Ref.new_box(Color(0, 0, 0, 255)))
    id: UIPath = field(default_factory=UIPath.root)


    def fast_debug_ui(self, u: ILoveUI) -> None:
        id = self.id
        color_ref = self.color_ref

        def open_ui_rect_control_window(u: ILoveUI):
            @window_content(u, single_window_key=id / 'ui_rect_control_window')
            def ui_rect_control_window(u: ILoveUI, ctx: PopupContext):
                debug_ui_rect_control_ui(u, Ref.from_attr(self, 'ui_rect'), Ref.from_attr(self, 'show_rect'))

        def open_color_selector_window(u: ILoveUI):
            @window_content(u, single_window_key=id / 'color_selector_window')
            def color_selector_window(u: ILoveUI, ctx: PopupContext):
                rgba_color_selector(u, color_ref)

        def open_render_layer_window(u: ILoveUI):
            @window_content(u, single_window_key=id / 'render_layer_window')
            def render_layer_window(u: ILoveUI, ctx: PopupContext):
                if self.ui_renderer_ui_state is not None:
                    max_layer = len(self.ui_renderer_ui_state.cached_render_tick_listeners) if self.ui_renderer_ui_state.cached_render_tick_listeners is not None else 0
                else:
                    max_layer = 0
                render_layer_control_ui(u, max_layer, self.render_layer_manager)

        def open_code_window(u: ILoveUI):
            @window_content(u, single_window_key=id / 'code_window')
            def render_layer_window(u: ILoveUI, ctx: PopupContext):
                if self.ui_renderer_ui_state is not None:
                    render_code_ui(u, id / 'render_code_ui', Ref.from_attr(self.ui_renderer_ui_state, UIRendererUIState.target_ui.__name__)) \
                        .min_size_xy(300, 300)

        def open_v_finger_window(u: ILoveUI):
            @window_content(u, single_window_key=id / 'v_finger_window', layout=column)
            def render_layer_window(u: ILoveUI, ctx: PopupContext):
                checkbox(u, Ref.from_attr(self, 'intercept_events'), id / 'intercept events checkbox') \
                    .flex() \
                    .tag_up(u, 'intercept events', id / 'intercept events checkbox tag', text_color=checkbox_text_color)

                checkbox(u, Ref.from_attr(self, 'show_v_finger'), id / 'show v finger checkbox') \
                    .flex() \
                    .tag_up(u, 'show v-finger', id / 'show v finger checkbox tag', text_color=checkbox_text_color)

        popup_layer(u)

        if self.show_v_finger:
            self.v_finger.v_finger(u)

        if self.show_rect and self.ui_rect is not None:
            spacing(u) \
                .background(highlight, touch_through=True) \
                .with_rect(self.ui_rect)

        @column_content(u)
        def top_column(u: ILoveUI):

            if self.ui_renderer_ui_state is not None:
                self.ui_renderer_ui_state.sync_events = not self.intercept_events
                ui_renderer_ui(
                    u,
                    self.ui_renderer_ui_state,
                    map_render_tick_listeners=self.render_layer_manager.render_mode_to_list_mapper(),
                    rect=self.ui_rect,
                    before_step=lambda: self.v_finger.send_event(self.ui_renderer_ui_state.target_ui_u) # type: ignore
                ) \
                    .flex()

            @row_content(u)
            def control_row(u: ILoveUI):
                checkbox(u, Ref(u.context.renderer.get_scissor_enabled, u.context.renderer.set_scissor_enabled), id / 'scissor checkbox') \
                    .flex() \
                    .tag_up(u, 'scissor', id / 'scissor checkbox tag', text_color=checkbox_text_color)

                text(u, 'v-finger') \
                    .flex() \
                    .clickable(highlight, lambda _: open_v_finger_window(u), check_scissor_rect=False)

                text(u, 'ui rect') \
                    .flex() \
                    .clickable(highlight, lambda _: open_ui_rect_control_window(u), check_scissor_rect=False)

                text(u, 'bg color') \
                    .flex() \
                    .clickable(highlight, lambda _: open_color_selector_window(u), check_scissor_rect=False)

                text(u, 'layer') \
                    .flex() \
                    .clickable(highlight, lambda _: open_render_layer_window(u), check_scissor_rect=False)

                text(u, 'code') \
                    .flex() \
                    .clickable(highlight, lambda _: open_code_window(u), check_scissor_rect=False)

                if self.ui_renderer_ui_state is not None:
                    text(u, 'single step' if self.ui_renderer_ui_state.single_step_mode else 'running') \
                        .flex() \
                        .clickable(highlight, lambda _: self.ui_renderer_ui_state.toggle_mode() if self.ui_renderer_ui_state is not None else None, check_scissor_rect=False)

                    text(u, 'stepping' if self.ui_renderer_ui_state.step else 'step') \
                        .flex() \
                        .clickable(highlight, lambda _: self.ui_renderer_ui_state.toggle_step() if self.ui_renderer_ui_state is not None else None, check_scissor_rect=False)

        spacing(u) \
            .background(color_ref.value)


def fast_debug(target_ui: Callable[[ILoveUI, FastStartContext], None]) -> None:
    state: FastDebug | None = None

    def fast_debug_ui(u: ILoveUI, ctx: FastStartContext) -> None:
        nonlocal state
        # todo 渲染剪刀区域 [ ]
        # todo 可视化低代码编辑器 [ ]

        if state is None:
            target_ui_u = ILoveUI(ILoveUIContext(u.context.renderer))
            state = FastDebug(UIRendererUIState(ctx, target_ui, target_ui, target_ui_u))

        state.ui_renderer_ui_state.fast_start_ctx = ctx
        state.fast_debug_ui(u)

    fast_start(fast_debug_ui)

# ==================== fast start ====================

class FastStart:
    def __init__(self, ui: Callable[[ILoveUI, FastStartContext], None], ctx: ILoveUIContext, screen_rect: Rect) -> None:
        self.ui = ui
        self.ctx = ctx
        self.screen_rect = screen_rect
        self.fps = 0.0

        if not ctx.fingers:
            ctx.fingers.append(Finger(0, 0))



    def handle_pygame_event(self, e: pygame.event.Event):
        ctx = self.ctx

        if e.type == pygame.VIDEORESIZE:
            w, h = e.size
            self.screen_rect = Rect(0, 0, w, h)

        elif e.type == pygame.TEXTINPUT:
            self.ctx.event_manager.send_event(TextInputEvent, TextInputEvent(e.text))

        elif e.type == pygame.MOUSEWHEEL:
            mouse_x, mouse_y = pygame.mouse.get_pos()
            ctx.event_manager.send_event(ScrollEvent, ScrollEvent(mouse_x, mouse_y, e.x, e.y))

        elif e.type == pygame.MOUSEBUTTONDOWN:
            if e.button != 4 and e.button != 5: # 排除滚轮事件
                x, y = e.pos
                finger = Finger(x, y)
                if len(ctx.fingers) > 0:
                    ctx.fingers[0] = finger
                else:
                    ctx.fingers.append(finger)
                ctx.event_manager.send_event(NewFingerEvent, NewFingerEvent(finger))

        elif e.type == pygame.MOUSEMOTION:
            if len(ctx.fingers) > 0:
                finger = ctx.fingers[0]
                x, y = e.pos
                finger.x = x
                finger.y = y
                for listener in finger.drag_listeners:
                    listener(finger)

        elif e.type == pygame.MOUSEBUTTONUP:
            if len(ctx.fingers) > 0:
                finger = ctx.fingers[0]
                x, y = e.pos
                finger.x = x
                finger.y = y
                finger.drag_listeners.clear()
                for listener in finger.release_listeners:
                    listener(finger)
                finger.release_listeners.clear()

        elif e.type == pygame.KEYDOWN:
            ctx.event_manager.send_event(KeyEvent, KeyEvent(e.key, e.scancode, e.unicode, True))

        elif e.type == pygame.KEYUP:
            ctx.event_manager.send_event(KeyEvent, KeyEvent(e.key, e.scancode, e.unicode, False))



    def tick(self) -> None:
        ctx = self.ctx

        for finger in ctx.fingers:
            ctx.event_manager.send_event(HoveringEvent, HoveringEvent(finger))

        ctx.event_manager.before_render()
        ctx.render_in(self.screen_rect, lambda u: self.ui(u, FastStartContext(self.fps)))



def fast_start(ui: Callable[[ILoveUI, FastStartContext], None]) -> None:
    running = True

    # pygame初始化
    pygame.init()
    screen = pygame.display.set_mode((800, 800), pygame.SRCALPHA | pygame.RESIZABLE)
    screen_rect = Rect(0, 0, 800, 800)
    pygame.display.set_caption("ILoveUI")
    clock = pygame.time.Clock()

    renderer = PygameILoveUIRenderer(screen)
    ctx = ILoveUIContext(renderer)
    fast_start = FastStart(ui, ctx, screen_rect)

    pygame.key.set_repeat(320, 50) # todo 这是为了流畅的文本删除, 但是会导致其它键的 KeyDown 事件快速连续触发

    while running:
        # 事件处理
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False
            fast_start.handle_pygame_event(e)

        # 清屏
        screen.fill((40,40,40))
        fast_start.fps = clock.get_fps()

        fast_start.tick()

        # 刷新屏幕
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

# ==================== visual editor ====================

@dataclass(slots=True)
class PythonCode:
    code_lines: list[str]
    ui_state: UIPath = field(default_factory=UIPath.root)

    def visual_tree_ui(self, u: ILoveUI, _: 'VisualTreeUI') -> Modifying:
        return text_field(u, self.ui_state, Ref.from_attr(self, 'code_lines'))

@dataclass(slots=True)
class WidgetNode:
    widget_value: str
    args: list['ContentNode | PythonCode'] = field(default_factory=lambda: [])
    modifiers: list['ModifierNode'] = field(default_factory=lambda: [])
    ui_state: UIPath = field(default_factory=UIPath.root)

    def visual_tree_ui(self, u: ILoveUI, tree_ui: 'VisualTreeUI') -> Modifying:
        @column_content(u)
        def top(u: ILoveUI):

            text(u, self.widget_value, color=tree_ui.style.widget_text) \
                .background(tree_ui.style.widget_bg)

            @row_content(u)
            def args_row(u: ILoveUI):
                text(u, 'args: ', color=tree_ui.style.widget_text) \
                    .background(tree_ui.style.widget_bg)

                def insert_arg_at(idx: int):
                    self.args.insert(idx, ContentNode())
                    tree_ui.on_tree_changed()

                def remove_at(idx: int):
                    del self.args[idx]
                    tree_ui.on_tree_changed()

                def swap_at(idx: int, idx1: int):
                    t = self.args[idx]
                    self.args[idx] = self.args[idx1]
                    self.args[idx1] = t
                    tree_ui.on_tree_changed()

                manageable_list(
                    u,
                    self.args,
                    element_ui=lambda u, _, e: e.visual_tree_ui(u, tree_ui),
                    insert_at=insert_arg_at,
                    remove_at=remove_at,
                    swap_at=swap_at,
                )

            @row_content(u)
            def modifiers_row(u: ILoveUI):
                text(u, 'modifiers: ', color=tree_ui.style.widget_text) \
                    .background(tree_ui.style.widget_bg)

                def insert_at(idx: int):
                    self.modifiers.insert(idx, ModifierNode('new modifier'))
                    tree_ui.on_tree_changed()

                def remove_at(idx: int):
                    del self.modifiers[idx]
                    tree_ui.on_tree_changed()

                def swap_at(idx: int, idx1: int):
                    t = self.modifiers[idx]
                    self.modifiers[idx] = self.modifiers[idx1]
                    self.modifiers[idx1] = t
                    tree_ui.on_tree_changed()

                manageable_list(
                    u,
                    self.modifiers,
                    element_ui=lambda u, _, e: e.visual_tree_ui(u, tree_ui),
                    insert_at=insert_at,
                    remove_at=remove_at,
                    swap_at=swap_at,
                )

        return top \
            .background(gray)


@dataclass(slots=True)
class ModifierNode:
    modifier_value: str
    args: list[PythonCode] = field(default_factory=lambda: [])
    ui_state: UIPath = field(default_factory=UIPath.root)

    def visual_tree_ui(self, u: ILoveUI, tree_ui: 'VisualTreeUI') -> Modifying:
        return text_field(u, self.ui_state, Ref.from_attr(self, 'modifier_value').value_changed(lambda _, _1: tree_ui.on_tree_changed()))


@dataclass(slots=True)
class ContentNode:
    widgets: list['WidgetNode | PythonCode'] = field(default_factory=lambda: [])

    def visual_tree_ui(n, u: ILoveUI, self: 'VisualTreeUI') -> Modifying:
        @row_content(u)
        def top_row(u: ILoveUI):
            spacing(u, width=20) \
                .background(self.style.content_bg)

            def insert_at(idx: int):
                n.widgets.insert(idx, WidgetNode('new widget'))
                self.on_tree_changed()

            def remove_at(idx: int):
                del n.widgets[idx]
                self.on_tree_changed()

            manageable_list(
                u,
                n.widgets,
                element_ui=lambda u, _, e: e.visual_tree_ui(u, self),
                insert_at=insert_at,
                remove_at=remove_at,
            )

        return top_row


class VisualTreeDumper:
    def __init__(self, tag_str: str = '\t') -> None:
        self.tag_str = tag_str

    def dump_content_str(self, n: ContentNode) -> str:
        return '\n'.join(self.dump_content_lines(n))

    def dump_python_code_lines(self, n: PythonCode) -> Generator[str, None, None]:
        yield from n.code_lines

    def dump_widget_lines(self, n: WidgetNode) -> Generator[str, None, None]:
        for i, arg in enumerate(n.args):
            yield f'def content{i}(u: ILoveUI) -> None:'

            for line in self.dump_content_lines(arg) if isinstance(arg, ContentNode) else self.dump_python_code_lines(arg):
                yield f'{self.tag_str}{line}'

            yield ''

        yield f'{n.widget_value}({", ".join(map(lambda x: f"content{x}", range(len(n.args))))})'

        for modifier in n.modifiers:
            yield f'{self.tag_str}.{modifier.modifier_value} \\'

    def dump_content_lines(self, n: ContentNode) -> Generator[str, None, None]:
        for widget in n.widgets:
            for line in self.dump_widget_lines(widget) if isinstance(widget, WidgetNode) else self.dump_python_code_lines(widget):
                yield self.tag_str + line

            yield ''


@dataclass(slots=True)
class VisualTreeUIStyle:
    content_bg: Color
    content_text: Color
    widget_bg: Color
    widget_text: Color
    modifier_bg: Color
    modifier_text: Color

styles = [
    VisualTreeUIStyle(
        Color(220, 240, 255), # （浅天蓝）
        Color(30, 60, 100), # （深蓝灰）
        Color(240, 230, 255), # （浅薰衣紫）
        Color(70, 40, 100), # （深紫灰）
        Color(235, 250, 235), # （浅薄荷绿）
        Color(40, 90, 40), # （深墨绿）
    ),
    VisualTreeUIStyle(
        Color(255, 235, 200), # （浅暖橙）
        Color(120, 60, 0), # （深橙红）
        Color(255, 220, 230), # （浅柔粉）
        Color(130, 30, 60), # （深玫红）
        Color(210, 245, 255), # （浅青蓝）
        Color(20, 80, 110), # （深海蓝）
    ),
    VisualTreeUIStyle(
        Color(50, 70, 100), # （深灰蓝）
        Color(245, 245, 255), # （纯白）
        Color(70, 50, 90), # （深紫灰）
        Color(245, 245, 255), # （纯白）
        Color(40, 80, 60), # （深墨绿）
        Color(245, 245, 255), # （纯白）
    )
]


@dataclass(slots=True)
class VisualTreeUI:
    root_content: ContentNode
    on_tree_changed: Callable[[], None] = lambda: None
    single_window_key: UIPath = field(default_factory=UIPath.root)
    style: VisualTreeUIStyle = field(default_factory=lambda: random.choice(styles))

    def visual_tree_content_ui(self, u: ILoveUI) -> Modifying:
        return self.root_content.visual_tree_ui(u, self)



class VisualEditor:
    def __init__(self) -> None:
        self.tree = VisualTreeUI(ContentNode(), on_tree_changed=self.on_tree_changed)
        self.id = UIPath.root()
        self.code_text = ''

    def on_tree_changed(self):
        self.code_text = VisualTreeDumper('    ').dump_content_str(self.tree.root_content)

    def code_ui(self, u: ILoveUI) -> Modifying:
        return text_field(u, self.id / 'code_ui text', Ref.from_attr(self, 'code_text')) \
            .expend_xy(40, 0)

    def visual_editor_ui(self, u: ILoveUI) -> Modifying:
        @row_content(u)
        def top_row(u: ILoveUI):

            self.tree.visual_tree_content_ui(u) \
                .v_scroll(self.id / 'tree v_scroll') \
                .h_scroll(self.id / 'tree h_scroll') \
                .flex()

            self.code_ui(u) \
                .v_scroll(self.id / 'code v_scroll') \
                .h_scroll(self.id / 'code h_scroll') \
                .flex()

        return top_row



# ==================== test ====================

@dataclass(slots=True)
class TestAnimationButton:
    align: float = 0
    animation_has_started: bool = False
    animation_valid_key: int = 0

def test_animation_button(u: ILoveUI, id: UIPath) -> Modifying:
    state = (id / 'state').remember(TestAnimationButton)

    def startAnimation(_):
        state.animation_has_started = True
        state.animation_valid_key = state.animation_valid_key + 1

    if state.animation_has_started:
        @tick_coroutine_content(id / 'animate test coroutine', state.animation_valid_key)
        async def co():
            for i in range(60):
                state.align = i / 59
                await suspend
            for i in range(60):
                state.align = 1 - i / 59
                await suspend

    return text(u, 'animate test', id / 'animate test text') \
        .flex() \
        .clickable(highlight, startAnimation, background_color=Color(100, 100, 100, 255)) \
        .align_xy(state.align, None)

def sleep_button(u: ILoveUI, id: UIPath) -> Modifying:
    enable_sleep_ref = (id / 'toggle sleep btn').remember(lambda: [False])

    if enable_sleep_ref[0]:
        time.sleep(0.1) # 测试 render_time_text

    def toggle_enable_sleep(_):
        enable_sleep_ref[0] = not enable_sleep_ref[0]

    return text(u, 'sleep 0.1s') \
        .expend_xy(10, 0) \
        .clickable(highlight, toggle_enable_sleep, background_color=Color(255, 40, 40) if enable_sleep_ref[0] else Color(80, 80, 80))

def hello_world_button(u: ILoveUI) -> Modifying:
    return text(u, 'hello world') \
        .expend_xy(10, 0) \
        .clickable(highlight, lambda _: toast(u, 'hello'), background_color=Color(100, 100, 100, 255))

def open_window_button(u: ILoveUI, id: UIPath) -> Modifying:
    rect_ref = (id / 'rect_ref').remember(lambda: Ref.new_box(Rect(0, 0, 100, 100)))

    def open_window(_):
        @dataclass(slots=True)
        class State:
            closed: bool = False
            max_size_and_size: tuple[float, float, float, float] | None = None

        state = State()
        window_id = UIPath.root()

        random_offset = 40
        r = rect_ref.value
        @window_content(u, initial_x=r.center_x + random.random() * random_offset, initial_y=r.y + r.h + 40 + random.random() * random_offset, with_close_button=False)
        def window_test(u: ILoveUI, ctx: PopupContext):
            def close_window():
                toast(u, 'window closing')
                state.closed = True

            if state.closed:
                @tick_coroutine_content(window_id / 'co')
                async def co():
                    try:
                        for i in range(20):
                            mw, mh, w, h = state.max_size_and_size # type: ignore
                            w = mw * (1 - i / 19)
                            h = mh * (1 - i / 19)
                            state.max_size_and_size = mw, mh, w, h
                            await suspend
                    finally:
                        toast(u, 'window closed')
                        ctx.close()

            @memo_content(u, window_id / 'memo layout')
            def window_box(u: ILoveUI):
                window_close_button(u, close_window)

                @column_content(u)
                def window_column(u: ILoveUI):
                    text(u, 'hello window') \
                        .expend_xy(80, 80)

                    number_pad(u, lambda n: toast(u, str(n)), id=window_id)

            if state.max_size_and_size is None:
                w = window_box.placeable.min_width
                h = window_box.placeable.min_height
                state.max_size_and_size = (w, h, w, h)

            if state.closed:
                _, _, w, h = state.max_size_and_size
                window_box.placeable = Placeable(w, h, window_box.placeable.place_fn)

    open_window_count = 25
    def open_more_window(_):
        for _ in range(open_window_count):
            open_window(None)

    @row_content(u)
    def buttons_row(u: ILoveUI):
        text(u, 'window') \
            .expend_xy(10, 0) \
            .clickable(highlight, open_window, background_color=Color(100, 100, 100, 255))

        text(u, f'{open_window_count} * window') \
            .expend_xy(10, 0) \
            .clickable(highlight, open_more_window, background_color=Color(100, 100, 100, 255))

    return buttons_row \
        .getRect(rect_ref)



def fruits_ui(u: ILoveUI, id: UIPath, fruits_lst: list[str], selected_index: Ref[int]) -> Modifying:
    @memo_content(u, id / 'memo test', fruits_lst[selected_index.value])
    def memo_test(u: ILoveUI):
        text(u, fruits_lst[selected_index.value]) \
            .repaint_flash()

    memo_test \
        .flex() \
        .background(Color(80, 255, 80)) \

    def fruit_ui(u, fruit_index, fruit):
        def set_selected(_):
            toast(u, fruit)
            selected_index.value = fruit_index

        return text(u, fruit) \
            .clickable(highlight, set_selected, background_color=Color(255, 80, 80) if fruit_index == selected_index.value else Color(80, 80, 255)) \
            .flex()

    @row_content(u)
    def fruits_row(u):
        for index, fruit in enumerate(fruits_lst):
            fruit_ui(u, index, fruit)

    return fruits_row \
        .expend_xy(0, 20)



def test_scroll_ui(u: ILoveUI, id: UIPath) -> Modifying:
    def element_button(u: ILoveUI, i: int, id: UIPath) -> Modifying:
        return text(u, f'element {i}', id) \
            .clickable(highlight, lambda _: toast(u, f'element {i}'), background_color=Color(80, 80, 80)) \
            .align_xy(0, None)

    element_id = id / 'scroll_test_elements'

    @lazy_list_column_content(u, id / 'lazy column', range(12000000))
    def element_buttons(u: ILoveUI, i: int) -> Modifying:
        return element_button(u, i, element_id / i) \
            .expend_xy(0, 10)

    return element_buttons \
        .expend_xy(40, 80)



@dataclass(slots=True)
class TestUIState:
    fruits: list[str] = field(default_factory=lambda: ['apple', 'banana', 'watermelon', 'pear', 'cherry'])
    selected: int = 0
    slider_val: list[float] = field(default_factory=lambda: [50.0])
    ui_root: UIPath = field(default_factory=UIPath.root)

def test_screen_content(u: ILoveUI, fps: float):
    test_ui_state = u.context.remember(TestUIState, TestUIState)

    popup_layer(u)

    test_animation_button(u, test_ui_state.ui_root / 'test_animation_button') \
        .expend_xy(40, 40) \
        .align_xy(None, 0.5)

    @row_content(u)
    def top_row(u: ILoveUI):

        test_scroll_ui(u, test_ui_state.ui_root / 'test_scroll_ui')

        @column_content(u)
        def top_column(u: ILoveUI):
            render_time_text(u, test_ui_state.ui_root / 'render_time_text') \
                .tag_left(u, 'Render Time: ')

            text(u, f'{fps:.4f}') \
                .tag_left(u, 'fps: ') \
                .expend_xy(0, 10)

            popup_manager = u.context.remember(PopupManager, PopupManager)

            text(u, f'{len(popup_manager.popups)}') \
                .tag_left(u, 'popup count: ')

            @row_content(u)
            def buttons_row(u: ILoveUI):
                sleep_button(u, test_ui_state.ui_root / 'sleep button')
                hello_world_button(u)
                open_window_button(u, test_ui_state.ui_root / 'open_window_button')

                checked = (test_ui_state.ui_root / 'checked').remember(lambda: Ref.new_box(False))
                checkbox(u, checked, test_ui_state.ui_root / 'check_box') \
                    .expend_xy(80, 0)

            buttons_row.expend_xy(0, 20)

            fruits_ui(u, test_ui_state.ui_root / 'fruits ui', test_ui_state.fruits, Ref.from_attr(test_ui_state, 'selected'))

            spacing(u, 0, 10)

            # 文本输入框
            input_text_1 = (test_ui_state.ui_root / 'input_text_1').remember(lambda: Ref.new_box(''))
            input_text_2 = (test_ui_state.ui_root / 'input_text_2').remember(lambda: Ref.new_box(''))

            @memo_content(u, test_ui_state.ui_root / 'memo_text_field_test', input_text_1.value)
            def memo_text_field_test(u: ILoveUI):
                text(u, f"memo text field: {input_text_1.value}") \
                    .repaint_flash()

            text_field(u, test_ui_state.ui_root / 'text_field 1', input_text_1) \
                .padding_xy(20, 0)

            text_field(u, test_ui_state.ui_root / 'text_field 2', input_text_2) \
                .padding_xy(20, 0)

            spacing(u, 0, 10)

            # 数字滑块
            text(u, f"value: {test_ui_state.slider_val[0]:.0f}")
            slider(u, Ref.from_list_slot(test_ui_state.slider_val), 0, 100)

            def dialog_cancelled() -> bool:
                toast(u, 'cancelled')
                return True

            def open_dialog(_):
                dialog(u, 'test dialog', lambda yes_or_no: toast(u, f'you chosen {yes_or_no}'), dialog_cancelled)

            text(u, 'dialog') \
                .expend_xy(20, 20) \
                .clickable(highlight, open_dialog)

            touchpad_vec = (test_ui_state.ui_root / 'touchpad_vec').remember(lambda: Ref[tuple[float, float]].new_box((0.5, 0.5)))

            touchpad(u, touchpad_vec) \
                .expend_xy(20, 20) \
                .background(Color(100, 100, 100)) \
                .align_xy(0, 0)

            def click_inc_number_button(u: ILoveUI, id: UIPath) -> Modifying:
                count_ref = (id / 'count_ref').remember(lambda: [0])

                def inc_count(_):
                    count_ref[0] += 1
                    toast(u, f'current count: {count_ref[0]}')

                return text(u, f'click me: {count_ref[0]}') \
                    .clickable(highlight, inc_count)

            @row_content(u)
            def stateful_test_row(u: ILoveUI):
                id = test_ui_state.ui_root
                click_inc_number_button(u, id / 'click_inc_number_button 1').flex()
                click_inc_number_button(u, id / 'click_inc_number_button 2').flex()

            stateful_test_row.expend_xy(0, 20)

        top_column.flex()

    top_row \
        .animated_rect(test_ui_state.ui_root / 'top_column animate')

def main():
    v = VisualEditor()
    ui: Callable[[ILoveUI, FastStartContext], None]

    def set_ui(value: Callable[[ILoveUI, FastStartContext], None]):
        nonlocal ui
        ui = value

    def test_screen_ui(u: ILoveUI, ctx: FastStartContext):
        test_screen_content(u, ctx.fps)

    def visual_editor(u: ILoveUI, _: FastStartContext):
        popup_layer(u)
        v.visual_editor_ui(u)

    def choice_ui(u: ILoveUI, ctx: FastStartContext):
        @column_content(u)
        def choice_col(u: ILoveUI):
            text(u, 'visual_editor').clickable(highlight, lambda _: set_ui(visual_editor))
            text(u, 'test screen').clickable(highlight, lambda _: set_ui(test_screen_ui))

    ui = choice_ui

    def dispatcher(u: ILoveUI, ctx: FastStartContext):
        if ui is not choice_ui:
            window_close_button(u, lambda: set_ui(choice_ui))
        ui(u, ctx)

    fast_debug(dispatcher)

if __name__ == '__main__':
    main()
