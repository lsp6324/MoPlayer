from PySide6.QtCore import Qt, QRectF  # 定义半颗心的绘制和点击区域。
from PySide6.QtGui import QPainter, QPainterPath, QColor, QPen  # 用矢量绘制心形，不依赖表情字体。
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QPushButton, QAbstractButton  # 构建五颗心的紧凑评分卡。

class HeartButton(QAbstractButton):  # 一颗心的左右两半分别对应一个整数分。
    def __init__(self, editor, number):  # number 表示第一至第五颗心。
        super().__init__(editor)  # 所有心形共用同一评分卡状态。
        self.editor, self.number = editor, number  # 保存总分来源与该颗心的序号。
        self.setFixedSize(48, 48)  # 保持每颗心的点击目标相同。
        self.setCursor(Qt.PointingHandCursor)  # 提示整颗心可以点击。
        self.setMouseTracking(True)  # 鼠标移动时显示半颗心预览。
        self.setFocusPolicy(Qt.StrongFocus)  # 可使用键盘聚焦。
        self.setAccessibleName(f'第{number}颗心，左侧{number * 2 - 1}分，右侧{number * 2}分')  # 明确半颗对应的分值。
        self.setToolTip(f'左半：{number * 2 - 1} 分；右半：{number * 2} 分')  # 说明无需占据常驻界面空间。

    def points(self, x):  # 左半取奇数，右半取偶数。
        return self.number * 2 - (1 if x < self.width() / 2 else 0)  # 五颗心覆盖一至十分。

    def mouseMoveEvent(self, event):  # 悬停只修改预览。
        self.editor.show_preview(self.points(event.position().x()))  # 同一颗心内移动也可预览半颗变化。

    def leaveEvent(self, event):  # 移出后恢复原评分。
        self.editor.show_preview(None)  # 不把悬停当作评分提交。
        super().leaveEvent(event)  # 保留原生控件事件处理。

    def mouseReleaseEvent(self, event):  # 点击指向的半颗心直接提交。
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):  # 只响应有效左键释放。
            self.editor.choose(self.points(event.position().x()))  # 仍使用原来的零至十分整数。
            event.accept()  # 不重复提交点击。
        else:  # 其他操作交给原生按钮。
            super().mouseReleaseEvent(event)  # 右键与移出释放不误保存。

    def keyPressEvent(self, event):  # 保留简单的键盘操作。
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):  # 聚焦心形后可确认该颗完整分数。
            self.editor.choose(self.number * 2)  # 半颗通过左右区域精确选择。
            event.accept()  # 不向对话框重复发出确认。
        else:  # Tab 等焦点导航保留默认行为。
            super().keyPressEvent(event)  # 不抢占其他输入。

    def paintEvent(self, event):  # 显示空心、左半颗或整颗红心。
        value = self.editor.preview if self.editor.preview is not None else self.editor.value or 0  # 未评分显示五颗空心。
        portion = min(2, max(0, value - (self.number - 1) * 2))  # 每颗心最多填两个半颗。
        area = QRectF(5, 5, self.width() - 10, self.height() - 10)  # 给描边留出空间。
        path = QPainterPath()  # 统一生成圆润心形。
        path.moveTo(area.center().x(), area.bottom() - 1)  # 从底部尖角起笔。
        path.cubicTo(area.left() - 8, area.top() + 15, area.left() + 2, area.top() - 7, area.center().x(), area.top() + 8)  # 左侧圆弧连接中间凹口。
        path.cubicTo(area.right() - 2, area.top() - 7, area.right() + 8, area.top() + 15, area.center().x(), area.bottom() - 1)  # 对称绘制右侧圆弧。
        path.closeSubpath()  # 形成可填充轮廓。
        painter = QPainter(self)  # 使用当前控件的实际像素绘制。
        painter.setRenderHint(QPainter.Antialiasing)  # 保证边缘平滑。
        painter.fillPath(path, QColor('#ffffff'))  # 空心区域保留白色。
        if portion:  # 需要填充时区分半颗和整颗。
            painter.save()  # 局部裁切不影响最终轮廓。
            if portion == 1:  # 奇数分只点亮当前颗的左半。
                painter.setClipRect(QRectF(0, 0, self.width() / 2, self.height()))  # 九分显示四颗半红心。
            painter.fillPath(path, QColor('#ed6070'))  # 所有选中部分统一使用红色。
            painter.restore()  # 恢复完整绘制区域。
        painter.setPen(QPen(QColor('#ed6070' if portion else '#929eac'), 1.8))  # 未选中描边为灰色。
        painter.drawPath(path)  # 保留整颗心的清晰外轮廓。

