import functools
import pygame
import time

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Self, TypeVar

# ==================== events ====================

@dataclass
class Finger:
    """触摸/鼠标指针"""
    x: float
    y: float

    drag_listener: Callable[['Finger'], Any] | None = None
    release_listener: Callable[['Finger'], Any] | None = None

@dataclass
class NewFingerEvent:
    finger: Finger

@dataclass
class KeyEvent:
    keycode: int
    scancode: int
    unicode: str
    isDown: bool

# ==================== core ====================

@dataclass(frozen=True)
class Color:
    r: int
    g: int
    b: int
    a: int = 255

    def to_tuple(self) -> tuple[int, int, int, int]:
        return (self.r, self.g, self.b, self.a)

@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def sub_rect_with_align(self, new_w: float, new_h: float, align_x: float, align_y: float) -> 'Rect':
        x = self.x + (self.w - new_w) * align_x
        y = self.y + (self.h - new_h) * align_y
        return Rect(x, y, new_w, new_h)

    def sub_rect_with_offset(self, new_w: float, new_h: float, offset_x: float, offset_y: float) -> 'Rect':
        x = self.x + offset_x
        y = self.y + offset_y
        return Rect(x, y, new_w, new_h)

    def contains_point(self, px: float, py: float) -> bool:
        return (self.x <= px <= self.x + self.w and
                self.y <= py <= self.y + self.h)

class Renderer(ABC):
    @abstractmethod
    def fill_rect(self, rect: Rect, color: Color, line_width: float = 0) -> None: ...

    @dataclass
    class TextRenderer:
        min_width: float
        min_height: float
        render: Callable[[Rect], None]

    @abstractmethod
    def draw_text(self, text_str: str, color: Color = Color(255, 255, 255)) -> TextRenderer: ...

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

@dataclass
class PlaceContext:
    rect: Rect
    context: 'ILoveUIContext'
    deferred_render_tick: Callable[[Callable[[], None]], None]

@dataclass
class Placeable:
    min_width: float
    min_height: float
    place_fn: Callable[[PlaceContext], None]

@dataclass
class Modifying:
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
        def my_ui_style(m: Modifying):
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

    def background(self, color: Color, touch_through: bool = False) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            p.place_fn(ctx)

            if not touch_through:
                ctx.context.event_manager.consume_events(NewFingerEvent, lambda e: ctx.rect.contains_point(e.finger.x, e.finger.y))

            ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, color))

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def clickable(self, hover_color: Color | None, click_callback: Callable[[Finger], None]) -> Self:
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            def consume_new_finger_event(e: NewFingerEvent) -> bool:
                in_rect = ctx.rect.contains_point(e.finger.x, e.finger.y)
                if in_rect:
                    def release_listener(finger):
                        if ctx.rect.contains_point(finger.x, finger.y):
                            click_callback(finger)
                    e.finger.release_listener = release_listener
                return in_rect

            ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

            if hover_color is not None and any(ctx.rect.contains_point(finger.x, finger.y) for finger in ctx.context.fingers):
                ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, hover_color))

            p.place_fn(ctx)

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def clickable_background(self, background_color: Color, click_callback: Callable[[Finger], None]) -> Self:
        '''
        用于拦截落在背景而不是 ui 内容的点击,
        可以用来实现点击背景取消弹窗的效果
        '''
        p = self.placeable
        def place_fn(ctx: PlaceContext):
            p.place_fn(ctx)

            def consume_new_finger_event(e: NewFingerEvent) -> bool:
                in_rect = ctx.rect.contains_point(e.finger.x, e.finger.y)

                if in_rect:
                    def release_listener(finger):
                        if ctx.rect.contains_point(finger.x, finger.y):
                            click_callback(finger)
                    e.finger.release_listener = release_listener

                return in_rect

            ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

            ctx.deferred_render_tick(lambda: ctx.context.renderer.fill_rect(ctx.rect, background_color))

        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

    def expend(self, expend_x: float, expend_y: float) -> Self:
        p = self.placeable
        self.placeable = Placeable(p.min_width + expend_x, p.min_height + expend_y, p.place_fn)
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
            p.place_fn(PlaceContext(new_rect, ctx.context, ctx.deferred_render_tick))
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
            p.place_fn(PlaceContext(new_rect, ctx.context, ctx.deferred_render_tick))
        self.placeable = Placeable(p.min_width, p.min_height, place_fn)
        return self

