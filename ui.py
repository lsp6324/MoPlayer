from PySide6.QtCore import Qt, QSize, QPointF, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPolygonF
from PySide6.QtWidgets import QLabel, QPushButton, QSizePolicy

def icon(name, color='#cbd2dd', size=24):  # 绘制统一的圆角细线图标。
    pixmap = QPixmap(size * 2, size * 2)  # 用双倍像素保证高 DPI 下清晰。
    pixmap.fill(Qt.transparent)  # 保留背景透明。
    painter = QPainter(pixmap)  # 在图标画布上绘制。
    painter.setRenderHint(QPainter.Antialiasing)  # 平滑图标线条。
    painter.scale(size * 2 / 24, size * 2 / 24)  # 将标准 24 单位坐标映射到目标分辨率。
    painter.setPen(QPen(QColor(color), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))  # 使用统一线宽和圆角端点。
    paths = {  # 用清晰的线段描述常用操作图标。
        'edit': [[(4, 16), (15, 5), (19, 9), (8, 20), (3, 21), (4, 16)], [(13, 7), (17, 11)]],
        'folder': [[(3, 7), (9, 7), (11, 9), (21, 9), (21, 20), (3, 20), (3, 7)], [(3, 7), (3, 5), (9, 5), (11, 7), (20, 7)]],  # 文件夹轮廓。
        'history': [[(4, 10), (4, 4), (1, 7)], [(12, 7), (12, 12), (16, 14)]],  # 历史时钟指针与返回箭头。
        'star': [[(12, 3), (15, 9), (22, 10), (17, 15), (18, 22), (12, 18), (6, 22), (7, 15), (2, 10), (9, 9), (12, 3)]],  # 收藏五角星。
        'tag': [[(3, 4), (12, 4), (22, 14), (14, 22), (3, 11), (3, 4)]],  # 标签吊牌轮廓。
        'score': [[(5, 19), (5, 13)], [(12, 19), (12, 5)], [(19, 19), (19, 9)]],  # 评分柱形标记。
        'photo': [[(3, 4), (21, 4), (21, 20), (3, 20), (3, 4)], [(3, 17), (9, 11), (13, 15), (16, 12), (21, 17)]],  # 自定义背景图标。
        'full': [[(8, 3), (3, 3), (3, 8)], [(16, 3), (21, 3), (21, 8)], [(3, 16), (3, 21), (8, 21)], [(16, 21), (21, 21), (21, 16)]],  # 视频全屏使用四角展开图标。
        'volume': [[(3, 9), (7, 9), (12, 5), (12, 19), (7, 15), (3, 15), (3, 9)], [(16, 8), (18, 12), (16, 16)], [(19, 5), (22, 12), (19, 19)]],  # 音量扬声器。
        'plus': [[(12, 5), (12, 19)], [(5, 12), (19, 12)]],  # 导入按钮加号。
        'back': [[(10, 5), (3, 12), (10, 19)], [(3, 12), (21, 12)]],
        'tasks': [[(9, 6), (21, 6)], [(9, 12), (21, 12)], [(9, 18), (21, 18)], [(3, 6), (4, 7), (6, 4)], [(3, 12), (4, 13), (6, 10)], [(3, 18), (4, 19), (6, 16)]],  # 归档任务列表。
        'help': [[(9, 8), (10, 6), (14, 6), (16, 8), (15, 10), (12, 12), (12, 14)], [(12, 18), (12, 18.2)]],  # 帮助问号。
        'pause': [[(8, 6), (8, 18)], [(16, 6), (16, 18)]],  # 暂停双竖线。
        'previous': [[(5, 6), (5, 18)], [(18, 5), (8, 12), (18, 19), (18, 5)]],  # 上一个视频。
        'next': [[(19, 6), (19, 18)], [(6, 5), (16, 12), (6, 19), (6, 5)]],  # 下一个视频。
    }  # 结束统一图标路径表。
    paths.update({'sidebar': [[(3, 4), (21, 4), (21, 20), (3, 20), (3, 4)], [(9, 4), (9, 20)]]})
    paths.update({
        'list': [[(9, 5), (21, 5)], [(9, 12), (21, 12)], [(9, 19), (21, 19)], [(3, 5), (4, 5)], [(3, 12), (4, 12)], [(3, 19), (4, 19)]],
        'grid': [[(3, 3), (10, 3), (10, 10), (3, 10), (3, 3)], [(14, 3), (21, 3), (21, 10), (14, 10), (14, 3)], [(3, 14), (10, 14), (10, 21), (3, 21), (3, 14)], [(14, 14), (21, 14), (21, 21), (14, 21), (14, 14)]],
        'filters': [[(3, 6), (8, 6)], [(12, 6), (21, 6)], [(3, 12), (14, 12)], [(18, 12), (21, 12)], [(3, 18), (6, 18)], [(10, 18), (21, 18)], [(10, 3), (10, 9)], [(16, 9), (16, 15)], [(8, 15), (8, 21)]],
        'muted': [[(3, 9), (7, 9), (12, 5), (12, 19), (7, 15), (3, 15), (3, 9)], [(17, 9), (23, 15)], [(23, 9), (17, 15)]],
        'minimize': [[(5, 12), (19, 12)]],
        'maximize': [[(5, 5), (19, 5), (19, 19), (5, 19), (5, 5)]],
        'restore': [[(8, 4), (20, 4), (20, 16)], [(4, 8), (16, 8), (16, 20), (4, 20), (4, 8)]],
        'close': [[(6, 6), (18, 18)], [(18, 6), (6, 18)]],
    })
    if name == 'more':
        painter.setBrush(QColor(color))
        for x in (5, 12, 19):
            painter.drawEllipse(QPointF(x, 12), 1, 1)
    if name == 'play':  # 播放使用实心三角形突出主要控制。
        painter.setBrush(QColor(color))  # 填充与线条相同的颜色。
        painter.drawPolygon(QPolygonF([QPointF(8, 5), QPointF(19, 12), QPointF(8, 19)]))  # 适当右移以获得视觉居中。
    if name == 'starFilled':
        painter.setBrush(QColor(color))
        painter.drawPolygon(QPolygonF([QPointF(x, y) for x, y in paths['star'][0]]))
    if name == 'heart':
        from heart_rating import heart_path
        painter.drawPath(heart_path(QRectF(0, 0, 24, 24)))
    for points in paths.get(name, []):  # 绘制当前图标的各条折线。
        painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))  # 根据标准坐标生成平滑线条。
    if name in ('history', 'help'):  # 时钟和帮助图标补充外圆。
        painter.drawEllipse(QPointF(12, 12), 9, 9)  # 使用一致的圆形外框。
    if name in ('photo', 'tag'):  # 图片和标签补充小圆细节。
        painter.drawEllipse(QPointF(16, 8) if name == 'photo' else QPointF(7, 8), 1.1, 1.1)  # 标注太阳或吊牌孔洞。
    painter.end()  # 结束画布绘制。
    pixmap.setDevicePixelRatio(2)  # 让 Qt 按高 DPI 图标显示。
    return QIcon(pixmap)  # 返回所有按钮可共享的矢量风格图标。

