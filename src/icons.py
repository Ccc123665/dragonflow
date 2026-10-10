"""矢量图标：用 QPainter 现画，零资源依赖，颜色可随主题。

风格：2px 描边、圆头圆角、24 网格（对齐 iOS SF Symbols 的视觉重量）。
"""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

import theme

S = 24          # 设计网格
_cache: dict = {}


def _pen(color: str, w: float = 2.0) -> QPen:
    p = QPen(QColor(color))
    p.setWidthF(w)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return p


def _draw(name: str, p: QPainter, color: str) -> None:
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)

    if name == "studio":            # 钢笔 / 创作
        path = QPainterPath()
        path.moveTo(5, 19)
        path.lineTo(6.2, 14.6)
        path.lineTo(15.4, 5.4)
        path.lineTo(18.6, 8.6)
        path.lineTo(9.4, 17.8)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(13.4, 7.4), QPointF(16.6, 10.6))

    elif name == "send":            # 发布 / 分发
        path = QPainterPath()
        path.moveTo(4.5, 12)
        path.lineTo(19.5, 5)
        path.lineTo(13.5, 19.5)
        path.lineTo(11.2, 13.2)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "folder":          # 素材库
        path = QPainterPath()
        path.moveTo(4, 18.5)
        path.lineTo(4, 7)
        path.lineTo(10, 7)
        path.lineTo(11.6, 9.4)
        path.lineTo(20, 9.4)
        path.lineTo(20, 18.5)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "clock":           # 记录
        p.drawEllipse(QRectF(4.2, 4.2, 15.6, 15.6))
        p.drawLine(QPointF(12, 7.8), QPointF(12, 12.2))
        p.drawLine(QPointF(12, 12.2), QPointF(15.4, 14.2))

    elif name == "gear":            # 设置
        p.drawEllipse(QRectF(9, 9, 6, 6))
        import math
        for i in range(8):
            a = math.radians(i * 45)
            x1, y1 = 12 + 7.2 * math.cos(a), 12 + 7.2 * math.sin(a)
            x2, y2 = 12 + 9.4 * math.cos(a), 12 + 9.4 * math.sin(a)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    elif name == "plus":
        p.drawLine(QPointF(12, 5.5), QPointF(12, 18.5))
        p.drawLine(QPointF(5.5, 12), QPointF(18.5, 12))

    elif name == "minus":
        p.drawLine(QPointF(5.5, 12), QPointF(18.5, 12))

    elif name == "close":
        p.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
        p.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))

    elif name == "max":
        p.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)

    elif name == "refresh":
        path = QPainterPath()
        path.arcMoveTo(QRectF(5, 5, 14, 14), 60)
        path.arcTo(QRectF(5, 5, 14, 14), 60, 280)
        p.drawPath(path)
        p.setBrush(QColor(color))
        tip = QPainterPath()
        tip.moveTo(15.4, 3.6)
        tip.lineTo(19.2, 6.4)
        tip.lineTo(15.0, 8.6)
        tip.closeSubpath()
        p.drawPath(tip)

    elif name == "copy":
        p.drawRoundedRect(QRectF(8.5, 8.5, 11, 11), 2.5, 2.5)
        path = QPainterPath()
        path.moveTo(15.5, 6.2)
        path.lineTo(15.5, 5.6)
        path.quadTo(15.5, 4.5, 14.4, 4.5)
        path.lineTo(5.6, 4.5)
        path.quadTo(4.5, 4.5, 4.5, 5.6)
        path.lineTo(4.5, 14.4)
        path.quadTo(4.5, 15.5, 5.6, 15.5)
        path.lineTo(6.2, 15.5)
        p.drawPath(path)

    elif name == "check":
        path = QPainterPath()
        path.moveTo(5.5, 12.5)
        path.lineTo(10, 17)
        path.lineTo(18.5, 7.5)
        p.drawPath(path)

    elif name == "warn":
        path = QPainterPath()
        path.moveTo(12, 4.5)
        path.lineTo(20.5, 19)
        path.lineTo(3.5, 19)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(12, 10), QPointF(12, 14))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(11.1, 15.6, 1.8, 1.8))

    elif name == "trash":
        p.drawLine(QPointF(5, 7), QPointF(19, 7))
        p.drawLine(QPointF(9.5, 7), QPointF(9.8, 4.8))
        p.drawLine(QPointF(14.5, 7), QPointF(14.2, 4.8))
        p.drawLine(QPointF(9.8, 4.8), QPointF(14.2, 4.8))
        path = QPainterPath()
        path.moveTo(6.6, 7)
        path.lineTo(7.4, 19)
        path.lineTo(16.6, 19)
        path.lineTo(17.4, 7)
        p.drawPath(path)

    elif name == "edit":
        path = QPainterPath()
        path.moveTo(5, 19)
        path.lineTo(5.8, 15.4)
        path.lineTo(15.2, 6)
        path.lineTo(18, 8.8)
        path.lineTo(8.6, 18.2)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "user":
        p.drawEllipse(QRectF(8.6, 4.8, 6.8, 6.8))
        path = QPainterPath()
        path.moveTo(4.8, 19.4)
        path.quadTo(4.8, 13.8, 12, 13.8)
        path.quadTo(19.2, 13.8, 19.2, 19.4)
        p.drawPath(path)

    elif name == "globe":
        p.drawEllipse(QRectF(4.2, 4.2, 15.6, 15.6))
        p.drawLine(QPointF(4.2, 12), QPointF(19.8, 12))
        path = QPainterPath()
        path.moveTo(12, 4.2)
        path.quadTo(7.2, 12, 12, 19.8)
        path.quadTo(16.8, 12, 12, 4.2)
        p.drawPath(path)

    elif name == "sparkle":         # AI
        path = QPainterPath()
        path.moveTo(12, 4)
        path.lineTo(13.8, 9.6)
        path.lineTo(19.5, 11.4)
        path.lineTo(13.8, 13.2)
        path.lineTo(12, 18.8)
        path.lineTo(10.2, 13.2)
        path.lineTo(4.5, 11.4)
        path.lineTo(10.2, 9.6)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "shield":          # 合规
        path = QPainterPath()
        path.moveTo(12, 4)
        path.lineTo(19, 6.6)
        path.lineTo(19, 12)
        path.quadTo(19, 17.4, 12, 20)
        path.quadTo(5, 17.4, 5, 12)
        path.lineTo(5, 6.6)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "chevron_right":
        path = QPainterPath()
        path.moveTo(9.5, 6)
        path.lineTo(15.5, 12)
        path.lineTo(9.5, 18)
        p.drawPath(path)

    elif name == "chevron_left":
        path = QPainterPath()
        path.moveTo(14.5, 6)
        path.lineTo(8.5, 12)
        path.lineTo(14.5, 18)
        p.drawPath(path)

    elif name == "chevron_down":
        path = QPainterPath()
        path.moveTo(6, 9.5)
        path.lineTo(12, 15.5)
        path.lineTo(18, 9.5)
        p.drawPath(path)

    elif name == "external":
        p.drawLine(QPointF(13.5, 5.5), QPointF(18.5, 5.5))
        p.drawLine(QPointF(18.5, 5.5), QPointF(18.5, 10.5))
        p.drawLine(QPointF(18.5, 5.5), QPointF(11, 13))
        path = QPainterPath()
        path.moveTo(16, 14.5)
        path.lineTo(16, 18)
        path.quadTo(16, 19.5, 14.5, 19.5)
        path.lineTo(6, 19.5)
        path.quadTo(4.5, 19.5, 4.5, 18)
        path.lineTo(4.5, 9.5)
        path.quadTo(4.5, 8, 6, 8)
        path.lineTo(9.5, 8)
        p.drawPath(path)

    elif name == "drag":
        for y in (9, 12, 15):
            p.drawLine(QPointF(9, y), QPointF(15, y))

    elif name == "sidebar":          # 侧栏展开 / 收起
        p.drawRoundedRect(QRectF(3.6, 5, 16.8, 14), 2.6, 2.6)
        p.drawLine(QPointF(9.6, 5), QPointF(9.6, 19))

    elif name == "sidebar_open":     # 侧栏展开（箭头朝右）
        p.drawRoundedRect(QRectF(3.6, 5, 16.8, 14), 2.6, 2.6)
        p.drawLine(QPointF(9.6, 5), QPointF(9.6, 19))
        path = QPainterPath()
        path.moveTo(12.4, 9.4)
        path.lineTo(15.4, 12)
        path.lineTo(12.4, 14.6)
        p.drawPath(path)

    elif name == "sidebar_close":    # 侧栏收起（箭头朝左）
        p.drawRoundedRect(QRectF(3.6, 5, 16.8, 14), 2.6, 2.6)
        p.drawLine(QPointF(9.6, 5), QPointF(9.6, 19))
        path = QPainterPath()
        path.moveTo(15.6, 9.4)
        path.lineTo(12.6, 12)
        path.lineTo(15.6, 14.6)
        p.drawPath(path)

    elif name == "expand":           # 最大化
        p.drawLine(QPointF(4.5, 9.5), QPointF(4.5, 4.5))
        p.drawLine(QPointF(4.5, 4.5), QPointF(9.5, 4.5))
        p.drawLine(QPointF(14.5, 19.5), QPointF(19.5, 19.5))
        p.drawLine(QPointF(19.5, 19.5), QPointF(19.5, 14.5))

    elif name == "collapse":         # 还原
        p.drawLine(QPointF(9.5, 4.5), QPointF(9.5, 9.5))
        p.drawLine(QPointF(9.5, 9.5), QPointF(4.5, 9.5))
        p.drawLine(QPointF(14.5, 19.5), QPointF(14.5, 14.5))
        p.drawLine(QPointF(14.5, 14.5), QPointF(19.5, 14.5))

    elif name == "sync":             # 同步（双向箭头）
        p.drawLine(QPointF(6, 9.5), QPointF(17, 9.5))
        path = QPainterPath()
        path.moveTo(14.6, 6.6)
        path.lineTo(17.8, 9.5)
        path.lineTo(14.6, 12.4)
        p.drawPath(path)
        p.drawLine(QPointF(18, 14.5), QPointF(7, 14.5))
        path2 = QPainterPath()
        path2.moveTo(9.4, 11.6)
        path2.lineTo(6.2, 14.5)
        path2.lineTo(9.4, 17.4)
        p.drawPath(path2)

    elif name == "upload":           # 上传
        p.drawLine(QPointF(12, 16), QPointF(12, 5.5))
        path = QPainterPath()
        path.moveTo(7.6, 9.4)
        path.lineTo(12, 5)
        path.lineTo(16.4, 9.4)
        p.drawPath(path)
        p.drawLine(QPointF(5, 19.2), QPointF(19, 19.2))

    elif name == "download":         # 下载 / 导出
        p.drawLine(QPointF(12, 4.8), QPointF(12, 15))
        path = QPainterPath()
        path.moveTo(7.6, 10.8)
        path.lineTo(12, 15.2)
        path.lineTo(16.4, 10.8)
        p.drawPath(path)
        p.drawLine(QPointF(5, 19.2), QPointF(19, 19.2))

    elif name == "target":           # 目标账号
        p.drawEllipse(QRectF(4.4, 4.4, 15.2, 15.2))
        p.drawEllipse(QRectF(8.6, 8.6, 6.8, 6.8))
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(11.1, 11.1, 1.8, 1.8))

    elif name == "list":             # 清单
        for y in (7.5, 12, 16.5):
            p.drawLine(QPointF(9.5, y), QPointF(19.5, y))
            p.setBrush(QColor(color))
            p.drawEllipse(QRectF(4.8, y - 1.1, 2.2, 2.2))

    elif name == "play":             # 执行
        path = QPainterPath()
        path.moveTo(8, 5.5)
        path.lineTo(18.5, 12)
        path.lineTo(8, 18.5)
        path.closeSubpath()
        p.drawPath(path)

    elif name == "settings2":        # 调节
        for y in (7.5, 12, 16.5):
            p.drawLine(QPointF(4.5, y), QPointF(19.5, y))
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(8.6, 5.9, 3.2, 3.2))
        p.drawEllipse(QRectF(13.4, 10.4, 3.2, 3.2))
        p.drawEllipse(QRectF(7.4, 14.9, 3.2, 3.2))

    elif name == "eye":              # 预览
        path = QPainterPath()
        path.moveTo(3.6, 12)
        path.quadTo(12, 4.4, 20.4, 12)
        path.quadTo(12, 19.6, 3.6, 12)
        p.drawPath(path)
        p.drawEllipse(QRectF(9.4, 9.4, 5.2, 5.2))

    elif name == "dot":
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(9, 9, 6, 6))

    else:
        p.drawRoundedRect(QRectF(5, 5, 14, 14), 3, 3)


def icon(name: str, color: str = None, size: int = 18, width: float = 1.9) -> QIcon:
    color = color or theme.TEXT_2
    key = (name, color, size, width)
    if key in _cache:
        return _cache[key]

    scale = 3
    pm = QPixmap(size * scale, size * scale)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size * scale / S, size * scale / S)
    _draw(name, p, color)
    p.end()
    pm.setDevicePixelRatio(scale)
    ic = QIcon(pm)
    _cache[key] = ic
    return ic


def pixmap(name: str, color: str = None, size: int = 18, width: float = 1.9) -> QPixmap:
    return icon(name, color, size, width).pixmap(size, size)