T = TypeVar('T')

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

    def send(self, type: type[T], e: T) -> None:
        self.new_events.append((type, e))

    def consume_events(self, type: type[T], consume: Callable[[T], bool]) -> None:
        events = self.event_by_type.get(type)
        if events is None:
            return
        self.event_by_type[type] = [e for e in events if not consume(e)]

class ILoveUIContext:
    def __init__(self, renderer: Renderer) -> None:
        self.renderer = renderer
        self.event_manager = EventManager()
        self.fingers: list[Finger] = []
        self.instance_by_type: dict[type, Any] = {}

    def get(self, cls: type[T]) -> T | None:
        return self.instance_by_type.get(cls)

    def set(self, cls: type[T], value: T) -> None:
        self.instance_by_type[cls] = value

    def remember(self, cls: type[T], calc: Callable[[], T]) -> T:
        if cls in self.instance_by_type:
            return self.instance_by_type[cls]
        instance = calc()
        self.instance_by_type[cls] = instance
        return instance

    # ==================== fast start ====================

    def place_in(self, rect: Rect, place_fn: Callable[[PlaceContext], None]) -> None:
        render_tick_listeners: list[Callable[[], None]] = []
        place_ctx = PlaceContext(rect, self, render_tick_listeners.append)
        place_fn(place_ctx)
        for listener in reversed(render_tick_listeners):
            listener()

    def render_in(self, rect: Rect, content: Callable[['ILoveUI'], None]) -> None:
        u = ILoveUI(self)
        ui = box(u, content)
        self.place_in(rect, ui.placeable.place_fn)

class ILoveUI():
    '''
    立即模式 ui 库
    在主循环中调用 ILoveUIContext.render_in 来绘制 ui

    ui: 内部直接调用 ILoveUI.element 一次, 返回 Modifying 的函数
    ui_content: 内部直接调用 ILoveUI.element 任意次, 不返回 Modifying 的函数

    '''
    def __init__(self, context: ILoveUIContext) -> None:
        self.context = context
        self.children: list[Modifying] = []

    def element(self, place_fn: Callable[[PlaceContext], None], min_width: float = 10, min_height: float = 10) -> Modifying:
        placeable = Placeable(min_width=min_width, min_height=min_height, place_fn=place_fn)
        modifying = Modifying(placeable)
        self.children.append(modifying)
        return modifying

# ==================== popups ====================

@dataclass
class PopupContext:
    close: Callable[[], None]

class PopupManager:
    @dataclass
    class Popup:
        popup_content: Callable[[ILoveUI, PopupContext], Any]
        removed: bool = False

        def remove(self):
            self.removed = True

    def __init__(self) -> None:
        self.popup_contents: list[PopupManager.Popup] = []

    def add(self, popup_content: Callable[[ILoveUI, PopupContext], Any]) -> None:
        self.popup_contents.append(PopupManager.Popup(popup_content))

def popup_layer(u: ILoveUI):
    def ui_content(u: ILoveUI):
        popupManager = u.context.remember(PopupManager, PopupManager)
        for i in range(len(popupManager.popup_contents) - 1, -1, -1):
            popup_instance = popupManager.popup_contents[i]

            ctx = PopupContext(popup_instance.remove)
            popup_instance.popup_content(u, ctx)

            if popup_instance.removed:
                del popupManager.popup_contents[i]

    return box(u, ui_content)

def popup(u: ILoveUI, popup_content: Callable[[ILoveUI, PopupContext], Any]) -> None:
    popupManager = u.context.get(PopupManager)
    if popupManager is None:
        raise ValueError("must call 'popup_layer' before call 'popup'")
    popupManager.add(popup_content)

# ==================== toasts ====================

TOAST_DURATION_SECONDS = 2

@dataclass
class ToastState:
    create_time: float
    toast_str: str
    offset: float = 0

def toast_content(u: ILoveUI, state: ToastState, ctx: PopupContext) -> None:
    current_time = time.time()
    if current_time - state.create_time > TOAST_DURATION_SECONDS:
        ctx.close()

    t = text(u, state.toast_str)
    t.expend(20, 20)
    t.background(Color(0, 0, 0, 127))
    t.offset_xy(0, state.offset)
    state.offset -= 0.8
    t.align_xy(0.5, 0.85)