def label(text, role=None):  # 创建具有语义样式的文字标签。
    result = QLabel(text)  # 设置用户可见文案。
    if role:  # 样式按角色统一管理。
        result.setProperty('role', role)  # 让 QSS 应用对应层级。
    return result  # 供布局直接使用。

def button(text, callback, symbol=None, role=None):  # 创建一致的操作按钮。
    result = QPushButton(text)  # 提供可读操作名称。
    result.setCursor(Qt.PointingHandCursor)  # 悬停时提示可点击。
    if role:  # 仅主要和特殊按钮声明角色。
        result.setProperty('role', role)  # 使用统一的颜色和圆角样式。
    if symbol:  # 图标与文字保持一致间距。
        result.setProperty('iconName', symbol)
        result.setIcon(icon(symbol, '#ffffff' if role == 'primary' else '#cbd2dd'))  # 主按钮使用白色图标。
        result.setIconSize(QSize(17, 17))  # 导航和次级按钮统一图标大小。
    result.clicked.connect(callback)  # 不改变原有业务回调。
    return result  # 返回可进一步调整的控件。

class PathLabel(QLabel):  # 路径过长时省略显示而不挤压卡片布局。
    def __init__(self, text):  # 保留完整路径用于提示。
        super().__init__()  # 初始化标签。
        self.full_text = text  # 缓存完整文本。
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)  # 允许左右分隔线正常缩小目录区域。
        self.setObjectName('directoryPath')  # 使用路径专属次级样式。
        self.setText(text)  # 首次展示文案。

    def setText(self, text):  # 兼容原扫描完成后的路径更新。
        self.full_text = text  # 保存未裁切路径。
        self.setToolTip(text)  # 悬停可查看完整路径。
        super().setText(self.fontMetrics().elidedText(text, Qt.ElideMiddle, max(80, self.width())))  # 在中间省略保留盘符与末级名称。

    def resizeEvent(self, event):  # 左侧宽度改变后重新计算路径显示。
        super().resizeEvent(event)  # 保持 Qt 标签正常布局。
        self.setText(self.full_text)  # 不改变真实浏览路径。


def format_time(ms):  # 将播放时间格式化为可读文本。
    seconds = max(0, ms) // 1000  # 未知时长显示零。
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'
