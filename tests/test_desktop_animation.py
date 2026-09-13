"""Deterministic animation and pointer tests without a GUI, service, or real clock."""

from types import SimpleNamespace

import pytest

from zhijing import desktop_animation
from zhijing.desktop_animation import PetAnimation
from zhijing.desktop_ui import DesktopAssistant


class FakeCanvas:
    def __init__(self):
        self.items = {}
        self.pending = {}
        self.cancelled = []
        self.timer_sequence = 0
        self.max_pending = 0
        self.calls = 0
        self.destroyed = False

    def _check_alive(self):
        assert not self.destroyed, "A callback touched the Canvas after destruction"
        self.calls += 1

    def _create(self, kind, coordinates, options):
        self._check_alive()
        identifier = len(self.items) + 1
        self.items[identifier] = {"kind": kind, "coords": coordinates, **options}
        return identifier

    def create_image(self, *coordinates, **options):
        return self._create("image", coordinates, options)

    def create_rectangle(self, *coordinates, **options):
        return self._create("rectangle", coordinates, options)

    def create_line(self, *coordinates, **options):
        return self._create("line", coordinates, options)

    def coords(self, identifier, *coordinates):
        self._check_alive()
        self.items[identifier]["coords"] = coordinates

    def itemconfigure(self, identifier, **options):
        self._check_alive()
        self.items[identifier].update(options)

    def after(self, delay, callback):
        self._check_alive()
        assert delay >= 20, "The mascot must not create a busy polling loop"
        self.timer_sequence += 1
        identifier = f"after-{self.timer_sequence}"
        self.pending[identifier] = callback
        self.max_pending = max(self.max_pending, len(self.pending))
        return identifier

    def after_cancel(self, identifier):
        self._check_alive()
        assert identifier in self.pending
        self.pending.pop(identifier)
        self.cancelled.append(identifier)

    def run_frame(self):
        assert len(self.pending) == 1
        identifier = next(iter(self.pending))
        callback = self.pending.pop(identifier)
        callback()

    @property
    def body_position(self):
        return next(item["coords"] for item in self.items.values() if item["kind"] == "image")