def toast(u: ILoveUI, s: str) -> None:
    create_time = time.time()
    state = ToastState(create_time, s)
    popup(u, lambda u, ctx: toast_content(u, state, ctx))

# ==================== base layout ====================

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

    return u.element(place_fn)

def row(u: ILoveUI, content: Callable[[ILoveUI], None], spacing: float = 4) -> Modifying:
    '''
    默认在交叉轴拉伸所有子元素
    可以通过指定子元素在交叉轴的 align 或 offset 的方式来避免
    '''
    return linear(u, horizontal=True, spacing=spacing, content=content)

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

        container_main_axis_size = ctx.rect.w if horizontal else ctx.rect.h

        def calc_flex_size(weight: int) -> float:
            return (container_main_axis_size - total_spacing - fixed_size) * weight / total_weight

        # 如果比例分配的大小不够, 转为固定大小
        for ui in child_u.children:
            if ui.flex_weight != 0:
                flex_size = calc_flex_size(ui.flex_weight)
                required_size = ui.placeable.min_width if horizontal else ui.placeable.min_height
                if flex_size < required_size:
                    fixed_size += required_size
                    total_weight -= ui.flex_weight
                    ui.flex_weight = 0

        base = ctx.rect.x if horizontal else ctx.rect.y
        for ui in child_u.children:

            if ui.flex_weight == 0:
                child_size = ui.placeable.min_width if horizontal else ui.placeable.min_height
            else:
                child_size = calc_flex_size(ui.flex_weight)

            child_rect = Rect(base, ctx.rect.y, child_size, ctx.rect.h) if horizontal else Rect(ctx.rect.x, base, ctx.rect.w, child_size)
            child_ctx = PlaceContext(child_rect, ctx.context, ctx.deferred_render_tick)
            ui.placeable.place_fn(child_ctx)
            base += child_size + spacing

    return u.element(place_fn, min_width=min_width, min_height=min_height)

# ==================== base widget ====================

def spacing(u: ILoveUI, width: float = 10, height: float = 10) -> Modifying:
    return u.element(lambda _: None, width, height)

def text(u: ILoveUI, s: str) -> Modifying:
    text_renderer = u.context.renderer.draw_text(s)

    def place_fn(ctx: PlaceContext):
        ctx.deferred_render_tick(lambda: text_renderer.render(ctx.rect))

    return u.element(
        place_fn=place_fn,
        min_width=text_renderer.min_width,
        min_height=text_renderer.min_height
    )

focused_input = None
last_blink = 0
blink_state = True

def text_field(u: ILoveUI, text_ref: list[str], placeholder: str = "type something...", ui_id: Any = None) -> Modifying:
    if ui_id is None:
        ui_id = id(text_ref)

    min_w = 200
    min_h = 36

    def place_fn(ctx: PlaceContext):
        global focused_input, last_blink, blink_state

        active = (focused_input == ui_id)

        def consume_new_finger_event(e: NewFingerEvent) -> bool:
            global focused_input
            in_rect = ctx.rect.contains_point(e.finger.x, e.finger.y)
            if in_rect:
                focused_input = ui_id
            elif active:
                focused_input = None
            return in_rect
        ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

        if active:
            def consume_key_event(e: KeyEvent) -> bool:
                if e.isDown and e.keycode == pygame.K_BACKSPACE:
                    text_ref[0] = text_ref[0][:-1]
                    return True
                elif e.isDown and e.unicode:
                    text_ref[0] += e.unicode
                    return True
                return False
            ctx.context.event_manager.consume_events(KeyEvent, consume_key_event)

            now = time.time()
            if now - last_blink > 0.5:
                blink_state = not blink_state
                last_blink = now

        def render():
            ctx.context.renderer.fill_rect(ctx.rect, Color(60, 60, 60))
            ctx.context.renderer.fill_rect(ctx.rect, Color(200, 200, 200), line_width = 2 if active else 1)

            s = text_ref[0]
            if not s and not active:
                textRenderer = ctx.context.renderer.draw_text(placeholder, color=Color(160, 160, 160))
            else:
                textRenderer = ctx.context.renderer.draw_text(s)

            r = ctx.rect
            textRenderer.render(Rect(r.x+8, r.y + (r.h-textRenderer.min_height)/2, textRenderer.min_width, textRenderer.min_height))

            if active and blink_state:
                cx = r.x + 8 + textRenderer.min_width + 2
                cy1 = r.y + 6
                cy2 = r.y + r.h -6
                ctx.context.renderer.draw_line(Color(255,255,255), (cx, cy1), (cx, cy2), 2)

        ctx.deferred_render_tick(render)

    return u.element(place_fn, min_w, min_h)

