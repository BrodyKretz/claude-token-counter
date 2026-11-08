"""A tabbed stats panel embedded in the menu as a single menu item.

A segmented control along the top switches tabs in place, so the menu stays
open while you flip between them. Content comes from stats_tabs.build_tabs().
"""

import objc
from AppKit import (
    NSColor,
    NSFont,
    NSLineBreakByTruncatingMiddle,
    NSMakeRect,
    NSMenuItem,
    NSSegmentDistributionFillEqually,
    NSSegmentedControl,
    NSSegmentSwitchTrackingSelectOne,
    NSTextAlignmentRight,
    NSTextField,
    NSView,
)
from Foundation import NSObject

WIDTH = 380
PAD_X = 14
PAD_Y = 8
TABS_HEIGHT = 24
VALUE_WIDTH = 120
ROW_HEIGHTS = {"heading": 20, "row": 19, "note": 16, "gap": 8}


class _FlippedView(NSView):
    """NSView whose y axis runs top-down, so rows can be laid out in order."""

    def isFlipped(self):
        return True


class _TabTarget(NSObject):
    def initWithCallback_(self, callback):
        self = objc.super(_TabTarget, self).init()
        if self is None:
            return None
        self.callback = callback
        return self

    def tabChanged_(self, sender):
        self.callback(sender.selectedSegment())


def _label(text, font, color, frame, align_right=False, truncate=False):
    field = NSTextField.labelWithString_(text)
    field.setFont_(font)
    field.setTextColor_(color)
    field.setFrame_(frame)
    if align_right:
        field.setAlignment_(NSTextAlignmentRight)
    if truncate:
        field.cell().setLineBreakMode_(NSLineBreakByTruncatingMiddle)
    return field


def _rows_height(rows):
    return sum(ROW_HEIGHTS[row[0]] for row in rows)


class StatsPanel:
    """Owns the NSMenuItem and redraws its content when data or tab changes."""

    def __init__(self, selected_tab=0, on_tab_change=None):
        self.tabs = []
        self.selected = selected_tab
        self.on_tab_change = on_tab_change
        self._target = _TabTarget.alloc().initWithCallback_(self._select)

        self.view = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 100))
        self.content = _FlippedView.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 0))
        self.segments = None
        self.view.addSubview_(self.content)

        self.menuitem = NSMenuItem.alloc().init()
        self.menuitem.setView_(self.view)

    def _build_segments(self, names):
        if self.segments is not None:
            self.segments.removeFromSuperview()
        self.segments = NSSegmentedControl.segmentedControlWithLabels_trackingMode_target_action_(
            names, NSSegmentSwitchTrackingSelectOne, self._target, "tabChanged:"
        )
        self.segments.setSegmentDistribution_(NSSegmentDistributionFillEqually)
        self.segments.setFrame_(NSMakeRect(PAD_X, PAD_Y, WIDTH - 2 * PAD_X, TABS_HEIGHT))
        self.segments.setSelectedSegment_(self.selected)
        self.view.addSubview_(self.segments)

    def update(self, tabs):
        names = [name for name, _ in tabs]
        if self.segments is None or names != [name for name, _ in self.tabs]:
            self.selected = min(self.selected, len(tabs) - 1)
            self._build_segments(names)
        self.tabs = tabs

        # Size for the tallest tab so switching tabs never resizes the open menu.
        content_height = max(_rows_height(rows) for _, rows in tabs)
        content_top = PAD_Y + TABS_HEIGHT + PAD_Y
        self.view.setFrameSize_((WIDTH, content_top + content_height + PAD_Y))
        self.content.setFrame_(NSMakeRect(0, content_top, WIDTH, content_height))
        self._draw()

    def _select(self, index):
        self.selected = index
        self._draw()
        if self.on_tab_change:
            self.on_tab_change(index)

    def _draw(self):
        for subview in list(self.content.subviews()):
            subview.removeFromSuperview()
        if not self.tabs:
            return
        _, rows = self.tabs[self.selected]

        size = NSFont.menuFontOfSize_(0.0).pointSize()
        regular = NSFont.systemFontOfSize_(size)
        bold = NSFont.boldSystemFontOfSize_(size)
        digits = NSFont.monospacedDigitSystemFontOfSize_weight_(size, 0.0)
        small = NSFont.systemFontOfSize_(size - 2)
        primary = NSColor.labelColor()
        secondary = NSColor.secondaryLabelColor()

        inner = WIDTH - 2 * PAD_X
        y = 0
        for row in rows:
            kind = row[0]
            height = ROW_HEIGHTS[kind]
            if kind == "heading":
                self.content.addSubview_(
                    _label(row[1], bold, primary, NSMakeRect(PAD_X, y, inner, height))
                )
            elif kind == "row":
                label_width = inner - VALUE_WIDTH - 8
                self.content.addSubview_(
                    _label(row[1], regular, primary,
                           NSMakeRect(PAD_X, y, label_width, height), truncate=True)
                )
                self.content.addSubview_(
                    _label(row[2], digits, primary,
                           NSMakeRect(PAD_X + inner - VALUE_WIDTH, y, VALUE_WIDTH, height),
                           align_right=True)
                )
            elif kind == "note":
                self.content.addSubview_(
                    _label(row[1], small, secondary, NSMakeRect(PAD_X, y, inner, height))
                )
            y += height
