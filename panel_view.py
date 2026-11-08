"""The popover panel shown when the menu bar icon is clicked.

Draws the plain-data tabs from stats_tabs.py with AppKit: an icon tab bar,
rounded cards, big-number tiles, share bars, a line chart, and controls.
The whole view is rebuilt on each render, which keeps the code simple and
is cheap at this size.
"""

import time

import objc
from AppKit import (
    NSBezierPath,
    NSBox,
    NSBoxCustom,
    NSButton,
    NSColor,
    NSFont,
    NSFontWeightSemibold,
    NSGradient,
    NSImage,
    NSImageLeading,
    NSImageOnly,
    NSImageView,
    NSLineBreakByTruncatingMiddle,
    NSLineBreakByTruncatingTail,
    NSMakeRect,
    NSMinYEdge,
    NSPopover,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventMaskLeftMouseDown,
    NSEventMaskRightMouseDown,
    NSPopoverBehaviorApplicationDefined,
    NSPopUpButton,
    NSScreen,
    NSScrollView,
    NSSegmentDistributionFillEqually,
    NSSegmentedControl,
    NSSegmentSwitchTrackingSelectOne,
    NSSwitch,
    NSTextAlignmentCenter,
    NSTextAlignmentRight,
    NSTextField,
    NSView,
    NSViewController,
)
from Foundation import NSObject

from version import APP_NAME

WIDTH = 360
PAD = 12  # outer padding
CARD_PAD = 12  # padding inside a card
GAP = 10  # space between cards
CORNER = 10

HEIGHTS = {
    "tiles": 66,
    "chart": 84,
    "bar": 36,
    "row": 22,
    "note": 16,
    "buttons": 32,
    "segmented": 30,
    "popup": 30,
    "switch": 30,
    "alert": 17,
}
CARD_TITLE_HEIGHT = 24
SCREEN_MARGIN = 40  # keep the panel this far from the bottom of the screen


def panel_height(content_height, screen_height):
    """How tall the panel is: its content, capped so it fits on screen
    (anything beyond scrolls)."""
    return min(content_height, screen_height - SCREEN_MARGIN)


# --- small drawing helpers -------------------------------------------------


def _faint(alpha):
    return NSColor.labelColor().colorWithAlphaComponent_(alpha)


def _symbol(name, size=13, weight=0.0):
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    if image is None:
        return None
    from AppKit import NSImageSymbolConfiguration

    config = NSImageSymbolConfiguration.configurationWithPointSize_weight_(size, weight)
    return image.imageWithSymbolConfiguration_(config)


def _label(text, frame, size=13, weight=0.0, color=None, align=None, truncate="tail"):
    field = NSTextField.labelWithString_(text)
    field.setFont_(
        NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight)
        if align == "right"
        else NSFont.systemFontOfSize_weight_(size, weight)
    )
    field.setTextColor_(color or NSColor.labelColor())
    field.setFrame_(frame)
    if align == "right":
        field.setAlignment_(NSTextAlignmentRight)
    elif align == "center":
        field.setAlignment_(NSTextAlignmentCenter)
    field.cell().setLineBreakMode_(
        NSLineBreakByTruncatingMiddle if truncate == "middle" else NSLineBreakByTruncatingTail
    )
    return field


def _box(frame, fill, border=None, radius=CORNER):
    box = NSBox.alloc().initWithFrame_(frame)
    box.setBoxType_(NSBoxCustom)
    box.setTitlePosition_(0)  # NSNoTitle
    box.setFillColor_(fill)
    box.setBorderColor_(border or NSColor.clearColor())
    box.setBorderWidth_(1 if border else 0)
    box.setCornerRadius_(radius)
    box.setContentViewMargins_((0, 0))
    return box


class _FlippedView(NSView):
    def isFlipped(self):
        return True


class _BarView(NSView):
    """A rounded track with an accent-colored fill for a 0-1 fraction."""

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        bounds = self.bounds()
        h = bounds.size.height
        _faint(0.12).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bounds, h / 2, h / 2).fill()
        fraction = max(0.0, min(1.0, getattr(self, "fraction", 0.0)))
        if fraction <= 0:
            return
        width = max(h, bounds.size.width * fraction)
        fill = NSMakeRect(0, 0, width, h)
        NSColor.controlAccentColor().setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(fill, h / 2, h / 2).fill()


