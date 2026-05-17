#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Icon Creator - 文件夹图标制作器
简化版：图标添加到画布后以200*200显示，左键拖动，滚轮缩放，无蚂蚁线和控制点
"""

import sys
import os
import re
import math
import json
import gc
import logging
import subprocess
import ctypes
from pathlib import Path
from uuid import uuid4
from math import cos, sin, radians, sqrt
from typing import Optional, Dict, List, Tuple, Iterable

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QFrame, QMessageBox, QGroupBox, QGridLayout,
    QSplitter, QLineEdit, QSlider, QScrollArea, QSizePolicy, QFileDialog,
    QListWidget, QListWidgetItem, QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QPointF, QRectF, QSize
from PyQt6.QtGui import QPixmap, QFont, QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient, QConicalGradient, QImage, QIcon, QWheelEvent, QCursor, QPixmapCache
from PyQt6.QtSvg import QSvgRenderer

from PIL import Image

# 分栏背景色
SECTION_BG = "rgb(240, 240, 240)"

# 色相滑条高度（统一）
HUE_SLIDER_HEIGHT = 204

logger = logging.getLogger(__name__)


def _safe_name(name: str) -> str:
    """将名称转换为可安全用于文件名的字符串。"""
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def _iter_existing_paths(paths: Iterable[Path]) -> List[Path]:
    """筛选出存在于磁盘上的路径列表。"""
    existing: List[Path] = []
    for path in paths:
        try:
            if path.exists():
                existing.append(path)
        except Exception:
            continue
    return existing


def _move_to_trash(paths: List[Path], trash_dir: Path) -> Tuple[bool, str, List[Tuple[Path, Path]]]:
    """将一组文件原子移动到回收站目录，返回移动映射以便回滚。"""
    moves: List[Tuple[Path, Path]] = []
    if not paths:
        return True, "no-op", moves

    try:
        trash_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.exception("创建删除回收站目录失败: %s", trash_dir)
        return False, f"无法创建临时目录：{exc}", moves

    for src in paths:
        try:
            same_drive = src.drive.lower() == trash_dir.drive.lower()
        except Exception:
            same_drive = False

        local_trash_dir = trash_dir if same_drive else (src.parent / ".trash")
        try:
            local_trash_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            logger.exception("创建删除回收站目录失败: %s", local_trash_dir)
            return False, f"无法创建临时目录：{exc}", moves

        dst = local_trash_dir / f"{src.name}.{uuid4().hex}.trash"
        try:
            os.replace(str(src), str(dst))
            moves.append((dst, src))
        except PermissionError as exc:
            logger.exception("移动到回收站失败（可能被占用）: %s", src)
            for moved_dst, original_src in reversed(moves):
                try:
                    os.replace(str(moved_dst), str(original_src))
                except Exception:
                    logger.exception("回滚失败: %s -> %s", moved_dst, original_src)
            return False, f"文件可能正在被占用，无法删除：{src}\n\n错误：{exc}", []
        except Exception as exc:
            logger.exception("移动到回收站失败: %s", src)
            for moved_dst, original_src in reversed(moves):
                try:
                    os.replace(str(moved_dst), str(original_src))
                except Exception:
                    logger.exception("回滚失败: %s -> %s", moved_dst, original_src)
            return False, f"无法删除文件：{src}\n\n错误：{exc}", []

    return True, "ok", moves


def _unlink_best_effort(paths: List[Path]) -> None:
    """尽力删除一组文件，失败仅记录日志，不抛异常。"""
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.exception("删除回收站文件失败: %s", path)


# ==================== 存档管理 ====================
class SaveManager:
    """管理自定义图标的保存和加载"""
    
    def __init__(self):
        self.save_dir = self._get_save_dir()
        try:
            os.makedirs(self.save_dir, exist_ok=True)
        except Exception as e:
            import logging
            logging.error(f"创建缓存目录失败: {e}")
            QMessageBox.critical(None, "权限错误", f"无法在目录中创建缓存文件夹，请以管理员身份运行程序。\n\n路径: {self.save_dir}\n错误信息: {e}")
        
    def _get_save_dir(self) -> str:
        """获取保存目录：同级目录下的 .cache/Save"""
        base_path = get_app_root_dir()
        return os.path.join(base_path, ".cache", "Save")
    
    def save_custom_icon(self, name: str, data: Dict) -> bool:
        """保存自定义图标配置"""
        try:
            safe_name = _safe_name(name)
            file_path = os.path.join(self.save_dir, f"{safe_name}.json")
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            logger.exception("保存自定义图标配置失败: %s", name)
            return False
    
    def load_custom_icon(self, file_path: str) -> Optional[Dict]:
        """加载单个自定义图标配置"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.exception("加载自定义图标配置失败: %s", file_path)
            return None
    
    def load_all_custom_icons(self) -> List[Tuple[str, Dict]]:
        """加载所有自定义图标配置"""
        icons = []
        try:
            for file_name in os.listdir(self.save_dir):
                if file_name.lower().endswith('.json'):
                    file_path = os.path.join(self.save_dir, file_name)
                    data = self.load_custom_icon(file_path)
                    if data:
                        name = os.path.splitext(file_name)[0]
                        icons.append((name, data))
            
            # 按修改时间排序
            icons.sort(key=lambda x: os.path.getmtime(
                os.path.join(self.save_dir, f"{x[0]}.json")
            ), reverse=True)
            
            return icons
        except Exception as e:
            logger.exception("加载所有自定义图标配置失败")
            return []
    
    def delete_custom_icon(self, name: str) -> bool:
        """删除自定义图标"""
        try:
            safe_name = _safe_name(name)
            file_path = os.path.join(self.save_dir, f"{safe_name}.json")
            
            if os.path.exists(file_path):
                os.remove(file_path)
                return True
            return False
        except Exception as e:
            logger.exception("删除自定义图标配置失败: %s", name)
            return False


