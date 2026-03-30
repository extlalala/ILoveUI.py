import dataclasses
import functools
import pygame
import random
import time

from abc import ABC, abstractmethod
from asyncio import CancelledError
from dataclasses import dataclass, field
from enum import auto, Enum
from typing import Any, Callable, Coroutine, Generic, Hashable, Literal, Self, TypeVar

T = TypeVar('T')

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

    drag_listener: Callable[['Finger'], Any] | None = None
    release_listener: Callable[['Finger'], Any] | None = None

    def in_rect(self, ctx: 'PlaceContext', check_scissor_rect: bool) -> bool:
        return ((not check_scissor_rect or ctx.context.renderer.contains_point(self.x, self.y)) and
                ctx.rect.contains_point(self.x, self.y))

@dataclass(slots=True)
class NewFingerEvent:
    finger: Finger

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
        def set_value(value: T):
            lst[slot_index] = value

        return Ref(lambda: lst[slot_index], set_value)

    @staticmethod
    def from_attr(obj: Any, attr_name: str) -> 'Ref[T]':
        return Ref(lambda: getattr(obj, attr_name), lambda value: setattr(obj, attr_name, value))

    @staticmethod
    def new_box(initial_value: T) -> 'Ref[T]':
        lst = [initial_value]
        return Ref.from_list_slot(lst)

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

    def with_rect(self, rect: Rect, component_min_width: float = 10, component_min_height: float = 10) -> Self:
        '''
        直接指定组件的 rect
        '''
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            p.place_fn(PlaceContext(rect, ctx.context, ctx.deferred_render_tick_listeners))
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

            ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, color))

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def clickable(self, hover_color: Color | None, click_callback: Callable[[Finger], None], check_scissor_rect: bool = True) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            def consume_new_finger_event(e: NewFingerEvent) -> bool:
                in_rect = e.finger.in_rect(ctx, check_scissor_rect)

                if in_rect:
                    def finger_release_listener(finger):
                        if e.finger.in_rect(ctx, check_scissor_rect):
                            click_callback(finger)

                    e.finger.release_listener = finger_release_listener

                return in_rect

            ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

            if hover_color is not None and any(finger.in_rect(ctx, check_scissor_rect) for finger in ctx.context.fingers):
                ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, hover_color)) # type: ignore

            p.place_fn(ctx)

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
                    e.finger.release_listener = release_listener

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

    def tag(self, u: 'ILoveUI', tag_str: str, id: UIPath | None = None, with_spacing: bool = True, min_size: float = 0) -> Self:
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
        mouse_wheel_speed: float = -10,
        scissor: bool = True,
    ) -> Self:
        p = self.placeable
        self.placeable = scroll_modifier(id, p, horizontal=False, friction=friction, mouse_wheel_speed=mouse_wheel_speed, scissor=scissor)
        return self

    def h_scroll(
        self,
        id: UIPath,
        friction: float = 0.92,
        mouse_wheel_speed: float = -10,
        scissor: bool = True,
    ) -> Self:
        p = self.placeable
        self.placeable = scroll_modifier(id, p, horizontal=True, friction=friction, mouse_wheel_speed=mouse_wheel_speed, scissor=scissor)
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

def scroll_modifier(
    id: UIPath,
    element_ui: Placeable,
    horizontal: bool = False,
    friction: float = 0.92,
    mouse_wheel_speed: float = -10,
    scissor: bool = True,
    check_scissor_rect: bool = True
) -> Placeable:
    state = id.remember(ScrollState)

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

            return True

        ctx.context.event_manager.consume_events(ScrollEvent, consume_scroll_event)

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
        child_ctx = PlaceContext(content_rect, ctx.context, ctx.deferred_render_tick_listeners)

        if scissor:
            ctx.context.renderer.push_scissor(ctx.rect, for_render=False) # 用于拦截事件
            ctx.deferred_render_tick(lambda: ctx.context.renderer.pop_scissor(), RenderOperateType.scissor_op) # defer 从下到上执行

        # if scissor:
            # element_ui = Modifying(element_ui).scissor().placeable # todo why

        element_ui.place_fn(child_ctx)

        if scissor:
            ctx.context.renderer.pop_scissor() # 用于拦截事件
            ctx.deferred_render_tick(lambda: ctx.context.renderer.push_scissor(ctx.rect), RenderOperateType.scissor_op) # defer 从下到上执行

        #拖拽
        def consume_finger(e: NewFingerEvent) -> bool:
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

            state.dragging = True
            state.drag_start = e.finger.x if horizontal else e.finger.y
            state.last_drag = state.drag_start
            state.drag_start_scroll = state.scroll
            e.finger.drag_listener = on_drag
            e.finger.release_listener = on_release

            return True

        ctx.context.event_manager.consume_events(NewFingerEvent, consume_finger)

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