class _ChartView(NSView):
    """A line chart of `values` with a soft gradient underneath."""

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        values = getattr(self, "values", [])
        bounds = self.bounds()
        w, h = bounds.size.width, bounds.size.height

        # Dashed line marking the peak.
        dash = NSBezierPath.bezierPath()
        dash.moveToPoint_((0, 0.5))
        dash.lineToPoint_((w, 0.5))
        dash.setLineDash_count_phase_([3.0, 3.0], 2, 0)
        dash.setLineWidth_(1)
        _faint(0.25).setStroke()
        dash.stroke()

        if len(values) < 2:
            return
        peak = max(values) or 1
        step = w / (len(values) - 1)
        points = [(i * step, h - 2 - (v / peak) * (h - 4)) for i, v in enumerate(values)]

        line = NSBezierPath.bezierPath()
        line.moveToPoint_(points[0])
        for point in points[1:]:
            line.lineToPoint_(point)

        area = line.copy()
        area.lineToPoint_((w, h))
        area.lineToPoint_((0, h))
        area.closePath()
        accent = NSColor.controlAccentColor()
        gradient = NSGradient.alloc().initWithStartingColor_endingColor_(
            accent.colorWithAlphaComponent_(0.35), accent.colorWithAlphaComponent_(0.0)
        )
        gradient.drawInBezierPath_angle_(area, 90)

        line.setLineWidth_(1.5)
        line.setLineJoinStyle_(1)  # round
        accent.setStroke()
        line.stroke()


class _ActionTarget(NSObject):
    """Receives clicks from every control and forwards them to Python."""

    def initWithPanel_(self, panel):
        self = objc.super(_ActionTarget, self).init()
        if self is None:
            return None
        self.panel = panel
        return self

    def tabClicked_(self, sender):
        self.panel._select_tab(sender.tag())

    def buttonClicked_(self, sender):
        self.panel._fire(sender.tag(), None)

    def segmentChanged_(self, sender):
        self.panel._fire(sender.tag(), sender.selectedSegment())

    def popupChanged_(self, sender):
        self.panel._fire(sender.tag(), sender.indexOfSelectedItem())

    def switchChanged_(self, sender):
        self.panel._fire(sender.tag(), sender.state() == 1)

    def togglePanel_(self, sender):
        # Showing the popover while the status bar button is still handling
        # its click fails silently, so open it on the next run-loop pass.
        self.performSelector_withObject_afterDelay_("deferredToggle:", sender, 0.05)

    def deferredToggle_(self, sender):
        self.panel.toggle(sender)

    def retryShow_(self, _):
        self.panel._show(retries_left=getattr(self, "retries_left", 0))


# --- the panel ---------------------------------------------------------------