class ScoreEditor(QDialog):  # 五颗心仍兼容零分与独立未评分状态。
    def __init__(self, video, parent=None):  # 绑定打开时的视频身份。
        super().__init__(parent)  # 不强制暂停播放。
        self.value, self.preview = video['score'], None  # 实际分数与悬停预览分离。
        self.setWindowTitle('视频评分')  # 保留系统可识别的弹窗名称。
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)  # 使用参考图中的轻量卡片。
        self.setAttribute(Qt.WA_TranslucentBackground)  # 圆角外侧保持透明。
        self.setFixedSize(360, 150)  # 五颗心无需占用原十按钮网格的空间。
        root = QVBoxLayout(self)  # 白卡片填满弹窗。
        root.setContentsMargins(0, 0, 0, 0)  # 去掉系统窗体留白。
        card = QFrame()  # 白底圆角容器。
        card.setObjectName('scoreCard')  # 样式只作用于当前卡片。
        card.setToolTip(video['name'])  # 悬停可确认正在评分的视频。
        root.addWidget(card)  # 不影响主界面和其他弹窗。
        self.setStyleSheet('#scoreCard { background:white; border:1px solid #dce2ea; border-radius:13px; } QLabel { color:#566174; background:transparent; border:none; font-size:15px; } QPushButton { background:transparent; border:none; color:#647083; padding:3px; font-size:14px; } QPushButton:hover { color:#ed6070; }')  # 贴近白色参考卡片的简洁外观。
        layout = QVBoxLayout(card)  # 上方五颗心，下方零分、读数和清除。
        layout.setContentsMargins(18, 17, 18, 15)  # 使用均匀的卡片边距。
        row = QHBoxLayout()  # 五颗心等间距排列。
        row.setSpacing(10)  # 保留足够的左右半颗点击间隔。
        self.hearts = [HeartButton(self, number) for number in range(1, 6)]  # 只创建五颗心形控件。
        for heart in self.hearts:  # 共用总分而非五套独立状态。
            row.addWidget(heart)  # 按顺序排列第一至第五颗。
        layout.addLayout(row)  # 不显示多余标题和下拉框。
        footer = QHBoxLayout()  # 与参考图一致的三项底部内容。
        zero = QPushButton('0 分')  # 零分不是未评分。
        zero.setObjectName('score_0')  # 保留零分控件的自动化识别名称。
        zero.clicked.connect(lambda: self.choose(0))  # 只有主动点击才保存零分。
        footer.addWidget(zero)  # 零分放在左下角。
        self.readout = QLabel()  # 居中显示当前十分制分数。
        self.readout.setAlignment(Qt.AlignCenter)  # 数字与心形区域对齐。
        footer.addWidget(self.readout, 1)  # 为分数留出主要空间。
        clear = QPushButton('清除')  # 右下角恢复未评分。
        clear.setObjectName('score_unrated')  # 保留未评分控件的自动化识别名称。
        clear.clicked.connect(lambda: self.choose(None))  # 与原数据库空评分语义保持一致。
        footer.addWidget(clear)  # 不再增加第二套分数按钮。
        layout.addLayout(footer)  # Esc 可以取消，无需额外常驻按钮。
        self.show_preview(None)  # 初始即按已有分数显示整颗和半颗红心。

    def show_preview(self, value):  # 悬停只更新显示，不归档。
        self.preview = value  # 移出时用 None 恢复实际分数。
        displayed = self.value if value is None else value  # 区分未评分与预览。
        self.readout.setText(f'{displayed if displayed is not None else "—"} / 10')  # 未评分显示横线。
        for heart in self.hearts:  # 一次总分变化刷新全部五颗心。
            heart.update()  # 使用 Qt 正常绘制队列。

    def choose(self, value):  # 点击半颗、零分或清除后一次提交。
        self.value = value  # 交给原评分与归档同步逻辑处理。
        self.accept()  # 不增加额外确认步骤。