# ==================== 图标叠加画布 ====================
class IconCanvasWidget(QLabel):
    """支持图标叠加、拖动、缩放的预览画布"""
    
    # 画布固定尺寸
    CANVAS_WIDTH = 320
    CANVAS_HEIGHT = 251
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.CANVAS_WIDTH, self.CANVAS_HEIGHT)
        self.setStyleSheet("background: transparent;")
        self.setMouseTracking(True)
        
        # SVG背景图
        self.svg_pixmap = None
        
        # 图标相关
        self.icon_pixmap = None  # 原始图标图像
        self.icon_path = ""  # 图标路径（用于存档）
        self.icon_pos = QPointF(self.CANVAS_WIDTH / 2, self.CANVAS_HEIGHT / 2)  # 图标中心位置
        self.icon_scale = 1.0  # 统一缩放比例
        self.icon_opacity = 100  # 图标透明度
        
        # 交互状态
        self.dragging = False
        self.drag_offset = QPointF()
        
        # 图标是否可见
        self.icon_visible = False
        
        # 右键标记
        self.show_center_mark = False
        self.center_mark_pos = QPointF()
        self.center_mark_timer = QTimer(self)
        self.center_mark_timer.setSingleShot(True)
        self.center_mark_timer.timeout.connect(self._hide_center_mark)
        
        # 缩放锚点（右键设置的位置，用于缩放中心）
        self.scale_anchor = None  # None 表示使用 icon_pos 作为缩放中心
    
    def set_svg_pixmap(self, pixmap):
        """设置SVG背景图"""
        self.svg_pixmap = pixmap
        self._update_display()
    
    def set_icon(self, pixmap, path=""):
        """设置图标 - 强制以200*200显示，放置在画布中心"""
        self.icon_pixmap = pixmap
        self.icon_path = path
        if pixmap:
            self.icon_visible = True
            # 强制图标缩放到200*200
            target_size = 200
            # 计算缩放比例，使图标填充200*200
            self.icon_scale = target_size / max(pixmap.width(), pixmap.height())
            # 将图标放置到画布正中心
            self.icon_pos = QPointF(self.CANVAS_WIDTH / 2, self.CANVAS_HEIGHT / 2)
            # 清除缩放锚点
            self.scale_anchor = None
        self._update_display()
    
    def set_icon_opacity(self, opacity: int):
        """设置图标透明度 (0-100)"""
        self.icon_opacity = opacity
        self._update_display()
    
    def clear_icon(self):
        """清除图标"""
        self.icon_pixmap = None
        self.icon_path = ""
        self.icon_visible = False
        self.scale_anchor = None
        self._update_display()
    
    def _hide_center_mark(self):
        """隐藏中心标记"""
        self.show_center_mark = False
        self._update_display()
    
    def _set_center_at_pos(self, pos):
        """将右键点击位置设置为缩放锚点"""
        if not self.icon_visible or self.icon_pixmap is None:
            return
        
        # 设置缩放锚点（画布坐标）
        self.scale_anchor = QPointF(pos)
        
        # 计算锚点相对于图标中心的归一化偏移
        # 归一化 = 偏移 / 当前缩放尺寸
        current_size = max(self.icon_pixmap.width(), self.icon_pixmap.height()) * self.icon_scale
        self.anchor_offset_normalized = QPointF(
            (pos.x() - self.icon_pos.x()) / current_size,
            (pos.y() - self.icon_pos.y()) / current_size
        )
        
        # 显示+号标记
        self.center_mark_pos = QPointF(pos)
        self.show_center_mark = True
        self.center_mark_timer.start(100)  # 0.1秒 = 100毫秒
        self._update_display()
    
    def get_icon_transform(self):
        """获取图标的变换信息（用于存档）"""
        return {
            "path": self.icon_path,
            "position": [self.icon_pos.x(), self.icon_pos.y()],
            "scale": self.icon_scale,
            "opacity": self.icon_opacity
        }
    
    def load_icon_transform(self, data: dict):
        """从存档数据加载图标变换"""
        if "position" in data:
            self.icon_pos = QPointF(data["position"][0], data["position"][1])
        if "scale" in data:
            self.icon_scale = data["scale"]
        if "opacity" in data:
            self.icon_opacity = data["opacity"]
        self._update_display()
    
    def _update_display(self):
        """更新显示"""
        if not self.svg_pixmap and not self.icon_pixmap:
            self.clear()
            return
        
        # 创建合成图像（使用固定尺寸，避免初始化问题）
        canvas = QPixmap(self.CANVAS_WIDTH, self.CANVAS_HEIGHT)
        canvas.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # 绘制SVG背景
        if self.svg_pixmap:
            scaled_svg = self.svg_pixmap.scaled(
                self.CANVAS_WIDTH, self.CANVAS_HEIGHT,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            x = (self.CANVAS_WIDTH - scaled_svg.width()) / 2
            y = (self.CANVAS_HEIGHT - scaled_svg.height()) / 2
            painter.drawPixmap(int(x), int(y), scaled_svg)
        
        # 绘制图标
        if self.icon_pixmap and self.icon_visible:
            # 计算缩放后的尺寸（强制等比缩放，保持宽高比）
            scaled_w = int(self.icon_pixmap.width() * self.icon_scale)
            scaled_h = int(self.icon_pixmap.height() * self.icon_scale)
            
            scaled_icon = self.icon_pixmap.scaled(
                scaled_w, scaled_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            painter.setOpacity(self.icon_opacity / 100.0)
            
            # 计算图标绘制位置（以icon_pos为中心）
            # 使用实际缩放后的尺寸来计算中心位置
            actual_w = scaled_icon.width()
            actual_h = scaled_icon.height()
            draw_x = self.icon_pos.x() - actual_w / 2
            draw_y = self.icon_pos.y() - actual_h / 2
            
            painter.drawPixmap(int(draw_x), int(draw_y), scaled_icon)
            painter.setOpacity(1.0)
        
        # 绘制中心标记（+号）
        if self.show_center_mark:
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(self.center_mark_pos.x(), self.center_mark_pos.y()), 8, 8)
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            painter.drawEllipse(QPointF(self.center_mark_pos.x(), self.center_mark_pos.y()), 8, 8)
            # 绘制横线
            painter.drawLine(int(self.center_mark_pos.x() - 10), int(self.center_mark_pos.y()), 
                           int(self.center_mark_pos.x() + 10), int(self.center_mark_pos.y()))
            # 绘制竖线
            painter.drawLine(int(self.center_mark_pos.x()), int(self.center_mark_pos.y() - 10), 
                           int(self.center_mark_pos.x()), int(self.center_mark_pos.y() + 10))
        
        painter.end()
        self.setPixmap(canvas)
    
    def mousePressEvent(self, event):
        """鼠标按下事件 - 左键开始拖动图标"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.icon_visible:
                self.dragging = True
                self.drag_offset = QPointF(event.position().x() - self.icon_pos.x(),
                                          event.position().y() - self.icon_pos.y())
    
    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 拖动图标"""
        if self.dragging and self.icon_visible:
            self.icon_pos = QPointF(event.position().x() - self.drag_offset.x(),
                                   event.position().y() - self.drag_offset.y())
            # 拖动时更新锚点的归一化偏移（保持锚点在画布上的位置）
            if self.scale_anchor is not None and self.icon_pixmap is not None:
                current_size = max(self.icon_pixmap.width(), self.icon_pixmap.height()) * self.icon_scale
                self.anchor_offset_normalized = QPointF(
                    (self.scale_anchor.x() - self.icon_pos.x()) / current_size,
                    (self.scale_anchor.y() - self.icon_pos.y()) / current_size
                )
            self._update_display()
    
    def mouseReleaseEvent(self, event):
        """鼠标释放事件 - 结束拖动"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
    
    def contextMenuEvent(self, event):
        """右键菜单事件 - 将图标中心移动到右键位置"""
        if self.icon_visible:
            self._set_center_at_pos(event.pos())
    
    def wheelEvent(self, event):
        """鼠标滚轮事件 - 缩放图标（以锚点为中心）"""
        if not self.icon_visible or self.icon_pixmap is None:
            return
        
        # 获取滚轮滚动方向
        delta = event.angleDelta().y()
        
        # 计算新的缩放比例
        scale_factor = 1.1 if delta > 0 else 0.9
        new_scale = self.icon_scale * scale_factor
        
        # 限制最小缩放（不限制最大）
        new_scale = max(0.1, new_scale)
        
        # 如果有缩放锚点，调整图标位置使锚点保持不变
        if self.scale_anchor is not None:
            # 新的图标尺寸
            new_size = max(self.icon_pixmap.width(), self.icon_pixmap.height()) * new_scale
            # 新的图标中心位置 = 锚点位置 - 归一化偏移 * 新尺寸
            self.icon_pos = QPointF(
                self.scale_anchor.x() - self.anchor_offset_normalized.x() * new_size,
                self.scale_anchor.y() - self.anchor_offset_normalized.y() * new_size
            )
        
        self.icon_scale = new_scale
        self._update_display()
    
    def compose_final_image(self, size=64):
        """合成最终图像（用于保存）"""
        canvas = QPixmap(size, size)
        canvas.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        
        # 绘制SVG背景
        if self.svg_pixmap:
            svg_scaled = self.svg_pixmap.scaled(
                size, size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            x = (size - svg_scaled.width()) / 2
            y = (size - svg_scaled.height()) / 2
            painter.drawPixmap(int(x), int(y), svg_scaled)
        
        # 绘制图标
        if self.icon_pixmap and self.icon_visible:
            # 保持原来的尺寸计算
            scale_factor = size / self.CANVAS_WIDTH
            scaled_w = int(self.icon_pixmap.width() * self.icon_scale * scale_factor)
            scaled_h = int(self.icon_pixmap.height() * self.icon_scale * scale_factor)
            
            scaled_icon = self.icon_pixmap.scaled(
                scaled_w, scaled_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            
            painter.setOpacity(self.icon_opacity / 100.0)
            
            # 修正Y方向映射：让画布中心正确映射到输出中心
            # X方向直接缩放
            icon_x = self.icon_pos.x() * scale_factor
            # Y方向需要考虑画布高度与输出尺寸的差异
            # 画布中心 (125.5) 应该映射到输出中心 (32)
            # 所以 Y 输出 = (icon_y - 画布中心Y) * 缩放 + 输出中心
            canvas_center_y = self.CANVAS_HEIGHT / 2
            output_center = size / 2
            icon_y = output_center + (self.icon_pos.y() - canvas_center_y) * scale_factor
            
            painter.drawPixmap(
                int(icon_x - scaled_icon.width() / 2),
                int(icon_y - scaled_icon.height() / 2),
                scaled_icon
            )
        
        painter.end()
        return canvas


# ==================== 资源路径处理 ====================
def get_app_dir() -> str:
    """获取程序数据目录（强制位于 EXE 同级）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_app_root_dir() -> str:
    """获取应用根目录（当 exe 位于 bin 子目录时，根目录为其父目录）。"""
    base_dir = get_app_dir()
    if os.path.basename(base_dir).lower() == "bin":
        return os.path.dirname(base_dir)
    return base_dir

def get_resource_dir() -> str:
    """获取只读资源目录（优先使用 _MEIPASS）"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path: str) -> str:
    # 1. 优先尝试从 exe 同级的 ico/CustomIco 查找用户自定义替换的资源（比如 base.svg）
    app_base = get_app_root_dir()
    custom_path = os.path.join(app_base, "ico", "CustomIco", relative_path)
    if os.path.exists(custom_path):
        return custom_path
    
    # 2. 从打包资源中查找
    res_base = get_resource_dir()
    return os.path.join(res_base, relative_path)


# ==================== 颜色工具 ====================
def hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def increase_brightness(hex_color: str, amount: int = 10) -> str:
    """增加亮度（使用HSV空间，保持色调不变）"""
    color = QColor(hex_color)
    h, s, v, _ = color.getHsv()
    v = min(255, v + amount)
    return QColor.fromHsv(h, s, v).name().upper()


# ==================== SVG 颜色修改器 ====================
class SVGColorModifier:
    @staticmethod
    def load_base_svg() -> Optional[str]:
        filepath = get_resource_path('base.svg')
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            print(f"加载 base.svg 失败: {e}")
            return None

    @staticmethod
    def apply_colors(svg_content: str, background_color: str,
                     gradient1_start: str, gradient1_end: str) -> str:
        result = svg_content

        # 背景颜色替换 - 匹配 #fcbc19 或 #FCBC19
        result = re.sub(r'fill\s*=\s*["\']?\s*#fcbc19\s*["\']?', f'fill="{background_color}"', result, flags=re.IGNORECASE)
        result = re.sub(r'fill\s*:\s*#fcbc19\b', f'fill: {background_color}', result, flags=re.IGNORECASE)

        # 渐变起始颜色替换 - 匹配 #ffe7a2 或 #FFE7A2
        result = re.sub(r'stop-color\s*=\s*["\']?\s*#ffe7a2\s*["\']?', f'stop-color="{gradient1_start}"', result, flags=re.IGNORECASE)
        result = re.sub(r'stop-color\s*:\s*#ffe7a2\b', f'stop-color: {gradient1_start}', result, flags=re.IGNORECASE)

        # 渐变结束颜色替换 - 匹配 #ffcb3d 或 #FFCB3D
        result = re.sub(r'stop-color\s*=\s*["\']?\s*#ffcb3d\s*["\']?', f'stop-color="{gradient1_end}"', result, flags=re.IGNORECASE)
        result = re.sub(r'stop-color\s*:\s*#ffcb3d\b', f'stop-color: {gradient1_end}', result, flags=re.IGNORECASE)

        # 第二组渐变颜色 - #ffcf4e 和 #ffb504
        g2s = increase_brightness(gradient1_start, 10)
        g2e = increase_brightness(gradient1_end, 10)
        result = re.sub(r'stop-color\s*=\s*["\']?\s*#ffcf4e\s*["\']?', f'stop-color="{g2s}"', result, flags=re.IGNORECASE)
        result = re.sub(r'stop-color\s*:\s*#ffcf4e\b', f'stop-color: {g2s}', result, flags=re.IGNORECASE)
        result = re.sub(r'stop-color\s*=\s*["\']?\s*#ffb504\s*["\']?', f'stop-color="{g2e}"', result, flags=re.IGNORECASE)
        result = re.sub(r'stop-color\s*:\s*#ffb504\b', f'stop-color: {g2e}', result, flags=re.IGNORECASE)

        # 第三组渐变颜色 - #ffecb5 和 #ffde82
        g3s = increase_brightness(gradient1_start, 20)
        g3e = increase_brightness(gradient1_end, 20)
        result = re.sub(r'stop-color\s*=\s*["\']?\s*#ffecb5\s*["\']?', f'stop-color="{g3s}"', result, flags=re.IGNORECASE)
        result = re.sub(r'stop-color\s*:\s*#ffecb5\b', f'stop-color: {g3s}', result, flags=re.IGNORECASE)
        result = re.sub(r'stop-color\s*=\s*["\']?\s*#ffde82\s*["\']?', f'stop-color="{g3e}"', result, flags=re.IGNORECASE)
        result = re.sub(r'stop-color\s*:\s*#ffde82\b', f'stop-color: {g3e}', result, flags=re.IGNORECASE)

        return result


# ==================== 方形颜色选择器（饱和度×明度）====================
class SquareColorPicker(QLabel):
    """方形颜色选择器：水平=饱和度，垂直=明度"""
    color_selected = pyqtSignal(int, int)
    
    def __init__(self, size=180):
        super().__init__()
        self.picker_size = size
        self.setFixedSize(size, size)
        self.hue = 0
        self.saturation = 100
        self.lightness = 50
        self._render_picker()
        self.setCursor(Qt.CursorShape.CrossCursor)
    
    def _render_picker(self):
        pixmap = QPixmap(self.picker_size, self.picker_size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        for x in range(self.picker_size):
            for y in range(self.picker_size):
                s = int((x / self.picker_size) * 255)
                l = int(255 - (y / self.picker_size) * 255)
                color = QColor.fromHsv(self.hue, s, l)
                painter.setPen(QPen(color))
                painter.drawPoint(x, y)
        
        indicator_x = int((self.saturation / 100) * self.picker_size)
        indicator_y = int((100 - self.lightness) / 100 * self.picker_size)
        
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(indicator_x, indicator_y), 8, 8)
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.drawEllipse(QPointF(indicator_x, indicator_y), 8, 8)
        
        painter.end()
        self.setPixmap(pixmap)
    
    def mousePressEvent(self, event):
        self._pick_color(event.position())
    
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._pick_color(event.position())
    
    def _pick_color(self, pos):
        x = max(0, min(self.picker_size, int(pos.x())))
        y = max(0, min(self.picker_size, int(pos.y())))
        
        self.saturation = int((x / self.picker_size) * 100)
        self.lightness = int(100 - (y / self.picker_size) * 100)
        
        self._render_picker()
        self.color_selected.emit(self.saturation, self.lightness)
    
    def set_hue(self, hue):
        self.hue = hue % 360
        self._render_picker()
    
    def set_saturation(self, saturation):
        self.saturation = max(0, min(100, saturation))
        self._render_picker()
    
    def set_lightness(self, lightness):
        self.lightness = max(0, min(100, lightness))
        self._render_picker()
    
    def get_size(self):
        return self.picker_size


# ==================== 竖向色相滑条 ====================
class HueSliderVertical(QSlider):
    """竖向色相滑条 (0-359)"""
    value_changed = pyqtSignal(int)
    
    def __init__(self):
        super().__init__(Qt.Orientation.Vertical)
        self.setRange(0, 359)
        self.setValue(0)
        self.setFixedWidth(24)
        self.setFixedHeight(HUE_SLIDER_HEIGHT)
        self._update_style()
        self.valueChanged.connect(self._on_value_changed)
    
    def _update_style(self):
        self.setStyleSheet("""
            QSlider::groove:vertical {
                width: 16px;
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:1, x2:0, y2:0,
                    stop:0 #ff0000, stop:0.167 #ffff00, stop:0.333 #00ff00,
                    stop:0.5 #00ffff, stop:0.667 #0000ff, stop:0.833 #ff00ff,
                    stop:1 #ff0000);
            }
            QSlider::handle:vertical {
                width: 18px;
                height: 18px;
                margin: 0 -2px;
                background: white;
                border: 2px solid #333;
                border-radius: 9px;
            }
            QSlider::handle:vertical:hover {
                background: #f0f0f0;
            }
        """)
    
    def _on_value_changed(self, value):
        self.value_changed.emit(value)
    
    def wheelEvent(self, event):
        """禁用滚轮事件，防止崩溃"""
        event.ignore()


# ==================== HSL 滑条 ====================
class SaturationSliderVertical(QSlider):
    """竖向饱和度滑条 (0-100)"""
    value_changed = pyqtSignal(int)
    
    def __init__(self):
        super().__init__(Qt.Orientation.Vertical)
        self.setRange(0, 100)
        self.setValue(100)
        self.setFixedWidth(24)
        self.setFixedHeight(HUE_SLIDER_HEIGHT)
        self._hue = 0
        self._update_style()
        self.valueChanged.connect(self._on_value_changed)
    
    def set_hue(self, hue):
        self._hue = hue
        self._update_style()
    
    def _update_style(self):
        pure_color = QColor.fromHsv(self._hue, 255, 255).name()
        self.setStyleSheet(f"""
            QSlider::groove:vertical {{
                width: 16px;
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:1, x2:0, y2:0,
                    stop:0 #ffffff, stop:1 {pure_color});
            }}
            QSlider::handle:vertical {{
                width: 18px;
                height: 18px;
                margin: 0 -2px;
                background: white;
                border: 2px solid #333;
                border-radius: 9px;
            }}
            QSlider::handle:vertical:hover {{
                background: #f0f0f0;
            }}
        """)
    
    def _on_value_changed(self, value):
        self.value_changed.emit(value)
    
    def mousePressEvent(self, event):
        """点击滑条任意位置直接跳转"""
        from PyQt6.QtWidgets import QStyleOptionSlider, QStyle
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self)
        if rect.contains(event.pos()):
            super().mousePressEvent(event)
            return
        # 竖向滑条，使用y坐标
        value = self.style().sliderValueFromPosition(self.minimum(), self.maximum(), event.pos().y(), self.height(), True)
        self.setValue(value)
        super().mousePressEvent(event)
    
    def wheelEvent(self, event):
        """禁用滚轮事件，防止崩溃"""
        event.ignore()


class LightnessSliderVertical(QSlider):
    """竖向明度滑条 (0-100)"""
    value_changed = pyqtSignal(int)
    
    def __init__(self):
        super().__init__(Qt.Orientation.Vertical)
        self.setRange(0, 100)
        self.setValue(50)
        self.setFixedWidth(24)
        self.setFixedHeight(HUE_SLIDER_HEIGHT)
        self._hue = 0
        self._saturation = 100
        self._update_style()
        self.valueChanged.connect(self._on_value_changed)
    
    def set_hsl(self, hue, saturation):
        self._hue = hue
        self._saturation = saturation
        self._update_style()
    
    def _update_style(self):
        dark_color = QColor.fromHsv(self._hue, int(self._saturation * 2.55), 0).name()
        mid_color = QColor.fromHsv(self._hue, int(self._saturation * 2.55), 255).name()
        light_color = QColor.fromHsv(self._hue, 0, 255).name()
        self.setStyleSheet(f"""
            QSlider::groove:vertical {{
                width: 16px;
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:1, x2:0, y2:0,
                    stop:0 {dark_color}, stop:0.5 {mid_color}, stop:1 {light_color});
            }}
            QSlider::handle:vertical {{
                width: 18px;
                height: 18px;
                margin: 0 -2px;
                background: white;
                border: 2px solid #333;
                border-radius: 9px;
            }}
            QSlider::handle:vertical:hover {{
                background: #f0f0f0;
            }}
        """)
    
    def _on_value_changed(self, value):
        self.value_changed.emit(value)
    
    def mousePressEvent(self, event):
        """点击滑条任意位置直接跳转"""
        from PyQt6.QtWidgets import QStyleOptionSlider, QStyle
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        rect = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self)
        if rect.contains(event.pos()):
            super().mousePressEvent(event)
            return
        # 竖向滑条，使用y坐标
        value = self.style().sliderValueFromPosition(self.minimum(), self.maximum(), event.pos().y(), self.height(), True)
        self.setValue(value)
        super().mousePressEvent(event)
    
    def wheelEvent(self, event):
        """禁用滚轮事件，防止崩溃"""
        event.ignore()


# ==================== SVG 渲染器 ====================
class SVGRenderer:
    @staticmethod
    def render_to_pixmap(svg_content: str, width: int = 320, height: int = 251) -> Optional[QPixmap]:
        try:
            renderer = QSvgRenderer()
            renderer.load(svg_content.encode('utf-8'))
            if not renderer.isValid():
                return None
            pixmap = QPixmap(width, height)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()
            return pixmap
        except Exception:
            return None


# ==================== 预设按钮（SVG 预览） ====================
class PresetButton(QLabel):
    clicked = pyqtSignal()
    delete_requested = pyqtSignal(object)  # 删除请求信号

    def __init__(self, bg: str, start: str, end: str, svg_template: str, is_custom: bool = False):
        super().__init__()
        self.bg_color = bg
        self.start_color = start
        self.end_color = end
        self.svg_template = svg_template
        self.is_custom = is_custom  # 是否为自定义预设
        self.setFixedSize(60, 47)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._render_preview()

    def _render_preview(self):
        if not self.svg_template:
            return
        svg_content = SVGColorModifier.apply_colors(
            self.svg_template, self.bg_color, self.start_color, self.end_color
        )
        pix = SVGRenderer.render_to_pixmap(svg_content, 60, 47)
        if pix:
            self.setPixmap(pix)

    def enterEvent(self, event):
        self.setStyleSheet("border: 2px solid #2196f3; border-radius: 6px;")
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet("")
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        """右键菜单 - 仅对自定义预设显示删除选项"""
        if not self.is_custom:
            return
        
        menu = RoundedMenu(self)
        delete_action = menu.addAction("🗑️ 删除预设")
        delete_action.triggered = lambda: self.delete_requested.emit(self)
        menu.exec(event.globalPos())


# ==================== 圆角菜单 ====================
class RoundedMenu(QWidget):
    """自定义圆角菜单，解决原生QMenu圆角显示问题"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Popup |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setMouseTracking(True)  # 启用鼠标追踪，实现悬停高亮
        
        self.actions = []  # 存储 (text, callback) 元组
        self.hovered_index = -1
        self.item_height = 36
        self.border_radius = 6
        self.padding = 8
        
    def addAction(self, text: str):
        """添加菜单项，返回一个可设置callback的对象"""
        action = type('Action', (), {'text': text, 'triggered': None})()
        self.actions.append(action)
        return action
    
    def exec(self, pos):
        if not self.actions:
            return
        
        # 计算菜单尺寸
        font_metrics = self.fontMetrics()
        max_text_width = max(font_metrics.horizontalAdvance(a.text) for a in self.actions)
        max_width = max_text_width + 40  # 左右padding
        total_height = len(self.actions) * self.item_height + self.padding * 2
        
        self.setFixedSize(max_width, total_height)
        self.move(pos)
        self.show()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 绘制圆角背景
        rect = self.rect()
        painter.setPen(QPen(QColor("#e0e0e0"), 1))
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawRoundedRect(rect.x() + 1, rect.y() + 1, 
                                rect.width() - 2, rect.height() - 2,
                                self.border_radius, self.border_radius)
        
        # 绘制菜单项
        for i, action in enumerate(self.actions):
            y = self.padding + i * self.item_height
            item_rect = QRectF(self.padding, y, 
                              self.width() - self.padding * 2, self.item_height)
            
            if i == self.hovered_index:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#ffebee")))
                painter.drawRoundedRect(item_rect, 4, 4)
                painter.setPen(QColor("#e53935"))
            else:
                painter.setPen(QColor("#333333"))
            
            # 绘制文字，使用左对齐并留出左边距
            text_rect = QRectF(self.padding + 12, y, 
                              self.width() - self.padding * 2 - 24, self.item_height)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, action.text)
    
    def mouseMoveEvent(self, event):
        pos = event.pos()
        self.hovered_index = (pos.y() - self.padding) // self.item_height
        if self.hovered_index < 0 or self.hovered_index >= len(self.actions):
            self.hovered_index = -1
        self.update()
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = (event.pos().y() - self.padding) // self.item_height
            if 0 <= index < len(self.actions):
                # triggered 是 lambda 函数，直接调用
                if callable(self.actions[index].triggered):
                    self.actions[index].triggered()
        self.close()