@pytest.fixture
def animated(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(desktop_animation.time, "monotonic", lambda: clock.now)
    canvas = FakeCanvas()
    animation = PetAnimation(canvas, object())
    return animation, canvas, clock


def test_idle_frames_keep_one_timer_and_fixed_canvas_items(animated):
    animation, canvas, clock = animated
    original_items = set(canvas.items)
    positions = []
    blink_states = set()
    for frame in range(1, 401):
        clock.now = frame * 0.05
        canvas.run_frame()
        x, y = canvas.body_position
        assert x == 36
        assert abs(y - 36) <= 1.4 + 1e-9
        positions.append(y)
        eyelid = next(item for item in canvas.items.values() if item["kind"] == "rectangle")
        blink_states.add(eyelid["state"])
        assert eyelid["coords"][1] - y == pytest.approx(-20)
        assert set(canvas.items) == original_items
        assert len(canvas.pending) == 1
    assert max(positions) - min(positions) > 2
    assert blink_states == {"normal", "hidden"}
    assert canvas.max_pending == 1
    animation.close()


def test_hold_freezes_pose_and_release_resumes_one_timer(animated):
    animation, canvas, clock = animated
    clock.now = 0.8
    canvas.run_frame()
    pose = canvas.body_position
    animation.hover(True)
    animation.hold()
    animation.hold()
    assert canvas.body_position == pose
    assert not canvas.pending
    assert len(canvas.cancelled) == 1
    animation.hover(False)
    animation.hover(True)
    assert canvas.body_position == pose
    clock.now = 8
    animation.release()
    animation.release()
    assert len(canvas.pending) == 1
    clock.now += 0.05
    canvas.run_frame()
    assert abs(canvas.body_position[1] - 36) <= 1.4
    assert canvas.max_pending == 1
    animation.close()


def test_disabled_animation_stays_still_through_click_hover_and_release(animated):
    animation, canvas, clock = animated
    animation.set_enabled(False)
    assert canvas.body_position == (36, 36)
    assert not canvas.pending
    animation.hover(True)
    animation.hold()
    animation.release(clicked=True)
    assert not canvas.pending
    assert canvas.body_position == (36, 36)
    assert all(
        item.get("state") == "hidden" for item in canvas.items.values() if item["kind"] != "image"
    )
    animation.set_enabled(True)
    animation.set_enabled(True)
    assert len(canvas.pending) == 1
    clock.now = 0.2
    canvas.run_frame()
    assert canvas.max_pending == 1
    animation.close()


def test_click_feedback_is_bounded_and_returns_to_idle(animated):
    animation, canvas, clock = animated
    animation.hold()
    animation.release(clicked=True)
    positions = []
    for moment in (0.1, 0.225, 0.35, 0.46, 0.7):
        clock.now = moment
        canvas.run_frame()
        x, y = canvas.body_position
        positions.append(y)
        assert x == 36
        # The unscaled 64px image must stay inside its 72px Canvas.
        assert 0 <= y - 32 < y + 32 <= 72
        assert len(canvas.pending) == 1
    assert min(positions) < 34
    assert abs(positions[-1] - 36) <= 1.4
    animation.close()


def test_close_cancels_once_and_stale_callback_cannot_touch_destroyed_canvas(animated):
    animation, canvas, _ = animated
    stale_callback = next(iter(canvas.pending.values()))
    animation.close()
    assert not canvas.pending
    assert len(canvas.cancelled) == 1
    canvas.destroyed = True
    calls = canvas.calls
    stale_callback()
    animation.hold()
    animation.release(clicked=True)
    animation.hover(True)
    animation.set_enabled(True)
    animation.close()
    assert canvas.calls == calls
    assert not canvas.pending


def make_assistant(animation, canvas):
    assistant = DesktopAssistant.__new__(DesktopAssistant)
    activity = {"opens": 0, "shutdowns": 0, "destroyed": 0, "geometry": []}

    def increment(name):
        activity[name] += 1

    def destroy():
        assert not canvas.pending, "Animation must stop before destroying the root"
        increment("destroyed")
        canvas.destroyed = True
        assistant._on_destroy(SimpleNamespace(widget=assistant.root))

    assistant.root = SimpleNamespace(
        winfo_x=lambda: 100,
        winfo_y=lambda: 120,
        geometry=activity["geometry"].append,
        destroy=destroy,
    )
    assistant.animation = animation
    assistant.panel = SimpleNamespace(shutdown=lambda: increment("shutdowns"))
    assistant.toggle_chat = lambda: increment("opens")
    assistant._screen_bounds = lambda: (0, 0, 1000, 800)
    assistant.ball_size = 72
    assistant._closed = False
    assistant._drag = None
    assistant._dragged = False
    return assistant, activity


def test_small_pointer_motion_is_one_click_and_stray_release_does_not_open(animated):
    animation, canvas, _ = animated
    assistant, activity = make_assistant(animation, canvas)
    assistant._on_ball_press(SimpleNamespace(x_root=120, y_root=140))
    assert not canvas.pending
    assistant._on_ball_drag(SimpleNamespace(x_root=121, y_root=141))
    assistant._on_ball_release(None)
    assert activity["opens"] == 1
    assert not activity["geometry"]
    assert len(canvas.pending) == 1
    assistant._on_ball_release(None)
    assert activity["opens"] == 1
    assert canvas.max_pending == 1
    assistant.close()


def test_drag_returning_to_start_does_not_open_and_stays_inside_screen(animated):
    animation, canvas, _ = animated
    assistant, activity = make_assistant(animation, canvas)
    assistant._on_ball_press(SimpleNamespace(x_root=120, y_root=140))
    assistant._on_ball_drag(SimpleNamespace(x_root=125, y_root=140))
    assert assistant._dragged
    assistant._on_ball_drag(SimpleNamespace(x_root=3000, y_root=3000))
    assert activity["geometry"][-1] == "72x72+928+728"
    assistant._on_ball_drag(SimpleNamespace(x_root=120, y_root=140))
    assert not canvas.pending
    assistant._on_ball_release(None)
    assert activity["opens"] == 0
    assert len(canvas.pending) == 1
    assistant.close()


@pytest.mark.parametrize("external_destroy", [False, True])
def test_assistant_exit_and_root_destroy_cancel_animation_idempotently(animated, external_destroy):
    animation, canvas, _ = animated
    assistant, activity = make_assistant(animation, canvas)
    callback = next(iter(canvas.pending.values()))
    assistant._on_destroy(SimpleNamespace(widget=object()))
    assert len(canvas.pending) == 1, "A child widget destruction must not close the assistant"
    if external_destroy:
        assistant._on_destroy(SimpleNamespace(widget=assistant.root))
        canvas.destroyed = True
    else:
        assistant.close()
    assert not canvas.pending
    assert activity["shutdowns"] == 1
    assistant.close()
    assistant._on_destroy(SimpleNamespace(widget=assistant.root))
    callback()
    assert activity["shutdowns"] == 1
    assert len(canvas.cancelled) == 1


def test_context_menu_pauses_and_releases_animation_even_when_popup_fails(animated):
    animation, canvas, _ = animated
    assistant, activity = make_assistant(animation, canvas)
    released = []

    def popup(*_):
        assert not canvas.pending
        raise RuntimeError("synthetic popup failure")

    assistant.menu = SimpleNamespace(tk_popup=popup, grab_release=lambda: released.append(True))
    with pytest.raises(RuntimeError, match="synthetic popup failure"):
        assistant._show_menu(SimpleNamespace(x_root=120, y_root=140))
    assert released == [True]
    assert len(canvas.pending) == 1
    assert activity["opens"] == 0
    assistant.close()