def slider(u: ILoveUI, value_ref: list[float], min_val: float, max_val: float) -> Modifying:
    min_w = 250
    min_h = 30

    def place_fn(ctx: PlaceContext):

        def consume_new_finger_event(e: NewFingerEvent) -> bool:
            in_rect = ctx.rect.contains_point(e.finger.x, e.finger.y)

            def handle_finger(finger):
                t = max(0.0, min(1.0, (finger.x - ctx.rect.x) / ctx.rect.w))
                value_ref[0] = min_val + t * (max_val - min_val)

            if in_rect:
                handle_finger(e.finger)
                e.finger.drag_listener = handle_finger

            return in_rect
        ctx.context.event_manager.consume_events(NewFingerEvent, consume_new_finger_event)

        def render():
            r = ctx.rect
            yh = r.h / 3

            ctx.context.renderer.fill_rect(Rect(r.x, r.y + yh, r.w, yh), Color(80, 80, 80))
            t = (value_ref[0] - min_val) / (max_val - min_val) if max_val != min_val else 0
            fill_w = r.w * t
            ctx.context.renderer.fill_rect(Rect(r.x, r.y + yh, fill_w, yh), Color(100,200,100))

            cr = r.h * 0.4
            cx = r.x + fill_w
            cy = r.y + r.h/2
            ctx.context.renderer.fill_circle(cx, cy, cr, Color(255,255,255))

        ctx.deferred_render_tick(render)

    return u.element(place_fn, min_w, min_h)

highlight = Color(255, 255, 255, 127)

def dialog(
    u: ILoveUI,
    text_str: str,
    yes_or_no: Callable[[bool], None],
    cancel: Callable[[], bool]
) -> None:
    def ui_content(u: ILoveUI, ctx: PopupContext):
        def top_content(u: ILoveUI):

            text(u, text_str) \
                .flex()

            def yes_or_no_content(u: ILoveUI):

                def chosen(value: bool):
                    yes_or_no(value)
                    ctx.close()

                text(u, 'yes') \
                    .flex() \
                    .clickable(highlight, lambda _: chosen(True))

                text(u, 'no') \
                    .flex() \
                    .clickable(highlight, lambda _: chosen(False))

            row(u, yes_or_no_content)

        column(u, top_content) \
            .expend(20, 20) \
            .background(Color(80, 80, 80)) \
            .align_xy(0.5, 0.5) \
            .clickable_background(Color(0, 0, 0, 80), lambda _: ctx.close())
    popup(u, ui_content)

# ==================== test ====================

class PygameILoveUIRenderer(Renderer):
    def __init__(
        self,
        screen_surface: pygame.Surface,
        font: pygame.font.Font | None = None,
        init_pygame_font: bool = True
    ) -> None:
        super().__init__()
        self.screen_surface = screen_surface
        if init_pygame_font:
            pygame.font.init()
        self.font = font if font is not None else pygame.font.SysFont(None, 24)

    @functools.lru_cache(maxsize=128)
    def text_to_surface(self, s: str, color) -> pygame.Surface:
        return self.font.render(s, True, color)

    def fill_rect(self, rect: Rect, color: Color, line_width: float = 0) -> None:
        color_tuple = color.to_tuple()
        pygame.draw.rect(
            self.screen_surface,
            color_tuple,
            (rect.x, rect.y, rect.w, rect.h),
            width=int(line_width)
        )

    def draw_text(self, text_str: str, color: Color = Color(255, 255, 255)) -> Renderer.TextRenderer:
        text_surf = self.text_to_surface(text_str, color.to_tuple())
        min_width = text_surf.get_width()
        min_height = text_surf.get_height()
        def render(rect: Rect):
            surf = text_surf
            # 文本居中绘制
            blit_x = rect.x + (rect.w - surf.get_width()) / 2
            blit_y = rect.y + (rect.h - surf.get_height()) / 2
            self.screen_surface.blit(surf, (blit_x, blit_y))
        return Renderer.TextRenderer(min_width, min_height, render)

    def draw_line(self, color: Color, start_pos: tuple[float, float], end_pos: tuple[float, float], width: int = 1) -> None:
        pygame.draw.line(self.screen_surface, color.to_tuple(), start_pos, end_pos, width)

    def fill_circle(self, x: float, y: float, radius: float, color: Color) -> None:
        pygame.draw.circle(self.screen_surface, color.to_tuple(), (x, y), radius)