class PopupManager:
    def __init__(self) -> None:
        self.popups: list[Popup] = []
        self.enabled = True

    def add(self, popup_content: Callable[[ILoveUI, PopupContext], Any]) -> None:
        self.popups.append(Popup(popup_content))

def popup_layer(u: ILoveUI) -> None:
    '''
    在 ui 最上层的第一行调用
    '''
    popupManager = u.context.remember(PopupManager, PopupManager)

    if not popupManager.enabled:
        return

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
        raise ValueError("must call 'popup_layer' before call 'popup'")
    popupManager.add(popup_content)

# ==================== popups ====================

TOAST_DURATION_SECONDS = 2

def toast(u: ILoveUI, toast_str: str) -> None:
    create_time = time.time()
    offset = 0
    state = UIPath.root()

    @popup_content(u)
    def toast_popup(u: ILoveUI, ctx: PopupContext) -> None:
        nonlocal offset

        current_time = time.time()
        if current_time - create_time > TOAST_DURATION_SECONDS:
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
    with_close_button: bool = True
) -> Callable[[Callable[[ILoveUI, PopupContext], None]], None]:
    def decorator(content: Callable[[ILoveUI, PopupContext], None]) -> None:
        window(u, content, initial_x, initial_y, layout, with_close_button)
    return decorator

WINDOW_FRAME_SIZE = 14

def window(
    u: ILoveUI,
    content: Callable[[ILoveUI, PopupContext], None],
    initial_x: float = 100,
    initial_y: float = 200,
    layout: Callable[[ILoveUI, Callable[[ILoveUI], None]], Modifying] | None = None,
    with_close_button: bool = True
) -> None:
    if layout is None:
        layout = box

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

                    e.finger.drag_listener = finger_drag_listener

                return in_rect

            ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_events)

            frame_rect = ctx.rect
            content_rect = frame_rect.with_padding(WINDOW_FRAME_SIZE, WINDOW_FRAME_SIZE)
            if any(frame_rect.contains_point(finger.x, finger.y) and not content_rect.contains_point(finger.x, finger.y) for finger in ctx.context.fingers):
                ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, highlight))

        return Placeable(p.min_width, p.min_height, place_fn)

    if with_close_button:
        old_content = content
        def wrapped_content(u: ILoveUI, ctx: PopupContext) -> None:
            window_close_button(u, ctx.close)
            old_content(u, ctx)
        content = wrapped_content

    @popup_content(u)
    def window_popup(u: ILoveUI, ctx: PopupContext) -> None:
        content_ui = layout(u, lambda u: content(u, ctx))

        content_ui \
            .background(Color(40, 40, 40), touch_through=True) \
            .padding_xy(WINDOW_FRAME_SIZE, WINDOW_FRAME_SIZE) \
            .modifier(draggable_modifier) \
            .background(Color(80, 80, 80), touch_through=True) \
            .on_touchdown(lambda _: ctx.set_to_top()) \
            .animated_rect(state)

        min_w, min_h = content_ui.placeable.min_width, content_ui.placeable.min_height
        content_ui.with_rect(Rect(rect_x, rect_y, min_w, min_h))

# ==================== layouts ====================

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

def memo(
    u: ILoveUI,
    id: UIPath,
    content: Callable[[ILoveUI], None],
    valid_key: Any,
    layout: Callable[[ILoveUI, Callable[[ILoveUI], None]], Modifying] | None = None
) -> Modifying:
    '''
    memo 的 content 在不更新时无法接收事件
    '''
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
        def place_component() -> list[RenderOperate]:
            render_tick_listeners: list[RenderOperate] = []

            # 确保每次 place_component 都对应一次 layout_component
            if not state.new_memo:
                state.memo_placeable = layout_component()

            state.new_memo = False
            state.memo_placeable.place_fn(PlaceContext(ctx.rect, ctx.context, render_tick_listeners))
            return render_tick_listeners

        render_tick_listeners = (id / 'render_tick_listeners').remember(place_component, (ctx.rect, valid_key))

        ctx.deferred_render_tick_listeners += render_tick_listeners

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

