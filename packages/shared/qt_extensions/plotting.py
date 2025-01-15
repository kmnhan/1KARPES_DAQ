import datetime
from collections.abc import Callable, Iterable, Sequence

import numpy as np
import pyqtgraph as pg
from qtpy import QtCore, QtGui

from qt_extensions.legendtable import LegendTableView


class SnapCurveItem(pg.PlotCurveItem):
    # Adapted from https://stackoverflow.com/a/68857695

    sigCurveHovered = QtCore.Signal(object, object)
    sigCurveNotHovered = QtCore.Signal(object, object)

    def __init__(
        self,
        *args,
        hoverable: bool = True,
        target_kw: dict | None = None,
        **kwargs,
    ):
        self.hoverable = hoverable

        if target_kw is None:
            target_kw = {}
        target_kw["movable"] = False
        target_kw.setdefault("size", 6)

        self.target = pg.TargetItem(**target_kw)
        super().__init__(*args, **kwargs)
        self.target.setParentItem(self)

        self.setAcceptHoverEvents(True)
        self.setClickable(True, 20)

    def setPen(self, *args, **kargs):
        super().setPen(*args, **kargs)

        # apply same color to target
        self.target.setPen(*args, **kargs)
        if self.target.label() is not None:
            self.target.label().setColor(self.target.pen.color())

    @QtCore.Slot(bool)
    def setHoverable(self, hoverable: bool):
        self.hoverable = hoverable
        if not self.hoverable:
            self.target.setVisible(False)

    def viewRangeChanged(self):
        super().viewRangeChanged()
        self._mouseShape = None

    def hoverEvent(self, ev):
        if not self.hoverable:
            return
        if ev.isExit() or not self.mouseShape().contains(ev.pos()):
            if self.target is not None:
                self.target.setVisible(False)
            self.sigCurveNotHovered.emit(self, ev)
        else:
            if self.target is not None:
                ind = np.argmin(np.abs(self.xData - ev.pos().x()))
                self.target.setPos(self.xData[ind], self.yData[ind])
                self.target.setVisible(True)
            self.sigCurveHovered.emit(self, ev)