# ==================== 颜色代码输入框 ====================
class ColorCodeInput(QLineEdit):
    """16进制颜色代码输入框"""
    color_changed = pyqtSignal(str)
    
    def __init__(self, initial_color: str = "#FFFFFF"):
        super().__init__()
        self.current_color = initial_color.upper()
        self.setText(self.current_color)
        self.setFixedHeight(24)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            QLineEdit {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 12px;
                font-family: Consolas, Monaco, monospace;
                background: #fff;
            }
            QLineEdit:focus {
                border: 2px solid #2196f3;
            }
        """)
        self.editingFinished.connect(self._on_edit_finished)
    
    def _on_edit_finished(self):
        text = self.text().strip()
        # 验证并格式化颜色代码
        if not text.startswith('#'):
            text = '#' + text
        
        # 支持3位或6位十六进制
        if len(text) == 4:  # #RGB -> #RRGGBB
            text = '#' + text[1]*2 + text[2]*2 + text[3]*2
        elif len(text) != 7:
            self.setText(self.current_color)
            return
        
        try:
            # 验证是否为有效的十六进制颜色
            int(text[1:], 16)
            self.current_color = text.upper()
            self.setText(self.current_color)
            self.color_changed.emit(self.current_color)
        except ValueError:
            self.setText(self.current_color)
    
    def set_color(self, color: str):
        self.current_color = color.upper()
        self.setText(self.current_color)


# ==================== 颜色拾取器窗口 ====================
class ColorPickerWindow(QWidget):
    """跟随光标的颜色拾取小窗口"""
    color_picked = pyqtSignal(str)  # 颜色被选取时发出
    
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.ToolTip
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(80, 30)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        
        # 颜色预览
        self.color_preview = QLabel()
        self.color_preview.setFixedSize(20, 20)
        self.color_preview.setStyleSheet("border: 1px solid #333; border-radius: 2px;")
        
        # 颜色文本
        self.color_text = QLabel("#FFFFFF")
        self.color_text.setStyleSheet("font-size: 11px; color: #333; background: white; padding: 2px 4px; border-radius: 2px;")
        self.color_text.setFont(QFont("Consolas", 9))
        
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(4)
        h_layout.addWidget(self.color_preview)
        h_layout.addWidget(self.color_text)
        layout.addLayout(h_layout)
        
        self.current_color = "#FFFFFF"
        self.active = False
        
        # 定时器用于跟踪鼠标
        self.track_timer = QTimer(self)
        self.track_timer.timeout.connect(self._update_position_and_color)
    
    def start_picking(self):
        """开始取色"""
        self.active = True
        self.show()
        self.track_timer.start(30)  # 30ms更新一次
        self._update_position_and_color()
    
    def stop_picking(self, apply: bool = False):
        """停止取色"""
        self.active = False
        self.track_timer.stop()
        self.hide()
        if apply:
            self.color_picked.emit(self.current_color)
    
    def _update_position_and_color(self):
        """更新窗口位置和颜色"""
        if not self.active:
            return
        
        # 获取全局鼠标位置
        cursor_pos = QCursor.pos()
        
        # 移动窗口到光标右下方
        self.move(cursor_pos.x() + 15, cursor_pos.y() + 15)
        
        # 获取屏幕颜色
        screen = QApplication.primaryScreen()
        if screen:
            pixmap = screen.grabWindow(0, cursor_pos.x(), cursor_pos.y(), 1, 1)
            image = pixmap.toImage()
            color = image.pixelColor(0, 0)
            self.current_color = color.name().upper()
            self.color_preview.setStyleSheet(f"background: {self.current_color}; border: 1px solid #333; border-radius: 2px;")
            self.color_text.setText(self.current_color)


# ==================== 取色按钮 ====================
class PickColorButton(QLabel):
    """右上角的取色按钮"""
    clicked = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText("✎")
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QLabel {
                color: #666;
                font-size: 12px;
                background: transparent;
            }
            QLabel:hover {
                color: #2196f3;
            }
        """)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