class Panel:
    """Owns the popover. Call render() with fresh data; clicks on controls
    call on_action(action, value) and on_tab_change(tab_key)."""

    def __init__(self, on_action, on_tab_change=None, selected_tab="overview"):
        self.on_action = on_action
        self.on_tab_change = on_tab_change
        self.selected = selected_tab
        self.tabs = []
        self.settings = None
        self.footer = ""
        self.paused = False
        self._actions = []
        self._target = _ActionTarget.alloc().initWithPanel_(self)

        self.root = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 400))
        # The content scrolls when it's taller than the screen allows.
        self.scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 400))
        self.scroll.setDocumentView_(self.root)
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setAutohidesScrollers_(True)
        self.scroll.setDrawsBackground_(False)
        controller = NSViewController.alloc().init()
        controller.setView_(self.scroll)
        self.popover = NSPopover.alloc().init()
        self.popover.setContentViewController_(controller)
        # Not NSPopoverBehaviorTransient: that closes the panel whenever this
        # background app isn't active, which macOS doesn't always allow it to
        # be. Outside clicks and Esc are handled with event monitors instead.
        self.popover.setBehavior_(NSPopoverBehaviorApplicationDefined)
        self.popover.setAnimates_(False)
        self._monitors = []
        self._last_toggle = 0.0

    # -- wiring

    def attach(self, status_item):
        """Make clicking the status item open this panel instead of a menu."""
        status_item.setMenu_(None)
        button = status_item.button()
        button.setTarget_(self._target)
        button.setAction_("togglePanel:")
        self._button = button

    def toggle(self, _sender=None):
        # One click on the status item can deliver the action twice; ignore
        # a second toggle that arrives right after the first.
        now = time.monotonic()
        if now - self._last_toggle < 0.3:
            return
        self._last_toggle = now
        if self.popover.isShown():
            self.close()
        else:
            self._show(retries_left=3)

    def _show(self, retries_left):
        from AppKit import NSApplication

        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.popover.showRelativeToRect_ofView_preferredEdge_(
            self._button.bounds(), self._button, NSMinYEdge
        )
        if self.popover.isShown():
            self._start_monitors()
        elif retries_left:
            # The status bar can still be busy with the click; try again shortly.
            self._target.retries_left = retries_left - 1
            self._target.performSelector_withObject_afterDelay_("retryShow:", None, 0.05)

    def show(self):
        """Open the panel if it isn't already open."""
        if getattr(self, "_button", None) is not None and not self.popover.isShown():
            self._show(retries_left=3)

    def close(self):
        self._stop_monitors()
        if self.popover.isShown():
            self.popover.close()

    def _start_monitors(self):
        self._stop_monitors()

        def outside_click(_event):
            # Global monitors only see clicks in other apps, so any click
            # here is outside the panel.
            self.close()

        def escape_key(event):
            if event.keyCode() == 53:  # Esc
                self.close()
                return None
            return event

        self._monitors = [
            NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown, outside_click
            ),
            NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, escape_key),
        ]

    def _stop_monitors(self):
        for monitor in self._monitors:
            if monitor is not None:
                NSEvent.removeMonitor_(monitor)
        self._monitors = []

    def is_shown(self):
        return bool(self.popover.isShown())

    # -- events

    def _select_tab(self, index):
        keys = [t["key"] for t in self.tabs]
        self.selected = keys[index] if index < len(keys) else "settings"
        if self.on_tab_change:
            self.on_tab_change(self.selected)
        self._draw()

    def _fire(self, tag, value):
        action = self._actions[tag]
        if action == "settings":
            self.selected = "overview" if self.selected == "settings" else "settings"
            self._draw()
            return
        self.on_action(action, value)

    def _register(self, action):
        self._actions.append(action)
        return len(self._actions) - 1

    # -- rendering

    def render(self, tabs, settings, footer, paused, tool_choices=None, selected_tool=None,
               welcome=None, subtitle="for Claude Code"):
        """`tool_choices` [(key, name)] adds a tool switcher when there are 2+;
        `welcome` (a tab) replaces everything with the first-run picker."""
        self.tabs = tabs
        self.settings = settings
        self.footer = footer
        self.paused = paused
        self.tool_choices = tool_choices or []
        self.selected_tool = selected_tool
        self.welcome = welcome
        self.subtitle = subtitle
        if self.selected not in [t["key"] for t in tabs] + ["settings"]:
            self.selected = tabs[0]["key"]
        self._draw()

    def _current_tab(self):
        if self.selected == "settings":
            return self.settings
        return next(t for t in self.tabs if t["key"] == self.selected)

    def _draw(self):
        if not self.tabs:
            return
        for view in list(self.root.subviews()):
            view.removeFromSuperview()
        self._actions = []
        inner = WIDTH - 2 * PAD

        y = PAD
        y = self._draw_header(y, inner)
        if self.welcome:
            self._draw_titled_cards(self.welcome, y, inner)
            return
        if len(self.tool_choices) >= 2:
            keys = [key for key, _ in self.tool_choices]
            selected = keys.index(self.selected_tool) if self.selected_tool in keys else 0
            self._draw_popup(
                ("popup", "Tracking", [name for _, name in self.tool_choices], selected, "select_tool"),
                PAD + 2, y - 4, inner - 4,
            )
            y += HEIGHTS["popup"] + 2
        y = self._draw_tab_bar(y, inner) + 12

        tab = self._current_tab()
        if self.selected == "settings":
            # Settings has no tab in the bar, so give it a visible title.
            self.root.addSubview_(
                _label(tab["title"], NSMakeRect(PAD + 2, y, inner, 20), size=15,
                       weight=NSFontWeightSemibold)
            )
            y += 28
        for card in tab["cards"]:
            y = self._draw_card(card, y, inner) + GAP

        y = self._draw_footer(y, inner)
        self._set_height(y + PAD)

    def _set_height(self, height):
        self.root.setFrameSize_((WIDTH, height))
        screen = NSScreen.mainScreen()
        screen_height = screen.visibleFrame().size.height if screen else height + SCREEN_MARGIN
        self.popover.setContentSize_((WIDTH, panel_height(height, screen_height)))

    def _draw_titled_cards(self, tab, y, inner):
        """A tab drawn on its own, under a title (the first-run picker)."""
        self.root.addSubview_(
            _label(tab["title"], NSMakeRect(PAD + 2, y + 4, inner, 20), size=15,
                   weight=NSFontWeightSemibold)
        )
        y += 32
        for card in tab["cards"]:
            y = self._draw_card(card, y, inner) + GAP
        self._set_height(y + PAD)

    def _draw_header(self, y, inner):
        self.root.addSubview_(_label("🪙", NSMakeRect(PAD, y + 2, 28, 28), size=22))
        self.root.addSubview_(
            _label(APP_NAME, NSMakeRect(PAD + 34, y, 200, 18),
                   size=14, weight=NSFontWeightSemibold)
        )
        self.root.addSubview_(
            _label(getattr(self, "subtitle", "for Claude Code"), NSMakeRect(PAD + 34, y + 17, 220, 15), size=11,
                   color=NSColor.secondaryLabelColor())
        )
        if self.paused:
            pill = _box(NSMakeRect(PAD + inner - 64, y + 6, 64, 20),
                        NSColor.systemOrangeColor().colorWithAlphaComponent_(0.18), radius=10)
            self.root.addSubview_(pill)
            self.root.addSubview_(
                _label("Paused", NSMakeRect(PAD + inner - 64, y + 8, 64, 16), size=11,
                       weight=NSFontWeightSemibold, color=NSColor.systemOrangeColor(),
                       align="center")
            )
        return y + 42

    def _draw_tab_bar(self, y, inner):
        height = 44
        count = len(self.tabs)
        slot = inner / count
        for index, tab in enumerate(self.tabs):
            x = PAD + index * slot
            selected = tab["key"] == self.selected
            tint = NSColor.controlAccentColor() if selected else NSColor.secondaryLabelColor()
            button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, slot, 26))
            button.setBordered_(False)
            button.setImage_(_symbol(tab["icon"], 16, NSFontWeightSemibold if selected else 0.0))
            button.setImagePosition_(NSImageOnly)
            button.setContentTintColor_(tint)
            button.setToolTip_(tab["title"])
            button.setTag_(index)
            button.setTarget_(self._target)
            button.setAction_("tabClicked:")
            self.root.addSubview_(button)
            caption = _label(tab["short"], NSMakeRect(x, y + 26, slot, 13), size=9,
                             weight=NSFontWeightSemibold if selected else 0.0,
                             color=tint, align="center")
            self.root.addSubview_(caption)
            if selected:
                underline = _box(NSMakeRect(x + slot * 0.25, y + height - 3, slot * 0.5, 3),
                                 NSColor.controlAccentColor(), radius=1.5)
                self.root.addSubview_(underline)
            # An invisible button over the whole tab (icon, caption and the
            # space around them), so clicking anywhere on it switches tabs.
            hit_area = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, slot, height))
            hit_area.setTransparent_(True)
            hit_area.setToolTip_(tab["title"])
            hit_area.setTag_(index)
            hit_area.setTarget_(self._target)
            hit_area.setAction_("tabClicked:")
            self.root.addSubview_(hit_area)
        hairline = _box(NSMakeRect(PAD, y + height, inner, 1), _faint(0.1), radius=0)
        self.root.addSubview_(hairline)
        return y + height + 1

    def _card_height(self, card):
        height = CARD_PAD * 2
        if card["title"]:
            height += CARD_TITLE_HEIGHT
        height += sum(HEIGHTS[item[0]] for item in card["items"])
        return height

    def _draw_card(self, card, y, inner):
        if not card["title"] and [item[0] for item in card["items"]] == ["tiles"]:
            # Tiles are already boxes; skip the card around them.
            self._draw_tiles(card["items"][0], PAD, y, inner)
            return y + 58
        height = self._card_height(card)
        self.root.addSubview_(_box(NSMakeRect(PAD, y, inner, height), _faint(0.05), _faint(0.08)))
        x = PAD + CARD_PAD
        width = inner - 2 * CARD_PAD
        cy = y + CARD_PAD
        if card["title"]:
            self.root.addSubview_(
                _label(card["title"], NSMakeRect(x, cy, width, 18), size=13,
                       weight=NSFontWeightSemibold, color=NSColor.secondaryLabelColor())
            )
            cy += CARD_TITLE_HEIGHT
        for item in card["items"]:
            getattr(self, f"_draw_{item[0]}")(item, x, cy, width)
            cy += HEIGHTS[item[0]]
        return y + height

    # -- items

    def _draw_tiles(self, item, x, y, width):
        tiles = item[1]
        gap = 8
        tile_width = (width - gap * (len(tiles) - 1)) / len(tiles)
        for index, (label, value, icon) in enumerate(tiles):
            tx = x + index * (tile_width + gap)
            self.root.addSubview_(_box(NSMakeRect(tx, y, tile_width, 58), _faint(0.06), radius=8))
            text_x = tx + 10
            if icon:
                image_view = NSImageView.imageViewWithImage_(_symbol(icon, 11, NSFontWeightSemibold))
                image_view.setContentTintColor_(NSColor.controlAccentColor())
                image_view.setFrame_(NSMakeRect(tx + 10, y + 9, 14, 14))
                self.root.addSubview_(image_view)
                text_x += 18
            self.root.addSubview_(
                _label(label, NSMakeRect(text_x, y + 8, tile_width - (text_x - tx) - 8, 16),
                       size=11, color=NSColor.secondaryLabelColor())
            )
            value_field = _label(value, NSMakeRect(tx + 10, y + 26, tile_width - 20, 26))
            value_field.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(21, NSFontWeightSemibold))
            self.root.addSubview_(value_field)

    def _draw_chart(self, item, x, y, width):
        _, values, caption = item
        self.root.addSubview_(
            _label(caption, NSMakeRect(x, y, width, 14), size=10, color=NSColor.secondaryLabelColor())
        )
        chart = _ChartView.alloc().initWithFrame_(NSMakeRect(x, y + 18, width, 58))
        chart.values = list(values)
        self.root.addSubview_(chart)

    def _draw_bar(self, item, x, y, width):
        _, label, value, fraction = item
        self.root.addSubview_(
            _label(label, NSMakeRect(x, y, width - 120, 18), truncate="middle")
        )
        self.root.addSubview_(
            _label(value, NSMakeRect(x + width - 120, y, 120, 18), align="right",
                   color=NSColor.secondaryLabelColor())
        )
        bar = _BarView.alloc().initWithFrame_(NSMakeRect(x, y + 21, width, 6))
        bar.fraction = fraction
        self.root.addSubview_(bar)

    def _draw_row(self, item, x, y, width):
        _, label, value = item
        self.root.addSubview_(_label(label, NSMakeRect(x, y + 2, width - 110, 18), truncate="middle"))
        self.root.addSubview_(
            _label(value, NSMakeRect(x + width - 110, y + 2, 110, 18), align="right",
                   weight=NSFontWeightSemibold)
        )

    def _draw_alert(self, item, x, y, width):
        """One line of a warning, in orange; the first line gets an icon."""
        _, text, show_icon = item
        if show_icon:
            icon = NSImageView.imageViewWithImage_(_symbol("exclamationmark.triangle.fill", 12))
            icon.setContentTintColor_(NSColor.systemOrangeColor())
            icon.setFrame_(NSMakeRect(x, y + 1, 16, 15))
            self.root.addSubview_(icon)
        self.root.addSubview_(
            _label(text, NSMakeRect(x + 22, y, width - 22, 16), size=12,
                   weight=NSFontWeightSemibold, color=NSColor.systemOrangeColor())
        )

    def _draw_note(self, item, x, y, width):
        self.root.addSubview_(
            _label(item[1], NSMakeRect(x, y + 1, width, 14), size=11,
                   color=NSColor.secondaryLabelColor())
        )

    def _draw_buttons(self, item, x, y, width):
        buttons = item[1]
        gap = 8
        button_width = (width - gap * (len(buttons) - 1)) / len(buttons)
        for index, (title, icon, action) in enumerate(buttons):
            button = NSButton.buttonWithTitle_target_action_(title, self._target, "buttonClicked:")
            if icon:
                button.setImage_(_symbol(icon, 12))
                button.setImagePosition_(NSImageLeading)
            button.setFrame_(NSMakeRect(x + index * (button_width + gap), y, button_width, 26))
            button.setTag_(self._register(action))
            self.root.addSubview_(button)

    def _control_label(self, label, x, y, width):
        if label:
            self.root.addSubview_(_label(label, NSMakeRect(x, y + 5, width, 18)))

    def _draw_segmented(self, item, x, y, width):
        _, label, options, selected, action = item
        self._control_label(label, x, y, width)
        control_x = x + (90 if label else 0)
        control = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            options, NSSegmentSwitchTrackingSelectOne, self._target, "segmentChanged:"
        )
        control.setSegmentDistribution_(NSSegmentDistributionFillEqually)
        control.setFrame_(NSMakeRect(control_x, y + 2, x + width - control_x, 24))
        control.setSelectedSegment_(selected)
        control.setTag_(self._register(action))
        self.root.addSubview_(control)

    def _draw_popup(self, item, x, y, width):
        _, label, options, selected, action = item
        self._control_label(label, x, y, width)
        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(x + width - 140, y + 1, 140, 26), False
        )
        popup.addItemsWithTitles_(options)
        popup.selectItemAtIndex_(selected)
        popup.setTarget_(self._target)
        popup.setAction_("popupChanged:")
        popup.setTag_(self._register(action))
        self.root.addSubview_(popup)

    def _draw_switch(self, item, x, y, width):
        _, label, is_on, action = item
        self._control_label(label, x, y, width)
        switch = NSSwitch.alloc().initWithFrame_(NSMakeRect(x + width - 40, y + 3, 40, 22))
        switch.setControlSize_(1)  # small
        switch.setState_(1 if is_on else 0)
        switch.setTarget_(self._target)
        switch.setAction_("switchChanged:")
        switch.setTag_(self._register(action))
        self.root.addSubview_(switch)

    # -- footer

    def _draw_footer(self, y, inner):
        self.root.addSubview_(_box(NSMakeRect(PAD, y, inner, 1), _faint(0.1), radius=0))
        y += 9
        calendar = NSImageView.imageViewWithImage_(_symbol("calendar", 11))
        calendar.setContentTintColor_(NSColor.secondaryLabelColor())
        calendar.setFrame_(NSMakeRect(PAD + 2, y + 5, 14, 14))
        self.root.addSubview_(calendar)
        self.root.addSubview_(
            _label(self.footer, NSMakeRect(PAD + 20, y + 4, inner - 90, 16), size=11,
                   color=NSColor.secondaryLabelColor())
        )
        settings_open = self.selected == "settings"
        icons = (
            ("checkmark.circle" if settings_open else "slider.horizontal.3",
             "Done" if settings_open else "Settings", "settings"),
            ("xmark.circle", "Quit", "quit"),
        )
        for index, (icon, tip, action) in enumerate(icons):
            button = NSButton.alloc().initWithFrame_(
                NSMakeRect(PAD + inner - 30 * (len(icons) - index), y, 28, 24)
            )
            button.setBezelStyle_(15)  # NSBezelStyleAccessoryBarAction: subtle rounded
            button.setImage_(_symbol(icon, 13))
            button.setImagePosition_(NSImageOnly)
            button.setContentTintColor_(
                NSColor.controlAccentColor() if action == "settings" and settings_open
                else NSColor.secondaryLabelColor()
            )
            button.setToolTip_(tip)
            button.setTarget_(self._target)
            button.setAction_("buttonClicked:")
            button.setTag_(self._register(action))
            self.root.addSubview_(button)
        return y + 24