class SnapCurvePlotDataItem(pg.PlotDataItem):
    def __init__(
        self,
        *args,
        hoverable: bool = True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.curve = SnapCurveItem(hoverable=hoverable)
        self.curve.setParentItem(self)
        self.curve.sigClicked.connect(self.curveClicked)
        self.setData(*args, **kwargs)

        self.curve.target.setLabel(
            self.gen_label, labelOpts={"fill": (100, 100, 100, 150)}
        )

    @staticmethod
    def format_x(x: float) -> str:
        return f"{x:.3f}"

    @staticmethod
    def format_y(y: float) -> str:
        return f"{y:.3f}"

    def gen_label(self, x: float, y: float) -> str:
        if self.name() is None:
            label = ""
        else:
            label = f"{self.name()}\n"
        if self.opts["logMode"][0]:
            x = 10**x
        if self.opts["logMode"][1]:
            y = 10**y
        label += self.format_x(x) + "\n" + self.format_y(y)
        return label


class XDateSnapCurvePlotDataItem(SnapCurvePlotDataItem):
    @staticmethod
    def format_x(x: float) -> str:
        return datetime.datetime.fromtimestamp(max(x, 0)).strftime("%m/%d %H:%M:%S")


class DynamicPlotItem(pg.PlotItem):
    def __init__(
        self,
        *args,
        legendtableview: LegendTableView,
        ncurves: int | None = None,
        plot_cls: type[pg.PlotDataItem] = pg.PlotDataItem,
        plot_kw: dict | None = None,
        pen_kw: dict | None = None,
        xformat: Callable[[float], str] | None = None,
        yformat: Callable[[float], str] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.legendtable: LegendTableView = legendtableview
        self.plot_cls: type[pg.PlotDataItem] = plot_cls
        if plot_kw is None:
            plot_kw = {}
        self.plot_kw: dict = plot_kw
        self.plots: list[pg.PlotDataItem] = []
        if ncurves is not None:
            self.set_ncurves(ncurves)

        if pen_kw is None:
            pen_kw = {}
        self.pen_kw = pen_kw

        self.legendtable.model().sigCurveToggled.connect(self.update_visibility)
        self.legendtable.model().sigColorChanged.connect(self.update_color)

        # Add cursor
        self.vline = pg.InfiniteLine(
            angle=90,
            movable=True,
            label="",
            labelOpts={"position": 0.75, "movable": True, "fill": (200, 200, 200, 75)},
        )
        self.addItem(self.vline)
        self.vline.sigPositionChanged.connect(self.update_cursor_label)

        if xformat is None:
            if hasattr(self.plot_cls, "format_x"):
                xformat = self.plot_cls.format_x
            else:

                def xformat(x):
                    return f"{x:.3f}"

        self.xformat = xformat

        if yformat is None:
            if hasattr(self.plot_cls, "format_y"):
                yformat = self.plot_cls.format_y
            else:

                def yformat(y):
                    return f"{y:.3f}"

        self.yformat = yformat

        self.toggle_cursor()

    @QtCore.Slot()
    def toggle_cursor(self):
        self.vline.setVisible(not self.vline.isVisible())

    @QtCore.Slot()
    def center_cursor(self):
        xmin, xmax = self.viewRange()[0]
        self.vline.setValue((xmin + xmax) / 2)

    @QtCore.Slot()
    def update_cursor_label(self):
        xval = self.vline.value()
        label = (
            f'<span style="color: #FFF; font-weight: 600;">{self.xformat(xval)}</span>'
        )
        old_x = None
        for plot, enabled, entry, color in zip(
            self.plots,
            self.legendtable.enabled,
            self.legendtable.entries,
            self.legendtable.colors,
            strict=True,
        ):
            if plot.xData is None:
                continue
            if old_x is None or not np.allclose(old_x, plot.xData):
                old_x = plot.xData
                idx = (np.abs(plot.xData - xval)).argmin()
            yval = plot.yData[idx]
            if enabled:
                label += f'<br><span style="color: {color.name()}; font-weight: 600;">{entry}</span>'
                label += f'<span style="color: #FFF;"> {self.yformat(yval)}</span>'
        self.vline.label.setHtml(label)

    @QtCore.Slot()
    def toggle_snap(self):
        for p in self.plots:
            p.curve.setHoverable(not p.curve.hoverable)

    def set_ncurves(self, ncurves: int):
        diff = ncurves - len(self.plots)
        if diff == 0:
            return
        elif diff > 0:
            for _ in range(diff):
                self.plots.append(self.plot_cls(**self.plot_kw))
                self.addItem(self.plots[-1])
        else:
            for _ in range(abs(diff)):
                self.removeItem(self.plots.pop(-1))

    def set_labels(self, labels: Sequence[str]):
        self.legendtable.set_items(labels)
        self.set_ncurves(len(labels))
        for plot, label in zip(self.plots, labels, strict=True):
            plot.opts["name"] = label
            plot.setProperty("styleWasChanged", True)

    @QtCore.Slot(int, bool)
    def update_visibility(self, index: int, visible: bool):
        self.plots[index].setVisible(visible)
        self.plots[index].informViewBoundsChanged()

    @QtCore.Slot(int, object)
    def update_color(self, index: int, color: QtGui.QColor):
        self.plots[index].setPen(color=color, **self.pen_kw)

    def set_enabled(self, index: int, value: bool):
        self.legendtable.set_enabled(index, value)

    def set_color(self, index: int, color: QtGui.QColor):
        self.legendtable.set_color(index, color)

    def set_data(self, index: int, x: Sequence[float], y: Sequence[float], **kwargs):
        self.plots[index].setVisible(self.legendtable.enabled[index])
        self.plots[index].setData(x, y, **kwargs)
        self.plots[index].setPen(color=self.legendtable.colors[index], **self.pen_kw)

    def set_datalist(
        self, x: Sequence[float], ylist: Sequence[Sequence[float]], **kwargs
    ):
        for plot, y, color, enabled in zip(
            self.plots,
            ylist,
            self.legendtable.colors,
            self.legendtable.enabled,
            strict=True,
        ):
            plot.setVisible(enabled)
            plot.setData(x, y, **kwargs)
            plot.setPen(color=color, **self.pen_kw)
        self.vline.setBounds((min(x), max(x)))

    def set_datadict(
        self, x: Sequence[float], ydict: dict[str, Sequence[float]], **kwargs
    ):
        self.set_labels(ydict.keys())
        self.set_datalist(x, ydict.values(), **kwargs)


class DynamicPlotItemTwiny(DynamicPlotItem):
    def __init__(
        self,
        *args,
        pen_kw_twin: dict | None = None,
        twiny_labels: Iterable[str] | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        if pen_kw_twin is None:
            pen_kw_twin = {}
        self.pen_kw_twin = pen_kw_twin

        # Add another viewbox
        self.vbs = [self.vb, pg.ViewBox()]

        if twiny_labels is None:
            twiny_labels = []
        self.set_twiny_labels(twiny_labels)

    def setup_twiny(self):
        self.showAxis("right")
        self.scene().addItem(self.vbs[1])
        self.getAxis("right").linkToView(self.vbs[1])
        self.vbs[1].setXLink(self.vbs[0])
        self.updateViews()
        self.vb.sigResized.connect(self.updateViews)

    def updateViews(self):
        self.vbs[1].setGeometry(self.vb.sceneBoundingRect())

    def toggle_logy(self, twin: bool):
        if twin:
            index = 1
        else:
            index = 0
        self.set_logy(index, not self.getAxis(("left", "right")[index]).logMode)

    def set_logy(self, twin: bool, value: bool):
        if twin:
            index = 1
        else:
            index = 0
        self.getAxis(("left", "right")[index]).setLogMode(value)
        for plot in self.plots:
            if plot.getViewBox() == self.vbs[index]:
                plot.setLogMode(self.getAxis("bottom").logMode, value)
        self.vbs[index].enableAutoRange(y=True)

    def set_twiny_labels(self, twiny_labels: Iterable[str]):
        self.twiny_labels = twiny_labels
        self.set_ncurves(len(self.plots))

    def set_ncurves(self, ncurves: int):
        diff = ncurves - len(self.plots)
        if diff > 0:
            for _ in range(diff):
                self.plots.append(self.plot_cls(**self.plot_kw))
        elif diff < 0:
            for _ in range(abs(diff)):
                p = self.plots.pop(-1)
                p.getViewBox().removeItem(p)

        for p, label in zip(self.plots, self.legendtable.entries, strict=True):
            if label in self.twiny_labels:
                vb = self.vbs[1]
            else:
                vb = self.vbs[0]
            if p.getViewBox() == vb:
                continue
            elif p.getViewBox() is not None:
                p.getViewBox().removeItem(p)
                p.forgetViewBox()
            vb.addItem(p)

    def set_data(self, index: int, x: Sequence[float], y: Sequence[float], **kwargs):
        self.plots[index].setVisible(self.legendtable.enabled[index])
        self.plots[index].setData(x, y, **kwargs)
        if self.legendtable.entries[index] in self.twiny_labels:
            pen_kw = self.pen_kw_twin
        else:
            pen_kw = self.pen_kw
        self.plots[index].setPen(color=self.legendtable.colors[index], **pen_kw)

    def set_datalist(
        self, x: Sequence[float], ylist: Sequence[Sequence[float]], **kwargs
    ):
        for plot, y, color, enabled, label in zip(
            self.plots,
            ylist,
            self.legendtable.colors,
            self.legendtable.enabled,
            self.legendtable.entries,
            strict=True,
        ):
            plot.setVisible(enabled)
            plot.setData(x, y, **kwargs)
            if label in self.twiny_labels:
                pen_kw = self.pen_kw_twin
            else:
                pen_kw = self.pen_kw
            plot.setPen(color=color, **pen_kw)
        self.vline.setBounds((min(x), max(x)))