def text(u: ILoveUI, s: str, id: UIPath | None = None) -> Modifying:
    if id is None:
        text_renderer = u.context.renderer.draw_text(s)
    else:
        text_renderer = id.remember(lambda: u.context.renderer.draw_text(s), valid_key=s)

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
    last_cursor_pos: float = 0

    def show_cursor(self) -> None:
        self.last_blink = time.time()
        self.blink_state = True

def text_field(u: ILoveUI, id: UIPath, text_ref: Ref[str], placeholder: str = "type something...", check_scissor_rect: bool = True) -> Modifying:
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

            spacing(u).on_touchdown(unfocus)

    state = id.remember(TextFieldState)
    min_w = 80
    min_h = 36

    def place_fn(ctx: PlaceContext):
        active = (focus_manager.focused_ui_path == id)

        def consume_new_finger_event(e: NewFingerEvent) -> bool:
            in_rect = e.finger.in_rect(ctx, check_scissor_rect)
            if in_rect and focus_manager.focused_ui_path != id:
                focus_manager.focused_ui_path = id
                add_invisible_unfocus_click_layer()

            return in_rect

        ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

        if active:
            def consume_key_event(e: KeyEvent) -> bool:
                if e.isDown and e.keycode == pygame.K_BACKSPACE:
                    text_ref.value = text_ref.value[:-1]
                    state.show_cursor()
                    return True
                elif e.isDown and e.unicode:
                    text_ref.value += e.unicode
                    state.show_cursor()
                    return True
                return False
            ctx.context.event_manager.consume_events(KeyEvent, consume_key_event)

            now = time.time()
            if now - state.last_blink > 0.5:
                state.blink_state = not state.blink_state
                state.last_blink = now

        def render():
            ctx.context.renderer.fill_rect(ctx.rect, Color(60, 60, 60))
            ctx.context.renderer.fill_rect(ctx.rect, Color(200, 200, 200), line_width = 2 if active else 1)

            s = text_ref.value
            if not s and not active:
                textRenderer = ctx.context.renderer.draw_text(placeholder, color=Color(160, 160, 160))
            else:
                textRenderer = ctx.context.renderer.draw_text(s)

            r = ctx.rect
            textRenderer.render(Rect(r.x+8, r.y + (r.h-textRenderer.min_height)/2, textRenderer.min_width, textRenderer.min_height))

            if active:
                cx = r.x + 8 + textRenderer.min_width + 2
                last_cx = state.last_cursor_pos
                cx = (last_cx * 3 + cx) / 4
                state.last_cursor_pos = cx

                if state.blink_state:
                    cy1 = r.y + 6
                    cy2 = r.y + r.h -6
                    ctx.context.renderer.draw_line(Color(255,255,255), (cx, cy1), (cx, cy2), 2)

        ctx.deferred_render_tick(render)

    return u.element(place_fn, min_w, min_h)

def slider(u: ILoveUI, value_ref: Ref[float], min_val: float, max_val: float, check_scissor_rect: bool = True) -> Modifying:
    def place_fn(ctx: PlaceContext):
        def consume_new_finger_event(e: NewFingerEvent) -> bool:
            in_rect = e.finger.in_rect(ctx, check_scissor_rect)

            def handle_finger(finger):
                t = max(0.0, min(1.0, (finger.x - ctx.rect.x) / ctx.rect.w))
                value_ref.value = min_val + t * (max_val - min_val)

            if in_rect:
                handle_finger(e.finger)
                e.finger.drag_listener = handle_finger

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

def number_input(u: ILoveUI, name_tag: str, value_ref: Ref[float], value_text_min_width: float = 0, level: int = 2) -> Modifying:
    @row_content(u)
    def top_row(u: ILoveUI):

        def number_modify_button(u: ILoveUI, show: str, delta_value: int) -> Modifying:
            return text(u, show) \
                .square_expend() \
                .clickable(highlight, lambda _: value_ref.set(value_ref.value + delta_value))

        if level >= 3:
            number_modify_button(u, '<<<', -100)

        if level >= 2:
            number_modify_button(u, '<<', -10)

        number_modify_button(u, '<', -1)

        text(u, str(value_ref.value)) \
            .min_size_xy(value_text_min_width, 0) \
            .tag(u, name_tag, with_spacing=False)

        number_modify_button(u, '>', 1)

        if level >= 2:
            number_modify_button(u, '>>', 10)

        if level >= 3:
            number_modify_button(u, '>>>', 100)

    return top_row

