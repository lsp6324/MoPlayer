"""Shared Qt layout for tag rows and the branches opened below them."""
from PySide6.QtCore import Qt, QRect, QSize, QPoint
from PySide6.QtWidgets import QLayout


class FlowLayout(QLayout):  # 胶囊按可用宽度自动换行。
    def __init__(self, parent=None):  # 由对应标签区管理布局。
        super().__init__(parent)  # 初始化 Qt 布局。
        self.items = []  # 保持胶囊的自然排序。
        self.branches = {}
        self.setContentsMargins(0, 0, 0, 0)  # 胶囊区不增加多余边框。
        self.setSpacing(8)  # 横纵方向均保留适量间隔。

    def addItem(self, item):  # 接收普通控件布局项。
        self.items.append(item)  # 不创建额外列表模型。

    def add_branch(self, anchor, panel):
        self.addWidget(panel)
        self.branches[anchor] = self.items[-1]

    def count(self):  # 返回 Qt 所需项目数量。
        return len(self.items)  # 与胶囊控件一一对应。

    def itemAt(self, index):  # 供 Qt 查询有效布局项。
        return self.items[index] if 0 <= index < len(self.items) else None  # 无效索引返回空。

    def takeAt(self, index):  # 支持 Qt 正常移除项目。
        return self.items.pop(index) if 0 <= index < len(self.items) else None  # 不访问越界位置。

    def expandingDirections(self):  # 宽度由外层滚动区决定。
        return Qt.Orientation(0)  # 不强制扩展每个胶囊。

    def hasHeightForWidth(self):  # 换行后的高度依赖宽度。
        return True  # 让滚动区按实际行数计算高度。

    def heightForWidth(self, width):  # 先计算不改变位置的布局高度。
        return self.arrange(QRect(0, 0, width, 0), True)  # 使用与绘制相同的换行规则。

    def setGeometry(self, rect):  # 实际放置胶囊。
        super().setGeometry(rect)  # 保持 Qt 布局几何有效。
        self.arrange(rect, False)  # 宽度改变时重新换行。

    def sizeHint(self):  # 让父布局合理分配初始空间。
        return self.minimumSize()  # 不产生额外空白大面板。

    def minimumSize(self):  # 最小宽度只需容纳一个胶囊。
        size = QSize(0, 0)  # 空标签区可以收缩。
        for item in self.items:  # 使用每个胶囊的实际尺寸。
            if item in self.branches.values():
                continue
            size = size.expandedTo(item.minimumSize())  # 避免截断单个标签的点击区域。
        return size  # 换行高度另外计算。

    def arrange(self, rect, measure):  # 简单地从左到右排列并换行。
        width, rows, row, used = max(1, rect.width()), [], [], 0
        for item in self.items:
            if item in self.branches.values():
                continue
            size = QSize(min(width, item.sizeHint().width()), item.sizeHint().height())
            if row and used + self.spacing() + size.width() > width:
                rows.append(row)
                row, used = [], 0
            row.append((item, size))
            used += (self.spacing() if used else 0) + size.width()
        if row:
            rows.append(row)
        y = rect.y()
        for number, row in enumerate(rows):
            if number:
                y += self.spacing()
            x, height = rect.x(), max(size.height() for _, size in row)
            for item, size in row:
                if not measure:
                    item.setGeometry(QRect(QPoint(x, y), size))
                x += size.width() + self.spacing()
            y += height
            for item, _ in row:
                branch = self.branches.get(item.widget())
                if branch is None:
                    continue
                branch_height = branch.heightForWidth(width) if branch.hasHeightForWidth() else branch.sizeHint().height()
                y += self.spacing()
                if not measure:
                    branch.setGeometry(QRect(rect.x(), y, width, max(0, branch_height)))
                y += max(0, branch_height)
        return y - rect.y()