# ==================== 整体调整按钮（SVG预览，无输入框）====================
class OverallColorBlock(QWidget):
    clicked = pyqtSignal()
    pick_color_requested = pyqtSignal()  # 取色请求

    def __init__(self, control_panel=None):
        super().__init__()
        self.control_panel = control_panel
        self.is_selected = False
        self.svg_template = None
        self.current_svg = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 预览标签容器（用于放置预览和取色按钮）
        preview_container = QWidget()
        preview_container.setFixedSize(78, 61)
        
        self.preview_label = QLabel(preview_container)
        self.preview_label.setGeometry(0, 0, 78, 61)
        self.preview_label.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # 右上角取色按钮
        self.pick_btn = PickColorButton(preview_container)
        self.pick_btn.move(78 - 20, 2)
        self.pick_btn.clicked.connect(self._on_pick_clicked)
        
        layout.addWidget(preview_container, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self._update_style()

    def _on_pick_clicked(self):
        """取色按钮点击"""
        self.pick_color_requested.emit()

    def set_svg_template(self, svg_template: str):
        self.svg_template = svg_template
        self._render_preview()

    def update_svg(self, svg_content: str):
        self.current_svg = svg_content
        self._render_preview()

    def _render_preview(self):
        if self.current_svg:
            pix = SVGRenderer.render_to_pixmap(self.current_svg, 78, 61)  # 14:11比例
            if pix:
                self.preview_label.setPixmap(pix)
                self._update_style()

    def _update_style(self):
        if self.is_selected:
            self.preview_label.setStyleSheet("""
                QLabel {
                    background-color: rgba(33, 150, 243, 0.15);
                    border: 3px solid #2196f3;
                    border-radius: 8px;
                }
            """)
        else:
            self.preview_label.setStyleSheet("""
                QLabel {
                    background-color: transparent;
                    border: 2px solid #bbb;
                    border-radius: 8px;
                }
                QLabel:hover {
                    border: 3px solid #2196f3;
                }
            """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()
    
    def set_color(self, color: str):
        """兼容接口，整体调整块不需要设置颜色"""
        pass


# ==================== 颜色选择块（带颜色输入框）====================
class ColorBlock(QWidget):
    color_changed = pyqtSignal(str)
    pick_color_requested = pyqtSignal()  # 取色请求

    def __init__(self, color: str, label: str, control_panel=None):
        super().__init__()
        self.current_color = color.upper()
        self.label_text = label
        self.is_selected = False
        self.control_panel = control_panel
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # 颜色按钮容器（用于放置按钮和取色按钮）
        btn_container = QWidget()
        btn_container.setFixedSize(78, 40)
        
        self.color_btn = QPushButton(btn_container)
        self.color_btn.setGeometry(0, 0, 78, 40)
        self.color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color_btn.mousePressEvent = self._on_btn_clicked
        
        # 右上角取色按钮
        self.pick_btn = PickColorButton(btn_container)
        self.pick_btn.move(78 - 20, 2)
        self.pick_btn.clicked.connect(self._on_pick_clicked)
        
        layout.addWidget(btn_container, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self.color_input = ColorCodeInput(color)
        self.color_input.setFixedWidth(78)
        self.color_input.color_changed.connect(self._on_color_input_changed)
        layout.addWidget(self.color_input, alignment=Qt.AlignmentFlag.AlignCenter)
        
        self._update_style()

    def _on_pick_clicked(self):
        """取色按钮点击"""
        self.pick_color_requested.emit()

    def _update_style(self):
        if self.is_selected:
            self.color_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.current_color};
                    border: 3px solid #2196f3;
                    border-radius: 8px;
                }}
                QPushButton:hover {{
                    border: 3px solid #2196f3;
                }}
            """)
        else:
            self.color_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.current_color};
                    border: 2px solid #bbb;
                    border-radius: 8px;
                }}
                QPushButton:hover {{
                    border: 3px solid #2196f3;
                }}
            """)

    def _on_btn_clicked(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.control_panel and hasattr(self.control_panel, 'deselect_all'):
                self.control_panel.deselect_all()
            self.is_selected = True
            self._update_style()
            if self.control_panel and hasattr(self.control_panel, 'gradient_locked'):
                if self.control_panel.gradient_locked and self in (self.control_panel.start_block, self.control_panel.end_block):
                    self.control_panel.start_block.is_selected = True
                    self.control_panel.end_block.is_selected = True
                    self.control_panel.start_block._update_style()
                    self.control_panel.end_block._update_style()
            if self.control_panel:
                self.control_panel.sync_color_to_palette(self.current_color)
            self.color_changed.emit(self.current_color)
        QPushButton.mousePressEvent(self.color_btn, event)

    def _on_color_input_changed(self, color: str):
        self.current_color = color.upper()
        self._update_style()
        if self.control_panel:
            self.control_panel.sync_color_to_palette(self.current_color)
        self.color_changed.emit(self.current_color)

    def set_color(self, color: str):
        self.current_color = color.upper()
        self.color_input.set_color(self.current_color)
        self._update_style()

    def set_selected(self, selected: bool):
        self.is_selected = selected
        self._update_style()

    def get_color(self) -> str:
        return self.current_color


# ==================== 控制面板内容（可滚动部分）====================
class ControlPanelContent(QWidget):
    colors_changed = pyqtSignal(str, str, str)
    save_custom_requested = pyqtSignal()  # 保存自定义图标请求

    @staticmethod
    def _get_cache_path():
        """获取缓存文件路径（软件同目录的.cache文件夹）"""
        try:
            base_path = get_app_root_dir()
            cache_dir = os.path.join(base_path, ".cache")
            os.makedirs(cache_dir, exist_ok=True)
            return os.path.join(cache_dir, "preset_cache.json")
        except Exception:
            return "preset_cache.json"
    
    def __init__(self):
        super().__init__()
        self.bg_block = None
        self.start_block = None
        self.end_block = None
        self.overall_block = None
        self.svg_template = None
        self.preset_buttons = []
        self._updating_palette = False
        self.custom_presets = []  # 用户自定义预设
        self._load_preset_cache()
        
        # 颜色拾取器
        self.color_picker = ColorPickerWindow()
        self.color_picker.color_picked.connect(self._on_color_picked)
        self.picking_target = None  # 当前取色目标
        
        self._init_ui()
    
    def _load_preset_cache(self):
        """从缓存文件加载用户自定义预设"""
        try:
            cache_path = self._get_cache_path()
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    self.custom_presets = json.load(f)
        except Exception:
            self.custom_presets = []
    
    def _save_preset_cache(self):
        """保存用户自定义预设到缓存文件"""
        try:
            cache_path = self._get_cache_path()
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(self.custom_presets, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def set_svg_template(self, svg_content: str):
        self.svg_template = svg_content
        if self.overall_block:
            self.overall_block.set_svg_template(svg_content)
            self.overall_block.update_svg(svg_content)
        for btn in self.preset_buttons:
            btn.svg_template = svg_content
            btn._render_preview()

    def update_overall_preview(self, svg_content: str):
        if self.overall_block:
            self.overall_block.update_svg(svg_content)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # ==================== 颜色调整区域 ====================
        color_group = QGroupBox()
        color_group.setStyleSheet(f"""
            QGroupBox {{
                border: none;
                border-radius: 8px;
                background: {SECTION_BG};
                margin: 0px;
            }}
        """)
        color_layout = QVBoxLayout(color_group)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(0)

        color_header = QLabel("🎨 颜色调整")
        color_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        color_header.setStyleSheet("""
            QLabel {
                background: #e0e0e0;
                color: #333333;
                font-weight: bold;
                font-size: 14px;
                padding: 12px 16px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
        """)
        color_layout.addWidget(color_header)

        color_content = QWidget()
        color_content.setStyleSheet(f"background: {SECTION_BG}; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;")
        content_layout = QVBoxLayout(color_content)
        content_layout.setContentsMargins(16, 12, 16, 12)

        grid = QGridLayout()
        grid.setSpacing(10)

        # 第一行：整体调整 + (空白) + 背景颜色（与渐变结束对齐）
        overall_label = QLabel("整体调整")
        overall_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overall_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
        self.overall_block = OverallColorBlock(self)
        self.overall_block.clicked.connect(self._on_overall_clicked)
        grid.addWidget(overall_label, 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.overall_block, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        # 连接整体调整的取色信号
        self.overall_block.pick_color_requested.connect(lambda: self._start_picking('overall'))

        bg_label = QLabel("背景颜色")
        bg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bg_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
        self.bg_block = ColorBlock("#FCBC19", "背景", self)
        self.bg_block.color_changed.connect(self._on_color_changed)
        self.bg_block.pick_color_requested.connect(lambda: self._start_picking('bg'))
        grid.addWidget(bg_label, 0, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.bg_block, 1, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        # 第二行：渐变起始 + 锁 + 渐变结束
        start_label = QLabel("渐变起始")
        start_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        start_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
        self.start_block = ColorBlock("#FFE7A2", "起始", self)
        self.start_block.color_changed.connect(self._on_color_changed)
        self.start_block.pick_color_requested.connect(lambda: self._start_picking('start'))
        grid.addWidget(start_label, 2, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.start_block, 3, 0, alignment=Qt.AlignmentFlag.AlignCenter)

        # 锁定按钮（放在渐变起始和渐变结束中间）
        self.lock_btn = QPushButton("🔓")
        self.lock_btn.setFixedSize(36, 36)
        self.lock_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lock_btn.setStyleSheet("""
            QPushButton {
                background: #ffffff;
                border: 2px solid #e0e0e0;
                border-radius: 18px;
                font-size: 18px;
            }
            QPushButton:hover {
                background: #f5f5f5;
                border: 2px solid #bdbdbd;
            }
        """)
        self.lock_btn.clicked.connect(self._toggle_lock)
        self.gradient_locked = False
        grid.addWidget(self.lock_btn, 3, 1, alignment=Qt.AlignmentFlag.AlignCenter)

        end_label = QLabel("渐变结束")
        end_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        end_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #333;")
        self.end_block = ColorBlock("#FFCB3D", "结束", self)
        self.end_block.color_changed.connect(self._on_color_changed)
        self.end_block.pick_color_requested.connect(lambda: self._start_picking('end'))
        grid.addWidget(end_label, 2, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.end_block, 3, 2, alignment=Qt.AlignmentFlag.AlignCenter)

        # 设置列宽：左右列拉伸，中间列固定为锁按钮宽度
        grid.setColumnStretch(0, 1)
        grid.setColumnMinimumWidth(1, 36)  # 中间列宽度与锁按钮一致
        grid.setColumnStretch(2, 1)

        content_layout.addLayout(grid)
        color_layout.addWidget(color_content)
        layout.addWidget(color_group)

        # ==================== 调色盘分栏 ====================
        palette_group = QGroupBox()
        palette_group.setStyleSheet(f"""
            QGroupBox {{
                border: none;
                border-radius: 8px;
                background: {SECTION_BG};
                margin: 0px;
            }}
        """)
        palette_outer_layout = QVBoxLayout(palette_group)
        palette_outer_layout.setContentsMargins(0, 0, 0, 0)
        palette_outer_layout.setSpacing(0)

        palette_header = QLabel("🎨 调色盘")
        palette_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        palette_header.setStyleSheet("""
            QLabel {
                background: #e0e0e0;
                color: #333333;
                font-weight: bold;
                font-size: 14px;
                padding: 12px 16px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
        """)
        palette_outer_layout.addWidget(palette_header)

        self.palette_content = QWidget()
        self.palette_content.setFixedHeight(260)  # 固定调色盘高度
        self.palette_content.setStyleSheet(f"background: {SECTION_BG}; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;")
        palette_inner_layout = QVBoxLayout(self.palette_content)
        palette_inner_layout.setContentsMargins(16, 12, 16, 12)
        palette_inner_layout.setSpacing(8)

        # 第一行：拾色框 + 色相条 + 饱和度条 + 明度条（全部竖向）
        top_layout = QHBoxLayout()
        top_layout.setSpacing(12)

        # 拾色框（带名称标签）
        picker_container = QVBoxLayout()
        picker_container.setSpacing(4)
        picker_label = QLabel("颜色")
        picker_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        picker_label.setStyleSheet("font-size: 12px; color: #666;")
        picker_size = 200
        self.square_picker = SquareColorPicker(picker_size)
        self.square_picker.color_selected.connect(self._on_picker_color_selected)
        picker_container.addWidget(picker_label)
        picker_container.addWidget(self.square_picker)
        top_layout.addLayout(picker_container)

        # 色相条（竖向）
        hue_container = QVBoxLayout()
        hue_container.setSpacing(4)
        hue_label = QLabel("色相")
        hue_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hue_label.setStyleSheet("font-size: 12px; color: #666;")
        self.hue_slider_v = HueSliderVertical()
        self.hue_slider_v.value_changed.connect(self._on_hue_changed)
        hue_container.addWidget(hue_label)
        hue_container.addWidget(self.hue_slider_v, alignment=Qt.AlignmentFlag.AlignCenter)
        top_layout.addLayout(hue_container)

        # 饱和度条（竖向）
        sat_container = QVBoxLayout()
        sat_container.setSpacing(4)
        sat_label = QLabel("饱和度")
        sat_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sat_label.setStyleSheet("font-size: 12px; color: #666;")
        self.sat_slider = SaturationSliderVertical()
        self.sat_slider.value_changed.connect(self._on_saturation_changed)
        sat_container.addWidget(sat_label)
        sat_container.addWidget(self.sat_slider, alignment=Qt.AlignmentFlag.AlignCenter)
        top_layout.addLayout(sat_container)

        # 明度条（竖向）
        light_container = QVBoxLayout()
        light_container.setSpacing(4)
        light_label = QLabel("明度")
        light_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        light_label.setStyleSheet("font-size: 12px; color: #666;")
        self.light_slider = LightnessSliderVertical()
        self.light_slider.value_changed.connect(self._on_lightness_changed)
        light_container.addWidget(light_label)
        light_container.addWidget(self.light_slider, alignment=Qt.AlignmentFlag.AlignCenter)
        top_layout.addLayout(light_container)

        top_layout.addStretch()  # 右侧弹性空间

        palette_inner_layout.addLayout(top_layout)

        palette_outer_layout.addWidget(self.palette_content)
        layout.addWidget(palette_group)

        # ==================== 预设配色 ====================
        preset_group = QGroupBox()
        preset_group.setStyleSheet(f"""
            QGroupBox {{
                border: none;
                border-radius: 8px;
                background: {SECTION_BG};
                margin: 0px;
            }}
        """)
        preset_outer_layout = QVBoxLayout(preset_group)
        preset_outer_layout.setContentsMargins(0, 0, 0, 0)
        preset_outer_layout.setSpacing(0)

        # 预设配色顶栏（标题 + 添加按钮）
        preset_header_widget = QWidget()
        preset_header_widget.setFixedHeight(45)  # 固定高度，防止随窗口拉伸
        preset_header_layout = QHBoxLayout(preset_header_widget)
        preset_header_layout.setContentsMargins(16, 12, 16, 12)
        preset_header_layout.setSpacing(0)
        
        self.preset_header = QLabel("🎯 预设配色  ▶")
        self.preset_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.preset_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preset_header.setStyleSheet("""
            QLabel {
                background: transparent;
                color: #333333;
                font-weight: bold;
                font-size: 14px;
            }
            QLabel:hover {
                color: #2196f3;
            }
        """)
        self.preset_header.mousePressEvent = lambda e: self._toggle_preset()
        
        self.add_preset_btn = QLabel("✚")
        self.add_preset_btn.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.add_preset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_preset_btn.setStyleSheet("""
            QLabel {
                background: transparent;
                color: #666;
                font-size: 18px;
                font-weight: bold;
                padding: 4px 8px;
            }
            QLabel:hover {
                color: #2196f3;
                background: rgba(33, 150, 243, 0.1);
                border-radius: 4px;
            }
        """)
        self.add_preset_btn.mousePressEvent = self._add_custom_preset
        
        preset_header_layout.addWidget(self.preset_header)
        preset_header_layout.addStretch()
        preset_header_layout.addWidget(self.add_preset_btn)
        
        preset_header_widget.setStyleSheet(f"""
            QWidget {{
                background: #e0e0e0;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }}
        """)
        preset_outer_layout.addWidget(preset_header_widget)

        self.preset_content = QWidget()
        self.preset_content.setStyleSheet(f"background: {SECTION_BG}; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;")
        self.preset_layout = QGridLayout(self.preset_content)
        self.preset_layout.setContentsMargins(16, 12, 16, 12)
        self.preset_layout.setSpacing(10)

        # 默认预设配色（只保留4个）
        self.default_presets = [
            ("#FCBC19", "#FFE7A2", "#FFCB3D", "默认黄"),
            ("#3498db", "#85c1e9", "#2980b9", "蓝色"),
            ("#2ecc71", "#82e0aa", "#27ae60", "绿色"),
            ("#e74c3c", "#f1948a", "#c0392b", "红色"),
        ]

        self.preset_buttons = []
        self._render_presets()

        preset_outer_layout.addWidget(self.preset_content)
        self.preset_expanded = False
        self.preset_content.hide()

        layout.addWidget(preset_group)
        layout.addStretch()  # 添加弹性空间，将所有分栏推向顶部，防止随窗口拉伸

    def _render_presets(self):
        """渲染所有预设按钮"""
        # 清除现有按钮
        for btn in self.preset_buttons:
            btn.deleteLater()
        self.preset_buttons.clear()
        
        # 清空布局
        while self.preset_layout.count():
            item = self.preset_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # 渲染默认预设（不可删除）
        for i, (bg, start, end, name) in enumerate(self.default_presets):
            btn = PresetButton(bg, start, end, self.svg_template or "", is_custom=False)
            btn.clicked.connect(lambda checked=False, b=btn: self._apply_preset(b.bg_color, b.start_color, b.end_color))
            self.preset_buttons.append(btn)
            row = i // 4
            col = i % 4
            self.preset_layout.addWidget(btn, row, col)
        
        # 渲染用户自定义预设（可右键删除）
        for i, preset in enumerate(self.custom_presets):
            bg, start, end = preset.get("bg"), preset.get("start"), preset.get("end")
            if bg and start and end:
                btn = PresetButton(bg, start, end, self.svg_template or "", is_custom=True)
                btn.clicked.connect(lambda checked=False, b=btn: self._apply_preset(b.bg_color, b.start_color, b.end_color))
                btn.delete_requested.connect(self._delete_preset)
                self.preset_buttons.append(btn)
                idx = len(self.default_presets) + i
                row = idx // 4
                col = idx % 4
                self.preset_layout.addWidget(btn, row, col)

    def _delete_preset(self, btn):
        """删除自定义预设"""
        # 找到该按钮对应的预设索引
        preset_idx = self.preset_buttons.index(btn) - len(self.default_presets)
        if preset_idx >= 0 and preset_idx < len(self.custom_presets):
            del self.custom_presets[preset_idx]
            self._save_preset_cache()
            self._render_presets()

    def _add_custom_preset(self, event):
        """添加当前配色为新预设"""
        if event.button() == Qt.MouseButton.LeftButton:
            bg = self.bg_block.get_color()
            start = self.start_block.get_color()
            end = self.end_block.get_color()
            
            # 添加到自定义预设
            self.custom_presets.append({
                "bg": bg,
                "start": start,
                "end": end
            })
            
            # 保存到缓存文件
            self._save_preset_cache()
            
            # 重新渲染预设
            self._render_presets()
            
            # 展开预设面板
            if not self.preset_expanded:
                self._toggle_preset()

    def _on_overall_clicked(self):
        self.deselect_all()
        self.overall_block.set_selected(True)
    
    def _start_picking(self, target: str):
        """开始取色"""
        self.picking_target = target
        self.color_picker.start_picking()
        # 高亮对应的颜色块
        self.deselect_all()
        if target == 'overall':
            self.overall_block.set_selected(True)
        elif target == 'bg':
            self.bg_block.set_selected(True)
        elif target == 'start':
            self.start_block.set_selected(True)
        elif target == 'end':
            self.end_block.set_selected(True)
        # 延迟安装事件过滤器，避免捕获到当前的点击事件
        QTimer.singleShot(100, lambda: QApplication.instance().installEventFilter(self))
    
    def eventFilter(self, obj, event):
        """事件过滤器 - 监听全局鼠标点击"""
        if self.color_picker.active:
            if event.type() == event.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    # 左键点击 - 应用颜色
                    self.color_picker.stop_picking(apply=True)
                    QApplication.instance().removeEventFilter(self)
                    return True
                elif event.button() == Qt.MouseButton.RightButton:
                    # 右键点击 - 取消
                    self.color_picker.stop_picking(apply=False)
                    QApplication.instance().removeEventFilter(self)
                    return True
        return super().eventFilter(obj, event)
    
    def _on_color_picked(self, color: str):
        """颜色被选取后的处理"""
        if self.picking_target == 'overall':
            self._apply_overall_adjustment(color)
        elif self.picking_target == 'bg':
            self.bg_block.set_color(color)
            self.sync_color_to_palette(color)
            self._on_color_changed(None)
        elif self.picking_target == 'start':
            self.start_block.set_color(color)
            if self.gradient_locked:
                self.end_block.set_color(color)
            self.sync_color_to_palette(color)
            self._on_color_changed(None)
        elif self.picking_target == 'end':
            self.end_block.set_color(color)
            if self.gradient_locked:
                self.start_block.set_color(color)
            self.sync_color_to_palette(color)
            self._on_color_changed(None)
        self.picking_target = None

    def _toggle_preset(self):
        self.preset_expanded = not self.preset_expanded
        if self.preset_expanded:
            self.preset_content.show()
            self.preset_header.setText("🎯 预设配色  ▼")
        else:
            self.preset_content.hide()
            self.preset_header.setText("🎯 预设配色  ▶")

    def _toggle_lock(self):
        self.gradient_locked = not self.gradient_locked
        if self.gradient_locked:
            self.lock_btn.setText("🔒")
            self.lock_btn.setStyleSheet("""
                QPushButton {
                    background: #2196f3;
                    border: 2px solid #1976d2;
                    border-radius: 18px;
                    font-size: 18px;
                }
                QPushButton:hover {
                    background: #1976d2;
                }
            """)
            # 锁定时以渐变结束颜色为基准
            end_color = self.end_block.get_color()
            self.start_block.set_color(end_color)
            self.sync_color_to_palette(end_color)
            self._on_color_changed(None)
        else:
            self.lock_btn.setText("🔓")
            self.lock_btn.setStyleSheet("""
                QPushButton {
                    background: #ffffff;
                    border: 2px solid #e0e0e0;
                    border-radius: 18px;
                    font-size: 18px;
                }
                QPushButton:hover {
                    background: #f5f5f5;
                    border: 2px solid #bdbdbd;
                }
            """)

    def deselect_all(self):
        for block in (self.bg_block, self.start_block, self.end_block):
            if block:
                block.set_selected(False)
        if self.overall_block:
            self.overall_block.set_selected(False)

    def sync_color_to_palette(self, hex_color: str):
        if self._updating_palette:
            return
        
        self._updating_palette = True
        try:
            color = QColor(hex_color)
            h, s, v, _ = color.getHsv()
            
            self.hue_slider_v.blockSignals(True)
            self.sat_slider.blockSignals(True)
            self.light_slider.blockSignals(True)
            
            self.hue_slider_v.setValue(h)
            self.sat_slider.setValue(int(s * 100 / 255))
            self.light_slider.setValue(int(v * 100 / 255))
            
            self.hue_slider_v.blockSignals(False)
            self.sat_slider.blockSignals(False)
            self.light_slider.blockSignals(False)
            
            self.square_picker.set_hue(h)
            self.square_picker.set_saturation(int(s * 100 / 255))
            self.square_picker.set_lightness(int(v * 100 / 255))
            
            self.sat_slider.set_hue(h)
            self.light_slider.set_hsl(h, int(s * 100 / 255))
        finally:
            self._updating_palette = False

    def _on_picker_color_selected(self, saturation, lightness):
        if self._updating_palette:
            return
        
        self.sat_slider.blockSignals(True)
        self.light_slider.blockSignals(True)
        self.sat_slider.setValue(saturation)
        self.light_slider.setValue(lightness)
        self.sat_slider.blockSignals(False)
        self.light_slider.blockSignals(False)
        
        self.light_slider.set_hsl(self.hue_slider_v.value(), saturation)
        self._apply_color_realtime()

    def _on_hue_changed(self, hue):
        if self._updating_palette:
            return
        self.square_picker.set_hue(hue)
        self.sat_slider.set_hue(hue)
        self.light_slider.set_hsl(hue, self.sat_slider.value())
        self._apply_color_realtime()

    def _on_saturation_changed(self, saturation):
        if self._updating_palette:
            return
        self.square_picker.set_saturation(saturation)
        self.light_slider.set_hsl(self.hue_slider_v.value(), saturation)
        self._apply_color_realtime()

    def _on_lightness_changed(self, lightness):
        if self._updating_palette:
            return
        self.square_picker.set_lightness(lightness)
        self._apply_color_realtime()

    def apply_hex_color_to_selected(self, hex_color: str):
        """从颜色输入框应用颜色到选中的色块"""
        if self.overall_block and self.overall_block.is_selected:
            # 整体调整：基于新颜色与当前平均色的差异，做相对调整
            self._apply_overall_adjustment(hex_color)
        elif self.bg_block.is_selected:
            self.bg_block.set_color(hex_color)
        elif self.start_block.is_selected:
            self.start_block.set_color(hex_color)
            if self.gradient_locked:
                self.end_block.set_color(hex_color)
        elif self.end_block.is_selected:
            self.end_block.set_color(hex_color)
            if self.gradient_locked:
                self.start_block.set_color(hex_color)
        else:
            self.bg_block.set_color(hex_color)
        
        self.sync_color_to_palette(hex_color)
        self._on_color_changed(None)

    def _apply_overall_adjustment(self, new_color: str):
        """整体调整：基于当前三个颜色与新颜色的差异做相对调整"""
        new = QColor(new_color)
        new_h, new_s, new_v, _ = new.getHsv()
        
        # 获取当前三个颜色的平均HSV
        bg = QColor(self.bg_block.get_color())
        start = QColor(self.start_block.get_color())
        end = QColor(self.end_block.get_color())
        
        bg_h, bg_s, bg_v, _ = bg.getHsv()
        start_h, start_s, start_v, _ = start.getHsv()
        end_h, end_s, end_v, _ = end.getHsv()
        
        # 计算平均色
        avg_h = (bg_h + start_h + end_h) / 3
        avg_s = (bg_s + start_s + end_s) / 3
        avg_v = (bg_v + start_v + end_v) / 3
        
        # 计算差异
        delta_h = new_h - avg_h
        delta_s = new_s - avg_s
        delta_v = new_v - avg_v
        
        # 应用相对调整到三个颜色
        # 背景颜色
        new_bg_h = (bg_h + delta_h) % 360
        new_bg_s = max(0, min(255, int(bg_s + delta_s)))
        new_bg_v = max(0, min(255, int(bg_v + delta_v)))
        self.bg_block.set_color(QColor.fromHsv(int(new_bg_h), new_bg_s, new_bg_v).name().upper())
        
        # 渐变起始
        new_start_h = (start_h + delta_h) % 360
        new_start_s = max(0, min(255, int(start_s + delta_s)))
        new_start_v = max(0, min(255, int(start_v + delta_v)))
        self.start_block.set_color(QColor.fromHsv(int(new_start_h), new_start_s, new_start_v).name().upper())
        
        # 渐变结束
        if self.gradient_locked:
            self.end_block.set_color(self.start_block.get_color())
        else:
            new_end_h = (end_h + delta_h) % 360
            new_end_s = max(0, min(255, int(end_s + delta_s)))
            new_end_v = max(0, min(255, int(end_v + delta_v)))
            self.end_block.set_color(QColor.fromHsv(int(new_end_h), new_end_s, new_end_v).name().upper())
        
        # 触发颜色更新信号，更新SVG预览
        self._on_color_changed(None)

    def _apply_color_realtime(self):
        hue = self.hue_slider_v.value()
        saturation = self.sat_slider.value()
        lightness = self.light_slider.value()
        
        h = hue
        s = int(saturation * 2.55)
        v = int(lightness * 2.55)
        
        color = QColor.fromHsv(h, s, v)
        hex_color = color.name().upper()
        
        if self.overall_block and self.overall_block.is_selected:
            # 整体调整：基于当前三个颜色做相对调整
            self._apply_overall_adjustment(hex_color)
        elif self.bg_block.is_selected:
            self.bg_block.set_color(hex_color)
        elif self.start_block.is_selected:
            self.start_block.set_color(hex_color)
            if self.gradient_locked:
                self.end_block.set_color(hex_color)
        elif self.end_block.is_selected:
            self.end_block.set_color(hex_color)
            if self.gradient_locked:
                self.start_block.set_color(hex_color)
        else:
            self.bg_block.set_color(hex_color)
        
        self._on_color_changed(None)

    def _on_color_changed(self, color: str):
        if self.gradient_locked:
            sender = self.sender()
            if sender == self.start_block:
                self.end_block.set_color(self.start_block.get_color())
            elif sender == self.end_block:
                self.start_block.set_color(self.end_block.get_color())
        
        bg = self.bg_block.get_color()
        start = self.start_block.get_color()
        end = self.end_block.get_color()
        
        # 更新整体调整的颜色输入框
        if self.overall_block:
            self.overall_block.set_color(bg)
        
        self.colors_changed.emit(bg, start, end)

    def _apply_preset(self, bg, start, end):
        old_locked = self.gradient_locked
        self.gradient_locked = False
        
        self.bg_block.set_color(bg)
        self.start_block.set_color(start)
        self.end_block.set_color(end)
        self.deselect_all()
        self.overall_block.set_selected(True)  # 预设应用后选中整体调整
        self.sync_color_to_palette(bg)
        
        self.gradient_locked = old_locked
        self._on_color_changed(None)


# ==================== 控制面板（含固定底部保存区域）====================
class ControlPanel(QWidget):
    colors_changed = pyqtSignal(str, str, str)
    save_requested = pyqtSignal()
    save_and_apply_requested = pyqtSignal()  # 保存并应用请求
    save_custom_requested = pyqtSignal()  # 保存自定义图标请求

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: #ffffff;")
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 设置滚动条悬浮覆盖在内容上，避免内容宽度变化
        scroll_area.setViewportMargins(0, 0, -6, 0)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: #ffffff;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 0, 0, 0.2);
                min-height: 30px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(0, 0, 0, 0.35);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)

        self.content = ControlPanelContent()
        self.content.colors_changed.connect(self.colors_changed.emit)
        self.content.save_custom_requested.connect(self.save_custom_requested.emit)
        scroll_area.setWidget(self.content)

        main_layout.addWidget(scroll_area)

        save_container = QWidget()
        save_container.setFixedHeight(60)
        save_container.setStyleSheet("""
            QWidget {
                background: white;
                border-top: 1px solid #e0e0e0;
            }
        """)
        save_layout = QHBoxLayout(save_container)
        save_layout.setContentsMargins(16, 10, 16, 10)
        save_layout.setSpacing(10)

        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText("请输入图标名称")
        self.filename_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                padding: 10px 12px;
                font-size: 14px;
                background: #ffffff;
            }
            QLineEdit:focus {
                border: 2px solid #2196f3;
            }
            QLineEdit::placeholder {
                color: #999999;
            }
        """)
        save_layout.addWidget(self.filename_input)

        self.btn_save = QPushButton("💾 保存")
        self.btn_save.setFixedWidth(100)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover { background-color: #1976d2; }
        """)
        self.btn_save.clicked.connect(self.save_requested.emit)
        save_layout.addWidget(self.btn_save)

        # 保存并应用按钮
        self.btn_save_apply = QPushButton("🚀 保存并应用")
        self.btn_save_apply.setFixedWidth(120)
        self.btn_save_apply.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
                padding: 10px;
            }
            QPushButton:hover { background-color: #43A047; }
        """)
        self.btn_save_apply.clicked.connect(self.save_and_apply_requested.emit)
        save_layout.addWidget(self.btn_save_apply)

        main_layout.addWidget(save_container)

    def set_svg_template(self, svg_content: str):
        self.content.set_svg_template(svg_content)

    def update_overall_preview(self, svg_content: str):
        self.content.update_overall_preview(svg_content)

    def get_filename(self) -> str:
        name = self.filename_input.text().strip()
        return name if name else "custom_folder"

    def deselect_all(self):
        self.content.deselect_all()

    def sync_color_to_palette(self, hex_color: str):
        self.content.sync_color_to_palette(hex_color)

    @property
    def bg_block(self):
        return self.content.bg_block

    @property
    def start_block(self):
        return self.content.start_block

    @property
    def end_block(self):
        return self.content.end_block


# ==================== 自定义图标列表项 ====================
class CustomIconListItemWidget(QWidget):
    """自定义图标列表项组件"""
    
    def __init__(self, icon_name: str, preview_pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.icon_name = icon_name
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        
        # 预览图标
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(48, 48)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
            }
        """)
        if preview_pixmap:
            scaled_pixmap = preview_pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.preview_label.setPixmap(scaled_pixmap)
        layout.addWidget(self.preview_label)
        
        # 名称标签
        self.name_label = QLabel(icon_name)
        self.name_label.setStyleSheet("font-size: 13px; color: #000000; background: transparent;")
        layout.addWidget(self.name_label, 1)
        
        self.setStyleSheet("""
            CustomIconListItemWidget {
                border-radius: 6px;
            }
            CustomIconListItemWidget:hover {
                background: #f5f5f5;
            }
        """)