# ==================== test ====================

@dataclass
class TestUIState:
    fruits: list[str] = field(default_factory=lambda: ['apple', 'banana', 'watermelon', 'pear', 'cherry'])
    selected: int = 0
    input_text: list[str] = field(default_factory=lambda: [""])
    slider_val: list[float] = field(default_factory=lambda: [50.0])

def test_screen(ctx: ILoveUIContext):
    testUIState = ctx.remember(TestUIState, TestUIState)

    def screen_content(u):
        popup_layer(u)

        def top_ui_content(u):
            text(u, 'hello world') \
                .expend(0, 20) \
                .background(Color(100, 100, 100, 255)) \
                .clickable(highlight, lambda _: toast(u, 'hello')) \
                .align_xy(0.5, 0.5)

            text(u, testUIState.fruits[testUIState.selected]) \
                .flex() \
                .background(Color(80, 255, 80))

            def fruits_ui_content(u):
                def fruit_ui(u, fruit_index, fruit):
                    def set_selected(_):
                        toast(u, fruit)
                        testUIState.selected = fruit_index

                    return text(u, fruit) \
                        .background(Color(255, 80, 80) if fruit_index == testUIState.selected else Color(80, 80, 255)) \
                        .clickable(highlight, set_selected) \
                        .flex()

                for index, fruit in enumerate(testUIState.fruits):
                    fruit_ui(u, index, fruit)

            row(u, fruits_ui_content) \
                .expend(0, 40)

            spacing(u, 0, 20)

            # 文本输入框
            text(u, "text field: ")
            text_field(u, testUIState.input_text)

            spacing(u, 0, 10)

            # 数字滑块
            text(u, f"value: {testUIState.slider_val[0]:.0f}")
            slider(u, testUIState.slider_val, 0, 100)

            def dialog_cancelled() -> bool:
                toast(u, 'cancelled')
                return True

            def open_dialog(_):
                dialog(u, 'test dialog', lambda yes_or_no: toast(u, f'you chosen {yes_or_no}'), dialog_cancelled)

            text(u, 'dialog') \
                .clickable(highlight, open_dialog)
        column(u, top_ui_content)

    ctx.render_in(Rect(0, 0, 800, 600), screen_content)

def main():
    # pygame初始化
    pygame.init()
    screen = pygame.display.set_mode((800, 600), pygame.SRCALPHA)
    pygame.display.set_caption("ILoveUI")
    clock = pygame.time.Clock()
    running = True

    ctx = ILoveUIContext(PygameILoveUIRenderer(screen))
    ctx.fingers.append(Finger(0, 0))

    while running:
        # 事件处理
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                running = False

            elif e.type == pygame.MOUSEBUTTONDOWN:
                x, y = e.pos
                finger = Finger(x, y)
                if len(ctx.fingers) > 0:
                    ctx.fingers[0] = finger
                else:
                    ctx.fingers.append(finger)
                ctx.event_manager.send(NewFingerEvent, NewFingerEvent(finger))

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
                ctx.event_manager.send(KeyEvent, KeyEvent(e.key, e.scancode, e.unicode, True))

            elif e.type == pygame.KEYUP:
                ctx.event_manager.send(KeyEvent, KeyEvent(e.key, e.scancode, e.unicode, False))

        # 清屏
        screen.fill((40,40,40))

        ctx.event_manager.before_render()
        test_screen(ctx)

        # 刷新屏幕
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == '__main__':
    main()