def number_pad(u: ILoveUI, number_typed: Callable[[int], None], id: UIPath | None = None) -> Modifying:
    def number_button(u: ILoveUI, number: int) -> Modifying:
        return text(u, str(number), id = id / number if id is not None else None) \
            .flex() \
            .background(Color(40, 40, 40)) \
            .clickable(highlight, lambda _: number_typed(number))

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
                    e.finger.drag_listener = handle_finger
                    e.finger.release_listener = finger_release_listener

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

def checkbox(u: ILoveUI, id: UIPath, checked: Ref[bool]) -> Modifying:
    def toggle_checked(_):
        checked.value = not checked.value

    def checkbox_handle_modifier(p: Placeable) -> Placeable:
        def place_fn(ctx: PlaceContext):
            new_rect = ctx.rect.sub_rect_with_align(ctx.rect.h, ctx.rect.h, 1 if checked.value else 0, 0)
            p.place_fn(PlaceContext(new_rect, ctx.context, ctx.deferred_render_tick_listeners))

        return Placeable(p.min_width, p.min_height, place_fn)

    @box_content(u)
    def top_box(u: ILoveUI):
        spacing(u) \
            .background(Color(255, 255, 255)) \
            .animated_rect(id / 'animated_rect 1') \
            .modifier(checkbox_handle_modifier)

        @row_content(u)
        def green_gray_row(u: ILoveUI):
            spacing(u, 0, 0) \
                .flex(1 if checked.value else 0) \
                .background(green) \
                .animated_rect(id / 'animated_rect 0')

            spacing(u, 0, 0) \
                .flex(0 if checked.value else 1) \
                .background(gray) \
                .animated_rect(id / 'animated_rect 2')

    return top_box \
        .clickable(None, toggle_checked)

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
        .background(Color(255, 80, 80)) \
        .clickable(highlight, lambda _: close_window()) \
        .align_xy(1, 0)

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
        .modifier(measure_time_modifier)