# ==================== 自定义图标面板 ====================
class CustomIconPanel(QWidget):
    """自定义图标面板，显示已保存的自定义图标"""
    
    load_icon_requested = pyqtSignal(str, dict)  # 加载图标请求 (name, data)
    delete_icon_requested = pyqtSignal(str)  # 删除图标请求
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: #ffffff;")
        self._preview_pixmap_cache: Dict[str, QPixmap] = {}
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # 标题栏
        header = QWidget()
        header.setStyleSheet("background: #e0e0e0; padding: 12px 16px;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        
        title_label = QLabel("⭐ 自定义图标")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #333;")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        layout.addWidget(header)
        
        # 图标列表
        self.icon_list = QListWidget()
        self.icon_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 移除焦点虚线框
        self.icon_list.setStyleSheet("""
            QListWidget {
                border: none;
                background: #ffffff;
                selection-background-color: #e3f2fd;
                selection-color: #000000;  /* 选中时的文字颜色改为黑色 */
                outline: none;  /* 额外确保无焦点边框 */
            }
            QListWidget::item {
                padding: 2px;
                border-bottom: 1px solid #f0f0f0;
            }
            QListWidget::item:selected {
                background: #e3f2fd;
                color: #000000;
            }
            /* 确保自定义项内部的标签也能变色且透明 */
            QListWidget::item:selected QLabel {
                color: #000000;
                background: transparent;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 6px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 0, 0, 0.2);
                min-height: 30px;
                border-radius: 3px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(0, 0, 0, 0.35);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        self.icon_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.icon_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.icon_list.customContextMenuRequested.connect(self._show_context_menu)
        self.icon_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.icon_list)
    
    def _show_context_menu(self, pos):
        """显示右键菜单"""
        item = self.icon_list.itemAt(pos)
        if not item:
            return
            
        menu = RoundedMenu(self)
        delete_action = menu.addAction("🗑️ 删除图标")
        
        # 获取图标名称
        widget = self.icon_list.itemWidget(item)
        icon_name = widget.icon_name
        
        delete_action.triggered = lambda: self.delete_icon_requested.emit(icon_name)
        menu.exec(self.icon_list.mapToGlobal(pos))
    
    def _on_item_double_clicked(self, item):
        """双击加载图标"""
        icon_data = item.data(Qt.ItemDataRole.UserRole)
        widget = self.icon_list.itemWidget(item)
        if icon_data and widget:
            self.load_icon_requested.emit(widget.icon_name, icon_data)
    
    def update_icon_list(self, icons_data: List[Tuple[str, Dict]], ico_dir: str = ""):
        """更新图标列表"""
        self.icon_list.clear()
        current_names = {name for name, _ in icons_data}
        for cached_name in list(self._preview_pixmap_cache.keys()):
            if cached_name not in current_names:
                self._preview_pixmap_cache.pop(cached_name, None)
        
        for icon_name, data in icons_data:
            # 优先尝试从本地加载生成的 .ico 文件作为预览
            preview_pixmap = None
            ico_path = os.path.join(ico_dir, f"{icon_name}.ico")
            
            preview_pixmap = self._preview_pixmap_cache.get(icon_name)
            if preview_pixmap is None and os.path.exists(ico_path):
                preview_pixmap = QPixmap(ico_path)
            
            # 如果没有找到 .ico 文件，回退到使用配置中的 svg_content 渲染预览
            if (not preview_pixmap or preview_pixmap.isNull()) and "svg_content" in data:
                preview_pixmap = SVGRenderer.render_to_pixmap(data["svg_content"], 64, 50)

            if preview_pixmap and not preview_pixmap.isNull():
                self._preview_pixmap_cache[icon_name] = preview_pixmap
            
            # 创建列表项
            item = QListWidgetItem()
            widget = CustomIconListItemWidget(icon_name, preview_pixmap)
            
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, data)
            
            self.icon_list.addItem(item)
            self.icon_list.setItemWidget(item, widget)

    def evict_preview_cache(self, icon_name: str) -> None:
        """清理自定义图标预览的内存缓存与列表项预览。"""
        self._preview_pixmap_cache.pop(icon_name, None)
        for row in range(self.icon_list.count()):
            item = self.icon_list.item(row)
            widget = self.icon_list.itemWidget(item)
            if widget and getattr(widget, "icon_name", None) == icon_name:
                try:
                    widget.preview_label.clear()
                except Exception:
                    pass
                break


# ==================== 主窗口 ====================
class IconCreatorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Icon Creator - 文件夹图标制作器")
        self.setMinimumSize(1200, 660)
        self.resize(1300, 700)

        self.original_svg = None
        self.current_svg = None
        self.ico_output_dir = os.path.join(get_app_root_dir(), "ico", "CustomIco")
        try:
            os.makedirs(self.ico_output_dir, exist_ok=True)
        except Exception as e:
            import logging
            logging.error(f"创建图标输出目录失败: {e}")
            QMessageBox.critical(None, "权限错误", f"无法创建输出目录，请以管理员身份运行程序。\n\n路径: {self.ico_output_dir}\n错误信息: {e}")
        self.icon_opacity = 100  # 图标透明度，默认100%
        
        # 图标相关属性初始化
        self.icon_files = []
        self.current_icon_index = -1
        
        # 存档管理器
        self.save_manager = SaveManager()
        
        self._init_ui()
        self._connect_signals()
        QTimer.singleShot(30, self._load_template)
        QTimer.singleShot(100, self.load_custom_icons)  # 延迟加载自定义图标

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main = QHBoxLayout(central)
        main.setContentsMargins(0, 0, 0, 0)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(8)

        # 左侧控制面板
        self.control = ControlPanel()
        self.control.setMinimumWidth(360)
        self.splitter.addWidget(self.control)

        # 中间预览区域
        preview_area = QWidget()
        preview_area.setStyleSheet("background: #fafafa;")
        p_layout = QVBoxLayout(preview_area)
        p_layout.setContentsMargins(40, 30, 40, 30)

        title = QLabel("实时预览")
        title.setStyleSheet("font-weight: bold; font-size: 19px; color: #222;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p_layout.addWidget(title)

        self.preview_container = QWidget()
        self.preview_container.setStyleSheet("background: transparent;")

        container_layout = QVBoxLayout(self.preview_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 使用支持图标叠加的自定义画布
        self.preview_canvas = IconCanvasWidget()
        container_layout.addWidget(self.preview_canvas)

        p_layout.addWidget(self.preview_container, 1)

        # ==================== 选择图标区域 ====================
        icon_group = QGroupBox()
        icon_group.setStyleSheet("""
            QGroupBox {
                border: none;
                border-radius: 8px;
                background: #ffffff;
                margin: 0px;
            }
        """)
        icon_outer_layout = QVBoxLayout(icon_group)
        icon_outer_layout.setContentsMargins(0, 0, 0, 0)
        icon_outer_layout.setSpacing(0)

        # 顶栏：显示文件名 + 切换按钮
        icon_header = QWidget()
        icon_header.setStyleSheet("""
            QWidget {
                background: #e0e0e0;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
        """)
        header_layout = QHBoxLayout(icon_header)
        header_layout.setContentsMargins(16, 0, 8, 0)
        header_layout.setSpacing(8)

        # 文件名显示标签
        self.icon_filename_label = QLabel("📁 选择图标")
        self.icon_filename_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.icon_filename_label.setStyleSheet("""
            QLabel {
                background: transparent;
                color: #333333;
                font-weight: bold;
                font-size: 14px;
                padding: 12px 0px;
            }
        """)
        header_layout.addWidget(self.icon_filename_label, 1)

        # 切换按钮容器（上下排列）
        switch_btn_container = QWidget()
        switch_btn_container.setFixedSize(36, 44)
        switch_btn_container.setStyleSheet("background: transparent;")
        switch_btn_layout = QVBoxLayout(switch_btn_container)
        switch_btn_layout.setContentsMargins(0, 4, 0, 4)
        switch_btn_layout.setSpacing(2)

        # 上一个按钮
        self.prev_icon_btn = QPushButton("▲")
        self.prev_icon_btn.setFixedSize(28, 16)
        self.prev_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.prev_icon_btn.setStyleSheet("""
            QPushButton {
                background: #bdbdbd;
                border: none;
                border-radius: 3px;
                color: #333;
                font-size: 10px;
            }
            QPushButton:hover {
                background: #9e9e9e;
            }
            QPushButton:pressed {
                background: #757575;
            }
        """)
        self.prev_icon_btn.clicked.connect(self._prev_icon)
        switch_btn_layout.addWidget(self.prev_icon_btn)

        # 下一个按钮
        self.next_icon_btn = QPushButton("▼")
        self.next_icon_btn.setFixedSize(28, 16)
        self.next_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.next_icon_btn.setStyleSheet("""
            QPushButton {
                background: #bdbdbd;
                border: none;
                border-radius: 3px;
                color: #333;
                font-size: 10px;
            }
            QPushButton:hover {
                background: #9e9e9e;
            }
            QPushButton:pressed {
                background: #757575;
            }
        """)
        self.next_icon_btn.clicked.connect(self._next_icon)
        switch_btn_layout.addWidget(self.next_icon_btn)

        header_layout.addWidget(switch_btn_container)
        icon_outer_layout.addWidget(icon_header)

        icon_content = QWidget()
        icon_content.setStyleSheet("background: #ffffff; border-bottom-left-radius: 8px; border-bottom-right-radius: 8px;")
        icon_inner_layout = QHBoxLayout(icon_content)
        icon_inner_layout.setContentsMargins(16, 12, 16, 12)
        icon_inner_layout.setSpacing(12)

        # 图标展示框
        self.icon_preview = QLabel()
        self.icon_preview.setFixedSize(48, 48)
        self.icon_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_preview.setStyleSheet("""
            QLabel {
                background: #f5f5f5;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
            }
        """)
        icon_inner_layout.addWidget(self.icon_preview)

        # 路径输入框
        self.icon_path_input = QLineEdit()
        self.icon_path_input.setPlaceholderText("选择文件路径")
        self.icon_path_input.setFixedHeight(36)
        self.icon_path_input.setStyleSheet("""
            QLineEdit {
                background: #ffffff;
                border: 2px solid #e0e0e0;
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 13px;
                color: #333;
            }
            QLineEdit:focus {
                border: 2px solid #2196f3;
            }
            QLineEdit::placeholder {
                color: #999;
            }
        """)
        self.icon_path_input.returnPressed.connect(self._on_icon_path_enter)
        icon_inner_layout.addWidget(self.icon_path_input, 1)

        # 选择文件按钮
        self.icon_select_file_btn = QPushButton("📄 选择文件")
        self.icon_select_file_btn.setFixedSize(90, 36)
        self.icon_select_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon_select_file_btn.setStyleSheet("""
            QPushButton {
                background: #81C784;
                border: none;
                border-radius: 6px;
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #66BB6A;
            }
            QPushButton:pressed {
                background: #4CAF50;
            }
        """)
        self.icon_select_file_btn.clicked.connect(self._select_icon_file)
        icon_inner_layout.addWidget(self.icon_select_file_btn)

        # 选择文件夹按钮
        self.icon_select_folder_btn = QPushButton("📁 选择文件夹")
        self.icon_select_folder_btn.setFixedSize(100, 36)
        self.icon_select_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.icon_select_folder_btn.setStyleSheet("""
            QPushButton {
                background: #81C784;
                border: none;
                border-radius: 6px;
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #66BB6A;
            }
            QPushButton:pressed {
                background: #4CAF50;
            }
        """)
        self.icon_select_folder_btn.clicked.connect(self._select_icon_folder)
        icon_inner_layout.addWidget(self.icon_select_folder_btn)

        icon_outer_layout.addWidget(icon_content)

        # 按钮区域
        btn_content = QWidget()
        btn_content.setStyleSheet("background: #ffffff;")
        btn_inner_layout = QHBoxLayout(btn_content)
        btn_inner_layout.setContentsMargins(16, 0, 16, 12)
        btn_inner_layout.setSpacing(8)

        # 透明度滑条
        opacity_container = QVBoxLayout()
        opacity_container.setSpacing(4)
        opacity_label = QLabel("透明度")
        opacity_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        opacity_label.setStyleSheet("font-size: 12px; color: #666;")
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setFixedWidth(190)  # 缩短50px
        self.opacity_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #e0e0e0;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #2196F3;
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #1976D2;
            }
            QSlider::sub-page:horizontal {
                background: #2196F3;
                border-radius: 3px;
            }
        """)
        self.opacity_value_label = QLabel("100%")
        self.opacity_value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.opacity_value_label.setStyleSheet("font-size: 11px; color: #333;")
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        opacity_container.addWidget(opacity_label)
        opacity_container.addWidget(self.opacity_slider)
        opacity_container.addWidget(self.opacity_value_label)
        btn_inner_layout.addLayout(opacity_container)

        btn_inner_layout.addStretch()  # 中间弹性空间，两端对齐

        # 添加图标到画布按钮（蓝色）
        self.add_icon_btn = QPushButton("添加图标到画布")
        self.add_icon_btn.setFixedSize(130, 36)  # 再缩短20px
        self.add_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_icon_btn.setStyleSheet("""
            QPushButton {
                background: #2196F3;
                border: none;
                border-radius: 6px;
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #1976D2;
            }
            QPushButton:pressed {
                background: #0D47A1;
            }
        """)
        self.add_icon_btn.clicked.connect(self._add_icon_to_canvas)
        btn_inner_layout.addWidget(self.add_icon_btn)

        # 从画布移出图标按钮（红色）
        self.remove_icon_btn = QPushButton("从画布移出图标")
        self.remove_icon_btn.setFixedSize(140, 36)  # 再缩短20px
        self.remove_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_icon_btn.setStyleSheet("""
            QPushButton {
                background: #EF5350;
                border: none;
                border-radius: 6px;
                color: #ffffff;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #E53935;
            }
            QPushButton:pressed {
                background: #C62828;
            }
        """)
        self.remove_icon_btn.clicked.connect(self._remove_icon_from_canvas)
        btn_inner_layout.addWidget(self.remove_icon_btn)

        icon_outer_layout.addWidget(btn_content)
        p_layout.addWidget(icon_group)
        
        # 画布操作说明（右下角小字）
        help_label = QLabel("画布操作：左键拖动 | 滚轮缩放 | 右键设缩放中心")
        help_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        help_label.setStyleSheet("font-size: 11px; color: #999; padding: 4px 8px;")
        p_layout.addWidget(help_label)

        self.splitter.addWidget(preview_area)

        # 右侧自定义图标面板
        self.custom_icon_panel = CustomIconPanel()
        self.custom_icon_panel.setMinimumWidth(240)
        self.custom_icon_panel.setMaximumWidth(300)
        self.splitter.addWidget(self.custom_icon_panel)

        main.addWidget(self.splitter)
        self.splitter.setSizes([380, 640, 240])

        self.statusBar().showMessage("就绪 - 点击颜色块切换颜色")
        self.statusBar().setStyleSheet("QStatusBar { background: #f5f5f5; color: #555; }")

    def _connect_signals(self):
        self.control.colors_changed.connect(self._update_colors)
        self.control.save_requested.connect(self._save_as_ico)
        self.control.save_and_apply_requested.connect(self._save_and_apply_ico)
        self.control.save_custom_requested.connect(self._save_custom_icon)
        self.custom_icon_panel.load_icon_requested.connect(self._load_custom_icon)
        self.custom_icon_panel.delete_icon_requested.connect(self._delete_custom_icon)

    def _load_template(self):
        self.original_svg = SVGColorModifier.load_base_svg()
        if self.original_svg:
            self.current_svg = self.original_svg
            self.control.set_svg_template(self.original_svg)
            self.control.content.deselect_all()
            self.control.content.overall_block.set_selected(True)  # 默认选中整体调整
            self.control.content.sync_color_to_palette("#FCBC19")
            self._update_preview()
            self.statusBar().showMessage("模板加载成功 | 点击左侧颜色块调整")
        else:
            self.preview_canvas.setText("未找到 base.svg\n请确认文件位于：\nico/CustomIco/base.svg")
            self.preview_canvas.setStyleSheet("color: #e74c3c; font-size: 16px;")

    def load_custom_icons(self):
        """加载自定义图标"""
        icons_data = self.save_manager.load_all_custom_icons()
        self.custom_icon_panel.update_icon_list(icons_data, self.ico_output_dir)
        self.statusBar().showMessage(f"已加载 {len(icons_data)} 个自定义图标")

    def _update_colors(self, bg, start, end):
        if not self.original_svg:
            return
        bg = bg if bg.startswith('#') else f'#{bg}'
        start = start if start.startswith('#') else f'#{start}'
        end = end if end.startswith('#') else f'#{end}'
        self.current_svg = SVGColorModifier.apply_colors(self.original_svg, bg, start, end)
        self._update_preview()
        self.control.update_overall_preview(self.current_svg)

    def _update_preview(self):
        if not self.current_svg:
            return

        pix = SVGRenderer.render_to_pixmap(self.current_svg, 320)
        if pix:
            self.preview_canvas.set_svg_pixmap(pix)
        else:
            self.preview_canvas.setText("预览渲染失败")

    def _save_as_ico(self, silent=False):
        if not self.current_svg:
            if not silent:
                QMessageBox.warning(self, "错误", "没有可保存的内容")
            return None

        filename = self.control.get_filename()

        try:
            # 使用新的合成方法
            final_pix = self.preview_canvas.compose_final_image(64)

            img = final_pix.toImage()
            img = img.convertToFormat(img.Format.Format_RGBA8888)
            
            width = img.width()
            height = img.height()
            ptr = img.bits()
            ptr.setsize(height * img.bytesPerLine())
            pil_img = Image.frombytes("RGBA", (width, height), bytes(ptr), "raw", "RGBA", img.bytesPerLine())

            save_path = os.path.join(self.ico_output_dir, f"{filename}.ico")
            
            if os.path.exists(save_path) and not silent:
                reply = QMessageBox.question(
                    self, "确认覆盖",
                    f"文件 \"{filename}.ico\" 已存在，是否覆盖？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return None
            
            pil_img.save(save_path, format='ICO', sizes=[(64, 64)])

            # 自动保存自定义配置
            self._save_custom_icon(silent=True)

            if not silent:
                QMessageBox.information(self, "保存成功", 
                                      f"64×64 图标已保存！\n\n路径：\n{save_path}")
            self.statusBar().showMessage(f"已保存: {filename}.ico")
            return save_path
        except Exception as e:
            if not silent:
                QMessageBox.warning(self, "保存失败", f"错误：{str(e)}")
            return None

    def _save_and_apply_ico(self):
        """保存并应用图标"""
        # 1. 检查是否选择了路径（通过命令行传过来的）
        target_path = self.icon_path_input.text().strip()
        if not target_path or not os.path.isdir(target_path):
            QMessageBox.warning(self, "提示", "请先在主程序中选择一个文件夹，或者在制作器中手动输入/选择要应用图标的文件夹路径。")
            return

        # 2. 保存图标
        save_path = self._save_as_ico(silent=True)
        if not save_path:
            return

        # 3. 应用图标
        try:
            # 这里的 IconApplicator 逻辑需要从 folder_icon_changer 引入或复用
            # 由于目前是两个独立脚本，最简单的方法是在此处定义一个简易版或调用系统命令
            # 为了保持一致性，我们直接在这里实现应用逻辑（参考 folder_icon_changer.py）
            success, message = self._apply_icon_to_folder(target_path, save_path)
            if success:
                QMessageBox.information(self, "成功", f"图标已成功保存并应用到：\n{target_path}")
            else:
                QMessageBox.warning(self, "应用失败", message)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"应用过程中出现异常：{str(e)}")

    def _apply_icon_to_folder(self, folder_path: str, icon_path: str) -> Tuple[bool, str]:
        """将图标应用到文件夹（参考 folder_icon_changer.py 的逻辑）"""
        try:
            icon_abs_path = os.path.abspath(icon_path)
            desktop_ini_path = os.path.join(folder_path, 'desktop.ini')
            
            # 清除属性
            if os.path.exists(desktop_ini_path):
                subprocess.run(f'attrib -h -s -r "{desktop_ini_path}"', shell=True, check=False)
            
            ini_content = f"[.ShellClassInfo]\nIconResource={icon_abs_path},0\n"
            
            with open(desktop_ini_path, 'w', encoding='gbk') as f:
                f.write(ini_content)
            
            # 设置属性
            subprocess.run(f'attrib +h +s "{desktop_ini_path}"', shell=True, check=False)
            subprocess.run(f'attrib +r "{folder_path}"', shell=True, check=False)
            
            # 强制刷新系统图标缓存
            self._refresh_system_icon(folder_path)
            
            return True, "成功"
        except Exception as e:
            return False, str(e)

    def _refresh_system_icon(self, folder_path: str):
        """强制刷新文件夹图标缓存（同步自 folder_icon_changer.py）"""
        try:
            # 1. 修改文件夹的修改时间
            try:
                os.utime(folder_path, None)
            except Exception:
                pass
            
            # 2. 通知系统发生变化
            try:
                if sys.platform == 'win32':
                    # SHCNE_ASSOCCHANGED = 0x08000000
                    # SHCNF_FLUSH = 0x1000
                    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x1000, None, None)
            except Exception:
                pass
            
            # 3. 尝试使用系统命令刷新
            try:
                subprocess.run('ie4uinit.exe -show', shell=True, check=False, timeout=5)
            except Exception:
                pass
        except Exception:
            pass

    def _save_custom_icon(self, silent=False):
        """保存自定义图标配置"""
        if not self.current_svg:
            if not silent:
                QMessageBox.warning(self, "错误", "没有可保存的内容")
            return False
        
        filename = self.control.get_filename()
        if not filename:
            if not silent:
                QMessageBox.warning(self, "错误", "请输入图标名称")
            return False
        
        # 收集保存数据
        import time
        save_data = {
            "bg_color": self.control.bg_block.get_color(),
            "gradient_start": self.control.start_block.get_color(),
            "gradient_end": self.control.end_block.get_color(),
            "svg_content": self.current_svg,
            "icon_transform": self.preview_canvas.get_icon_transform(),
            "timestamp": time.time()
        }
        
        # 保存到文件
        if self.save_manager.save_custom_icon(filename, save_data):
            self.load_custom_icons()  # 刷新列表
            self.statusBar().showMessage(f"已保存自定义图标: {filename}")
            if not silent:
                QMessageBox.information(self, "保存成功", f"自定义图标 '{filename}' 已保存！")
            return True
        else:
            if not silent:
                QMessageBox.warning(self, "保存失败", "无法保存自定义图标，请检查权限")
            return False

    def _load_custom_icon(self, name: str, data: Dict):
        """加载自定义图标配置"""
        try:
            # 更新文件名输入框
            self.control.filename_input.setText(name)
            
            # 加载颜色配置
            if "bg_color" in data and "gradient_start" in data and "gradient_end" in data:
                self.control.bg_block.set_color(data["bg_color"])
                self.control.start_block.set_color(data["gradient_start"])
                self.control.end_block.set_color(data["gradient_end"])
                self.control.content.deselect_all()
                self.control.content.overall_block.set_selected(True)
                self.control.sync_color_to_palette(data["bg_color"])
                self._update_colors(data["bg_color"], data["gradient_start"], data["gradient_end"])
            
            # 加载图标变换
            if "icon_transform" in data:
                icon_transform = data["icon_transform"]
                
                # 如果有图标路径，尝试加载图标
                if "path" in icon_transform and icon_transform["path"] and os.path.exists(icon_transform["path"]):
                    icon_path = icon_transform["path"]
                    pixmap = None
                    
                    if icon_path.lower().endswith('.ico'):
                        pixmap = QPixmap(icon_path)
                    elif icon_path.lower().endswith('.png'):
                        pixmap = QPixmap(icon_path)
                    elif icon_path.lower().endswith('.exe'):
                        pixmap = self._extract_exe_pixmap(icon_path)
                    
                    if pixmap and not pixmap.isNull():
                        self.preview_canvas.set_icon(pixmap, icon_path)
                        self.preview_canvas.load_icon_transform(icon_transform)
                        
                        # 更新界面显示
                        self.icon_path_input.setText(icon_path)
                        self.icon_filename_label.setText(f"📁 {os.path.basename(icon_path)}")
                        self.icon_preview.setPixmap(pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                        
                        # 更新文件名输入框
                        name_without_ext = os.path.splitext(os.path.basename(icon_path))[0]
                        self.control.filename_input.setText(name_without_ext)
                else:
                    # 仅加载变换信息（无图标文件）
                    self.preview_canvas.load_icon_transform(icon_transform)
            
            self.statusBar().showMessage("已加载自定义图标配置")
            
        except Exception as e:
            QMessageBox.warning(self, "加载失败", f"无法加载自定义图标：{str(e)}")

    def _delete_custom_icon(self, icon_name: str):
        """删除自定义图标"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除自定义图标 '{icon_name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            ok, message = self._delete_custom_icon_assets(icon_name)
            if ok:
                self.load_custom_icons()
                self.statusBar().showMessage(f"已删除自定义图标: {icon_name}")
            else:
                QMessageBox.warning(self, "删除失败", message)

    def _delete_custom_icon_assets(self, icon_name: str) -> Tuple[bool, str]:
        """删除自定义图标的磁盘文件、缓存文件与配置文件，并清理内存缓存。"""
        safe_icon_name = _safe_name(icon_name)
        ico_path = Path(self.ico_output_dir) / f"{safe_icon_name}.ico"
        json_path = Path(self.save_manager.save_dir) / f"{safe_icon_name}.json"
        cache_candidates = [
            ico_path.with_suffix(".ico_thumb"),
            ico_path.with_suffix(".ico_cache"),
            ico_path.with_suffix(".ico.tmp"),
            ico_path.with_suffix(".ico.temp"),
        ]

        self._release_custom_icon_references(icon_name, ico_path)
        gc.collect()

        paths_to_remove = _iter_existing_paths([*cache_candidates, ico_path, json_path])
        if not paths_to_remove:
            self.custom_icon_panel.evict_preview_cache(icon_name)
            return True, "文件已不存在"

        trash_dir = Path(get_app_root_dir()) / ".cache" / ".trash"
        ok, message, moves = _move_to_trash(paths_to_remove, trash_dir)
        if not ok:
            return False, message

        trash_paths = [dst for dst, _ in moves]
        _unlink_best_effort(trash_paths)
        return True, "ok"

    def _release_custom_icon_references(self, icon_name: str, ico_path: Path) -> None:
        """释放可能占用图标文件的引用，并清理相关内存/Qt 缓存。"""
        try:
            self.custom_icon_panel.evict_preview_cache(icon_name)
        except Exception:
            logger.exception("清理自定义图标预览缓存失败: %s", icon_name)

        try:
            ico_abs = os.path.abspath(str(ico_path))
            if self.preview_canvas and os.path.abspath(self.preview_canvas.icon_path) == ico_abs:
                self.preview_canvas.clear_icon()
                self.icon_preview.clear()
                if self.icon_path_input.text().strip() == ico_abs:
                    self.icon_path_input.clear()
                    self.icon_filename_label.setText("📁 选择图标")
        except Exception:
            logger.exception("释放画布图标引用失败: %s", ico_path)

        try:
            QPixmapCache.remove(str(ico_path))
            QPixmapCache.remove(icon_name)
        except Exception:
            logger.exception("清理 QPixmapCache 失败: %s", ico_path)

    def _select_icon_file(self):
        """选择图标文件"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "选择图标文件", 
            "", 
            "图标文件 (*.exe *.ico *.png);;可执行文件 (*.exe);;图标文件 (*.ico);;PNG图片 (*.png);;所有文件 (*.*)"
        )
        if file_path:
            self.icon_path_input.setText(file_path)
            # 如果选择了文件，搜索该文件所在目录
            self._load_icons_from_path(file_path)
    
    def _select_icon_folder(self):
        """选择文件夹"""
        folder_path = QFileDialog.getExistingDirectory(self, "选择文件夹", "")
        if folder_path:
            self.icon_path_input.setText(folder_path)
            self._load_icons_from_path(folder_path)

    def _on_icon_path_enter(self):
        """用户在路径输入框按回车时加载图标"""
        path = self.icon_path_input.text().strip()
        if not path:
            self.icon_preview.clear()
            self.icon_filename_label.setText("📁 选择图标")
            return
        
        if os.path.exists(path):
            self._load_icons_from_path(path)
        else:
            self.icon_preview.clear()
            self.icon_filename_label.setText("⚠️ 路径不存在")

    def _load_icons_from_path(self, path: str):
        """从路径加载图标"""
        try:
            # 如果是单个文件，直接加载
            if os.path.isfile(path):
                self._load_single_icon(path)
                # 同时扫描目录以便切换
                search_dir = os.path.dirname(path)
                self.exe_files = []
                self.ico_files = []
                self.png_files = []
                if os.path.isdir(search_dir):
                    for file in sorted(os.listdir(search_dir)):
                        if file.lower().endswith('.exe'):
                            self.exe_files.append(os.path.join(search_dir, file))
                        elif file.lower().endswith('.ico'):
                            self.ico_files.append(os.path.join(search_dir, file))
                        elif file.lower().endswith('.png'):
                            png_path = os.path.join(search_dir, file)
                            pixmap = QPixmap(png_path)
                            if not pixmap.isNull() and pixmap.width() <= 128 and pixmap.height() <= 128:
                                self.png_files.append(png_path)
                self.icon_files = self.exe_files + self.ico_files + self.png_files
                # 确保当前文件在列表中
                if path not in self.icon_files:
                    self.icon_files.insert(0, path)
                self.current_icon_index = self.icon_files.index(path)
                return
            
            # 如果是目录，搜索目录下的图标文件
            if os.path.isdir(path):
                self.exe_files = []
                self.ico_files = []
                self.png_files = []
                for file in sorted(os.listdir(path)):
                    if file.lower().endswith('.exe'):
                        self.exe_files.append(os.path.join(path, file))
                    elif file.lower().endswith('.ico'):
                        self.ico_files.append(os.path.join(path, file))
                    elif file.lower().endswith('.png'):
                        png_path = os.path.join(path, file)
                        pixmap = QPixmap(png_path)
                        if not pixmap.isNull() and pixmap.width() <= 128 and pixmap.height() <= 128:
                            self.png_files.append(png_path)
                
                self.icon_files = self.exe_files + self.ico_files + self.png_files
                self.current_icon_index = 0
                
                if self.icon_files:
                    self._load_current_icon()
                else:
                    self.icon_preview.clear()
                    self.icon_filename_label.setText("⚠️ 未找到图标，支持exe、ico、png")
        except Exception as e:
            print(f"加载图标失败: {e}")
            self.icon_preview.clear()
            self.icon_filename_label.setText("⚠️ 加载失败")
    
    def _load_single_icon(self, path: str):
        """直接加载单个图标文件"""
        filename = os.path.basename(path)
        self.icon_filename_label.setText(f"📁 {filename}")
        
        # 更新名称输入框（去掉后缀，保留特殊符号）
        name_without_ext = os.path.splitext(filename)[0]
        self.control.filename_input.setText(name_without_ext)
        
        pixmap = None
        if path.lower().endswith('.ico'):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.icon_preview.setPixmap(pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                self.icon_preview.clear()
        elif path.lower().endswith('.png'):
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                if pixmap.width() <= 128 and pixmap.height() <= 128:
                    self.icon_preview.setPixmap(pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                else:
                    QMessageBox.warning(self, "提示", f"PNG图片尺寸过大\n当前: {pixmap.width()}x{pixmap.height()}\n请选择128x128以下的图片")
                    self.icon_preview.clear()
            else:
                self.icon_preview.clear()
        elif path.lower().endswith('.exe'):
            pixmap = self._extract_exe_pixmap(path)
            self._extract_exe_icon(path)
        else:
            self.icon_preview.clear()
            self.icon_filename_label.setText("⚠️ 不支持的文件格式")
        
        # 自动添加到画布
        if pixmap and not pixmap.isNull():
            self.preview_canvas.set_icon(pixmap, path)
            self.preview_canvas.set_icon_opacity(self.icon_opacity)
            self.statusBar().showMessage(f"已添加图标: {filename}")
    
    def _load_current_icon(self):
        """加载当前索引的图标"""
        if not hasattr(self, 'icon_files') or not self.icon_files:
            return
        
        if 0 <= self.current_icon_index < len(self.icon_files):
            icon_path = self.icon_files[self.current_icon_index]
            filename = os.path.basename(icon_path)
            self.icon_filename_label.setText(f"📁 {filename}")
            
            # 更新名称输入框（去掉后缀，保留特殊符号）
            name_without_ext = os.path.splitext(filename)[0]
            self.control.filename_input.setText(name_without_ext)
            
            pixmap = None
            if icon_path.lower().endswith('.ico'):
                pixmap = QPixmap(icon_path)
                if not pixmap.isNull():
                    self.icon_preview.setPixmap(pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                else:
                    self.icon_preview.clear()
            elif icon_path.lower().endswith('.png'):
                pixmap = QPixmap(icon_path)
                if not pixmap.isNull():
                    self.icon_preview.setPixmap(pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                else:
                    self.icon_preview.clear()
            elif icon_path.lower().endswith('.exe'):
                pixmap = self._extract_exe_pixmap(icon_path)
                self._extract_exe_icon(icon_path)
            
            # 自动添加到画布
            if pixmap and not pixmap.isNull():
                self.preview_canvas.set_icon(pixmap, icon_path)
                self.preview_canvas.set_icon_opacity(self.icon_opacity)
                self.statusBar().showMessage(f"已添加图标: {filename}")
    
    def _prev_icon(self):
        """切换到上一个图标"""
        if not hasattr(self, 'icon_files') or not self.icon_files:
            return
        self.current_icon_index = (self.current_icon_index - 1) % len(self.icon_files)
        self._load_current_icon()
    
    def _next_icon(self):
        """切换到下一个图标"""
        if not hasattr(self, 'icon_files') or not self.icon_files:
            return
        self.current_icon_index = (self.current_icon_index + 1) % len(self.icon_files)
        self._load_current_icon()

    def _extract_exe_icon(self, exe_path: str):
        """从exe文件提取图标"""
        try:
            # 使用QFileIconProvider获取exe图标
            from PyQt6.QtWidgets import QFileIconProvider
            from PyQt6.QtCore import QFileInfo
            
            provider = QFileIconProvider()
            info = QFileInfo(exe_path)
            icon = provider.icon(info)
            
            if not icon.isNull():
                pixmap = icon.pixmap(QSize(48, 48))
                self.icon_preview.setPixmap(pixmap.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            else:
                self.icon_preview.clear()
        except Exception as e:
            print(f"提取exe图标失败: {e}")
            self.icon_preview.clear()

    def _on_opacity_changed(self, value: int):
        """透明度滑条变化"""
        self.opacity_value_label.setText(f"{value}%")
        self.icon_opacity = value
        # 实时更新画布上的图标透明度
        self.preview_canvas.set_icon_opacity(value)

    def _add_icon_to_canvas(self):
        """添加图标到画布"""
        # 检查是否有当前选中的图标
        if not hasattr(self, 'icon_files') or not self.icon_files:
            QMessageBox.warning(self, "提示", "请先选择一个图标文件")
            return
        
        if self.current_icon_index < 0 or self.current_icon_index >= len(self.icon_files):
            QMessageBox.warning(self, "提示", "请先选择一个图标文件")
            return
        
        icon_path = self.icon_files[self.current_icon_index]
        
        # 加载图标
        if icon_path.lower().endswith('.ico'):
            pixmap = QPixmap(icon_path)
        elif icon_path.lower().endswith('.png'):
            pixmap = QPixmap(icon_path)
        elif icon_path.lower().endswith('.exe'):
            # 从exe提取图标
            pixmap = self._extract_exe_pixmap(icon_path)
        else:
            QMessageBox.warning(self, "提示", "不支持的图标格式")
            return
        
        if pixmap.isNull():
            QMessageBox.warning(self, "提示", "无法加载图标")
            return
        
        # 设置图标到画布
        self.preview_canvas.set_icon(pixmap, icon_path)
        self.preview_canvas.set_icon_opacity(self.icon_opacity)
        self.statusBar().showMessage(f"已添加图标: {os.path.basename(icon_path)}")

    def _remove_icon_from_canvas(self):
        """从画布移出图标"""
        self.preview_canvas.clear_icon()
        self.statusBar().showMessage("已移除图标")

    def _extract_exe_pixmap(self, exe_path: str):
        """从exe文件提取图标并返回QPixmap"""
        try:
            from PyQt6.QtWidgets import QFileIconProvider
            from PyQt6.QtCore import QFileInfo
            
            provider = QFileIconProvider()
            info = QFileInfo(exe_path)
            icon = provider.icon(info)
            
            if not icon.isNull():
                # 获取较大尺寸的图标
                return icon.pixmap(QSize(64, 64))
            return QPixmap()
        except Exception as e:
            print(f"提取exe图标失败: {e}")
            return QPixmap()


# ==================== 启动 ====================
def main():
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 9))

    # 获取命令行参数（第一个参数作为初始路径）
    initial_path = ""
    if len(sys.argv) > 1:
        # 获取除了脚本名之外的所有参数，并用空格连接（处理某些环境下路径未正确转义的情况）
        # 但通常 sys.argv[1] 已经是完整的路径
        path_arg = sys.argv[1]
        # 去除可能存在的引号
        initial_path = path_arg.strip('"').strip("'")
        # 规范化路径
        initial_path = os.path.abspath(os.path.normpath(initial_path))

    window = IconCreatorWindow()
    
    # 如果有初始路径，则自动填充并加载
    if initial_path:
        # 即使路径不存在也先填进去，方便用户排查
        window.icon_path_input.setText(initial_path)
        if os.path.exists(initial_path):
            window._load_icons_from_path(initial_path)
        else:
            window.statusBar().showMessage(f"注意：传入的路径不存在: {initial_path}", 5000)
        
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