def bitmap_ui(
    u: ILoveUI, id: UIPath,
    bitmap: bytearray,
    total_bytes_count: int = -1,
    flip_byte_at: Callable[[int], None] | None = None,
    row_byte_count: int = 8
) -> Modifying:
    '''
    用 byte 表示 bool
    '''
    if total_bytes_count < 0:
        total_bytes_count = len(bitmap)

    def flip_index(index: int) -> None:
        if flip_byte_at is None:
            bitmap[index] = 0 if bitmap[index] != 0 else 1
        else:
            flip_byte_at(index)

    def byte_ui(u: ILoveUI, index: int) -> Modifying:
        return spacing(u) \
            .flex() \
            .background(green if bitmap[index] != 0 else gray) \
            .clickable(highlight, lambda _: flip_index(index))

    @column_content(u)
    def byte_rows_col(u: ILoveUI):
        for row_number in range((total_bytes_count + row_byte_count - 1) // row_byte_count):
            row_start_index = row_number * row_byte_count

            @row_content(u)
            def bytes_row(u: ILoveUI):
                text(u, str(row_start_index), id / row_start_index) \
                    .min_size_xy(40, 0)

                for col_number in range(row_byte_count):
                    index = row_start_index + col_number

                    if index >= total_bytes_count:
                        spacing(u).flex() # 代替缺失的位参与布局, 保持最后一行布局正常
                        continue

                    byte_ui(u, index)

                def flip_row(_, row_start_index = row_start_index):
                    for col_number in range(row_byte_count):
                        index = row_start_index + col_number
                        if index < total_bytes_count:
                            flip_index(index)

                text(u, 'flip', id / 'flip' / row_start_index) \
                    .min_size_xy(40, 0) \
                    .clickable(highlight, flip_row)

            bytes_row \
                .ratio_expend(row_byte_count, 1) \

    return byte_rows_col \
        .v_scroll(id / 'scroll')

def single_component_rgba_color_selector(u: ILoveUI, component_ref: Ref[int]) -> Modifying:
    return slider(u, Ref(component_ref.get, lambda value: component_ref.set(int(value))), 0, 255)

def rgba_color_selector(u: ILoveUI, color_ref: Ref[Color]) -> Modifying:
    @row_content(u)
    def top_row(u: ILoveUI):

        @column_content(u)
        def rgba_sliders_col(u: ILoveUI):
            # single_component_rgba_color_selector(u, Ref(lambda: color_ref.value.r, lambda value: color_ref.set(dataclasses.replace(color_ref.value, r=value)))).flex()
            # single_component_rgba_color_selector(u, Ref(lambda: color_ref.value.g, lambda value: color_ref.set(dataclasses.replace(color_ref.value, g=value)))).flex()
            # single_component_rgba_color_selector(u, Ref(lambda: color_ref.value.b, lambda value: color_ref.set(dataclasses.replace(color_ref.value, b=value)))).flex()
            # single_component_rgba_color_selector(u, Ref(lambda: color_ref.value.a, lambda value: color_ref.set(dataclasses.replace(color_ref.value, a=value)))).flex()

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

# ==================== renderer ====================

class PygameILoveUIRenderer(Renderer):
    def __init__(
        self,
        screen_surface: pygame.Surface,
        font: pygame.font.Font | None = None,
        init_pygame_font: bool = True
    ) -> None:
        super().__init__()
        self.screen_surface = screen_surface
        self.buffer_surface = pygame.Surface(screen_surface.get_size(), pygame.SRCALPHA)

        if init_pygame_font:
            pygame.font.init()

        self.font = font if font is not None else pygame.font.SysFont(['Arial', 'SimHei'], 24)

        # 每个元素：(original_rect: Rect, effective_rect: Rect | None)
        # effective_rect = 上一层裁剪 ∩ 当前 push 的矩形（嵌套生效）
        self.scissor_stack: list[Rect] = []

    def _bilt_screen(self):
        self.screen_surface.blit(self.buffer_surface, (0, 0))
        self.buffer_surface.fill((0, 0, 0, 0))

    def _sync_buffer_size(self):
        bw, bh = self.buffer_surface.get_size()
        sw, sh = self.screen_surface.get_size()
        if bw < sw or bh < sh:
            self.buffer_surface = pygame.Surface((max(bw, sw), max(bh, sh)), pygame.SRCALPHA)

    @functools.lru_cache(maxsize=128)
    def _text_to_surface(self, s: str, color) -> pygame.Surface:
        return self.font.render(s, True, color)

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

    def draw_text(self, text_str: str, color: Color = Color(255, 255, 255)) -> Renderer.Renderable:
        text_surf = self._text_to_surface(text_str, color.to_tuple())
        min_width = text_surf.get_width()
        min_height = text_surf.get_height()

        def render(rect: Rect):
            surf = text_surf
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
        if for_render:
            self.screen_surface.set_clip(effective_rect.to_tuple() if effective_rect is not None else None)

    def pop_scissor(self) -> None:
        if not self.scissor_stack:
            raise IndexError("pop_scissor() called without matching push_scissor()")

        # 弹出栈顶
        self.scissor_stack.pop()

        # 恢复新的栈顶裁剪
        if self.scissor_stack:
            new_top_effective = self.scissor_stack[-1]
            self.screen_surface.set_clip(new_top_effective.to_tuple() if new_top_effective is not None else None)
        else:
            self.screen_surface.set_clip(None)

    @property
    def scissor_rect(self) -> Rect | None:
        return self.scissor_stack[-1] if self.scissor_stack else None

    def get_scissor_count(self) -> int:
        return len(self.scissor_stack)


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
    render_mask: bytearray = field(default_factory=lambda: bytearray(512))
    id: UIPath = field(default_factory=UIPath.root)

    def get_mask(self, required_count: int) -> bytearray:
        current_size = len(self.render_mask)
        if current_size >= required_count:
            return self.render_mask

        bytes_extend = b'\x00' * (required_count - current_size)
        self.render_mask.extend(bytes_extend)
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
                    if op.type == RenderOperateType.scissor_op:
                        return []
                    return [op]
                return exactly_mapper

            case RenderLayerMode.before:
                def before_mapper(lst: list[RenderOperate]) -> list[RenderOperate]:
                    return [e for i, e in enumerate(lst) if i <= self.layer or e.type == RenderOperateType.scissor_op]
                return before_mapper

            case RenderLayerMode.after:
                def after_mapper(lst: list[RenderOperate]) -> list[RenderOperate]:
                    return [e for i, e in enumerate(lst) if i >= self.layer or e.type == RenderOperateType.scissor_op]
                return after_mapper

            case RenderLayerMode.mask:
                def after_mapper(lst: list[RenderOperate]) -> list[RenderOperate]:
                    mask = self.get_mask(len(lst))
                    return [e for i, e in enumerate(lst) if mask[i] != 0 or e.type == RenderOperateType.scissor_op]
                return after_mapper

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
                .tag(u, f'layer: {layer}  ', with_spacing=False, min_size=100) \
                .tag_right(u, f'  max: {max_layer}', min_size=100) \
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
                .clickable(highlight, toggle_mode, check_scissor_rect=False)

            def flip_mask(_):
                for i, e in enumerate(state.render_mask):
                    state.render_mask[i] = 0 if e != 0 else 1

            text(u, 'flip mask') \
                .flex() \
                .clickable(highlight, flip_mask, check_scissor_rect=False)

        bitmap_ui(u, state.id / 'bitmap_ui', state.render_mask, total_bytes_count=max_layer) \
            .flex(1)

    return top_col \
        .square_expend()

@dataclass(slots=True)
class UIRendererUIState:
    single_step_mode: bool = False
    step: bool = False
    cached_render_tick_listeners: list[Callable[[], None]] | None = None

    def toggle_mode(self) -> None:
        self.single_step_mode = not self.single_step_mode

    def toggle_step(self) -> None:
        self.step = not self.step

def ui_renderer_ui(
    u: ILoveUI,
    state: UIRendererUIState,
    ui: Callable[[ILoveUI], None],
    map_render_tick_listeners: Callable[[list[RenderOperate]], list[RenderOperate]] | None = None,
    rect: Rect | None = None,
) -> Modifying:

    def place_component(ctx: PlaceContext) -> list[RenderOperate]:
        '''
        收集绘制指令到 list
        '''
        p = u.context.to_placeable(ui)
        render_tick_listeners: list[RenderOperate] = []
        p.place_fn(PlaceContext(rect if rect is not None else ctx.rect, ctx.context, render_tick_listeners))
        return render_tick_listeners

    def place_fn(ctx: PlaceContext):
        if not state.single_step_mode:
            lst = place_component(ctx)
            state.cached_render_tick_listeners = lst
        elif state.step:
            state.step = False
            lst = place_component(ctx)
            state.cached_render_tick_listeners = lst
        else:
            lst: list[RenderOperateType[Callable[[], None]]] = state.cached_render_tick_listeners # type: ignore

        ctx.deferred_render_tick_listeners += map_render_tick_listeners(lst) if map_render_tick_listeners is not None else lst

    return u.element(place_fn)


def debug_ui_rect_control_ui(u: ILoveUI, ui_rect_ref: Ref[Rect | None], show_rect_ref: Ref[bool]) -> Modifying:
    @row_content(u)
    def rect_control_row(u: ILoveUI):
        def get_rect() -> Rect:
            return ui_rect_ref.value if ui_rect_ref.value is not None else Rect(10, 10, 10, 10)

        def set_rect(value: Rect) -> None:
            ui_rect_ref.value = value

        rect_control_ui(u, Ref(get_rect, set_rect))

        def flip_show_rect(_):
            show_rect_ref.value = not show_rect_ref.value

        @column_content(u)
        def buttons_col(u: ILoveUI):
            text(u, 'show rect') \
                .background(green if show_rect_ref.value else gray) \
                .clickable(highlight, flip_show_rect)

            text(u, 'reset') \
                .background(gray) \
                .clickable(highlight, lambda _: ui_rect_ref.set(None))

        buttons_col.align_xy(None, 0.5)

    return rect_control_row

@dataclass(slots=True)
class FastStartContext:
    fps: float

def fast_debug(ui: Callable[[ILoveUI, FastStartContext], None]) -> None:
    render_layer_manager = RenderLayerManager()
    ui_renderer_ui_state = UIRendererUIState()
    color_ref = Ref.new_box(Color(0, 0, 0, 255))

    ui_rect: Rect | None = None
    show_rect: bool = True

    close_last_ui_rect_control_window: Callable[[], None] | None = None
    def open_ui_rect_control_window(u: ILoveUI):
        if close_last_ui_rect_control_window is not None:
            close_last_ui_rect_control_window()

        @window_content(u)
        def ui_rect_control_window(u: ILoveUI, ctx: PopupContext):
            nonlocal close_last_ui_rect_control_window
            close_last_ui_rect_control_window = ctx.close

            def set_rect(value: Rect | None) -> None:
                nonlocal ui_rect
                ui_rect = value
            def set_show_rect(value: bool) -> None:
                nonlocal show_rect
                show_rect = value
            debug_ui_rect_control_ui(u, Ref(lambda: ui_rect, set_rect), Ref(lambda: show_rect, set_show_rect))

    close_last_color_selector_window: Callable[[], None] | None = None
    def open_color_selector_window(u: ILoveUI):
        if close_last_color_selector_window is not None:
            close_last_color_selector_window()

        @window_content(u)
        def color_selector_window(u: ILoveUI, ctx: PopupContext):
            nonlocal close_last_color_selector_window
            close_last_color_selector_window = ctx.close

            rgba_color_selector(u, color_ref)

    close_last_render_layer_window: Callable[[], None] | None = None
    def open_render_layer_window(u: ILoveUI):
        if close_last_render_layer_window is not None:
            close_last_render_layer_window()

        @window_content(u)
        def render_layer_window(u: ILoveUI, ctx: PopupContext):
            nonlocal close_last_render_layer_window
            close_last_render_layer_window = ctx.close

            max_layer = len(ui_renderer_ui_state.cached_render_tick_listeners) if ui_renderer_ui_state.cached_render_tick_listeners is not None else 0

            render_layer_control_ui(u, max_layer, render_layer_manager)

    def fast_debug_ui(u: ILoveUI, ctx: FastStartContext) -> None:
        # todo 随意调节窗口大小 [v]
        # todo 暂停, 逐帧推进 [v]
        # todo 拦截所有事件并提供虚拟手指, 可以精确操控
        # todo 逐层渲染 [v]
        # todo 渲染剪刀区域

        popup_manager = u.context.remember(PopupManager, PopupManager)

        popup_manager.enabled = True
        popup_layer(u)
        popup_manager.enabled = False

        if show_rect and ui_rect is not None:
            spacing(u) \
                .background(highlight, touch_through=True) \
                .with_rect(ui_rect)

        @column_content(u)
        def top_column(u: ILoveUI):

            ui_renderer_ui(u, ui_renderer_ui_state, lambda u: ui(u, ctx), map_render_tick_listeners=render_layer_manager.render_mode_to_list_mapper(), rect=ui_rect) \
                .flex() \
                .scissor()

            @row_content(u)
            def control_row(u: ILoveUI):
                text(u, 'ui rect') \
                    .flex() \
                    .clickable(highlight, lambda _: open_ui_rect_control_window(u), check_scissor_rect=False)

                text(u, 'bg color') \
                    .flex() \
                    .clickable(highlight, lambda _: open_color_selector_window(u), check_scissor_rect=False)

                text(u, 'layer') \
                    .flex() \
                    .clickable(highlight, lambda _: open_render_layer_window(u), check_scissor_rect=False)

                text(u, 'single step' if ui_renderer_ui_state.single_step_mode else 'run') \
                    .flex() \
                    .clickable(highlight, lambda _: ui_renderer_ui_state.toggle_mode(), check_scissor_rect=False)

                text(u, 'stepping' if ui_renderer_ui_state.step else 'step') \
                    .flex() \
                    .clickable(highlight, lambda _: ui_renderer_ui_state.toggle_step(), check_scissor_rect=False)

        spacing(u) \
            .background(color_ref.value)

    fast_start(fast_debug_ui)

# ==================== fast start ====================

class FastStart:
    def __init__(self, ui: Callable[[ILoveUI, FastStartContext], None]) -> None:
        self.ui = ui

        # pygame初始化
        pygame.init()
        self.screen = pygame.display.set_mode((800, 800), pygame.SRCALPHA | pygame.RESIZABLE)
        self.screen_rect = Rect(0, 0, 800, 800)
        pygame.display.set_caption("ILoveUI")
        self.clock = pygame.time.Clock()
        self.running = True

        self.renderer = PygameILoveUIRenderer(self.screen)
        ctx = ILoveUIContext(self.renderer)
        ctx.fingers.append(Finger(0, 0))
        self.ctx = ctx

    def tick(self) -> None:
        if not self.running:
            return
        ctx = self.ctx

        # 事件处理
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False

            elif e.type == pygame.VIDEORESIZE:
                self.screen_rect = Rect(0, 0, e.size[0], e.size[1])

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
                    if finger.drag_listener is not None:
                        finger.drag_listener(finger)

            elif e.type == pygame.MOUSEBUTTONUP:
                if len(ctx.fingers) > 0:
                    finger = ctx.fingers[0]
                    x, y = e.pos
                    finger.x = x
                    finger.y = y
                    finger.drag_listener = None
                    if finger.release_listener is not None:
                        finger.release_listener(finger)
                        finger.release_listener = None

            # 输入框打字
            elif e.type == pygame.KEYDOWN:
                ctx.event_manager.send_event(KeyEvent, KeyEvent(e.key, e.scancode, e.unicode, True))

            elif e.type == pygame.KEYUP:
                ctx.event_manager.send_event(KeyEvent, KeyEvent(e.key, e.scancode, e.unicode, False))

        # 清屏
        self.renderer.screen_surface.fill((40,40,40))

        ctx.event_manager.before_render()
        ctx.render_in(self.screen_rect, lambda u: self.ui(u, FastStartContext(self.clock.get_fps())))

        # 刷新屏幕
        pygame.display.flip()
        self.clock.tick(60)

    def quit(self) -> None:
        self.running = False

def fast_start(ui: Callable[[ILoveUI, FastStartContext], None]) -> None:
    s = FastStart(ui)

    while s.running:
        s.tick()

    pygame.quit()

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
        .background(Color(100, 100, 100, 255)) \
        .clickable(highlight, startAnimation) \
        .align_xy(state.align, None)

def sleep_button(u: ILoveUI, id: UIPath) -> Modifying:
    enable_sleep_ref = (id / 'toggle sleep btn').remember(lambda: [False])

    if enable_sleep_ref[0]:
        time.sleep(0.1) # 测试 render_time_text

    def toggle_enable_sleep(_):
        enable_sleep_ref[0] = not enable_sleep_ref[0]

    return text(u, 'sleep 0.1s') \
        .expend_xy(10, 0) \
        .background(Color(255, 40, 40) if enable_sleep_ref[0] else Color(80, 80, 80)) \
        .clickable(highlight, toggle_enable_sleep)

def hello_world_button(u: ILoveUI) -> Modifying:
    return text(u, 'hello world') \
        .expend_xy(10, 0) \
        .background(Color(100, 100, 100, 255)) \
        .clickable(highlight, lambda _: toast(u, 'hello'))

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

            @box_content(u)
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
            .background(Color(100, 100, 100, 255)) \
            .clickable(highlight, open_window)

        text(u, f'{open_window_count} * window') \
            .expend_xy(10, 0) \
            .background(Color(100, 100, 100, 255)) \
            .clickable(highlight, open_more_window)

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
            .background(Color(255, 80, 80) if fruit_index == selected_index.value else Color(80, 80, 255)) \
            .clickable(highlight, set_selected) \
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
            .background(Color(80, 80, 80)) \
            .clickable(highlight, lambda _: toast(u, f'element {i}')) \
            .align_xy(0, 0.5)

    @column_content(u)
    def elements_ui(u: ILoveUI):
        element_id = id / 'scroll_test_elements'
        for i in range(60):
            element_button(u, i, element_id / i)

    return elements_ui \
        .v_scroll(id / 'scroll_test') \
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
                .tag(u, 'Render Time: ') \

            text(u, f'{fps:.4f}') \
                .tag(u, 'fps: ')

            popup_manager = u.context.remember(PopupManager, PopupManager)

            text(u, f'{len(popup_manager.popups)}') \
                .tag(u, 'popup count: ')

            @row_content(u)
            def buttons_row(u: ILoveUI):
                sleep_button(u, test_ui_state.ui_root / 'sleep button')
                hello_world_button(u)
                open_window_button(u, test_ui_state.ui_root / 'open_window_button')

                checked = (test_ui_state.ui_root / 'checked').remember(lambda: Ref.new_box(False))
                checkbox(u, test_ui_state.ui_root / 'check_box', checked) \
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

            bitmap = (test_ui_state.ui_root / 'bitmap').remember(lambda: bytearray(100))
            bitmap_ui(u, test_ui_state.ui_root / 'bitmap_ui', bitmap) \
                .flex()

        top_column.flex()

    top_row \
        .animated_rect(test_ui_state.ui_root / 'top_column animate')

def main():
    fast_debug(lambda u, ctx: test_screen_content(u, ctx.fps))

if __name__ == '__main__':
    main()
