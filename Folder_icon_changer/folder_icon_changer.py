#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Folder Icon Changer - 文件夹图标更换工具
基于 PyQt6 开发，支持拖拽和双击应用图标
"""

import sys
import os
import json
import shutil
import struct
import ctypes
import subprocess
import logging
import unicodedata
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


# ==================== 性能与日志 ====================
def _get_app_root_dir() -> str:
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.basename(exe_dir).lower() == "bin":
            return os.path.dirname(exe_dir)
        return exe_dir
    return os.path.dirname(os.path.abspath(__file__))


def _get_perf_log_path() -> str:
    return os.path.join(_get_app_root_dir(), ".cache", "perf.jsonl")


def _is_perf_enabled() -> bool:
    return os.environ.get("FIC_PERF", "").strip() not in ("", "0", "false", "False")


def _append_perf_event(payload: Dict):
    if not _is_perf_enabled():
        return
    try:
        os.makedirs(os.path.join(_get_app_root_dir(), ".cache"), exist_ok=True)
        payload = dict(payload)
        payload.setdefault("ts", time.time())
        payload.setdefault("pid", os.getpid())
        with open(_get_perf_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


@contextmanager
def perf_span(name: str, **fields):
    start = time.perf_counter_ns()
    try:
        yield
    finally:
        dur_ms = (time.perf_counter_ns() - start) / 1_000_000
        _append_perf_event({"name": name, "dur_ms": dur_ms, **fields})


# ==================== 资源路径处理 ====================
def get_app_dir() -> str:
    """获取程序数据目录（用于存放 .cache 和 ico 等输出文件），强制位于 EXE 同级"""
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
    """获取只读资源目录（如打包进 exe 的素材），优先使用 _MEIPASS"""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path: str) -> str:
    """获取资源文件的绝对路径"""
    return os.path.join(get_resource_dir(), relative_path)

def get_ico_directory() -> str:
    """获取 ico 文件夹的路径"""
    base_dir = get_app_root_dir()
    ico_dir = os.path.join(base_dir, 'ico')
    
    # 强制创建 ico 及其子目录 CustomIco
    try:
        os.makedirs(os.path.join(ico_dir, "CustomIco"), exist_ok=True)
    except Exception as e:
        print(f"创建 ico 目录失败: {e}")
        
    return ico_dir


def open_icon_downloader_ui(parent=None, *, script_path: Optional[str] = None, test_mode: bool = False):
    base_dir = get_app_dir()
    root_dir = get_app_root_dir()
    
    target_script = script_path or os.path.join(base_dir, "icon_downloader.py")
    target_exe = os.path.join(base_dir, "icon_downloader.exe")

    log_path = os.path.join(root_dir, ".cache", "folder_icon_changer.log")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
    except Exception:
        pass

    try:
        logger = logging.getLogger("folder_icon_changer")
        if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == log_path for h in logger.handlers):
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
    except Exception:
        logger = None

    args = None
    if getattr(sys, 'frozen', False):
        if os.path.exists(target_exe):
            args = [target_exe, "--ui"]
            if test_mode:
                args = [target_exe, "--ui-smoke-test"]
        else:
            args = [sys.executable, "--run-downloader", "--ui"]
            if test_mode:
                args = [sys.executable, "--run-downloader", "--ui-smoke-test"]
    else:
        if not os.path.exists(target_script) or not os.path.isfile(target_script):
            msg = f"未找到下载器脚本：\n{target_script}"
            if logger:
                logger.error(msg)
            QMessageBox.critical(parent, "错误", msg)
            return None

        if not os.access(target_script, os.R_OK):
            msg = f"没有权限读取下载器脚本：\n{target_script}"
            if logger:
                logger.error(msg)
            QMessageBox.critical(parent, "错误", msg)
            return None

        args = [sys.executable, target_script, "--ui"]
        if test_mode:
            args = [sys.executable, target_script, "--ui-smoke-test"]

    try:
        proc = subprocess.Popen(args, cwd=base_dir)
        return proc
    except PermissionError as e:
        msg = f"启动下载器失败（权限不足）：\n{e}"
        if logger:
            logger.error(msg)
        QMessageBox.critical(parent, "错误", msg)
        return None
    except Exception as e:
        msg = f"启动下载器失败：\n{e}"
        if logger:
            logger.error(msg)
        QMessageBox.critical(parent, "错误", msg)
        return None

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QLineEdit, QPushButton, QListWidget, QListWidgetItem,
    QScrollArea, QGridLayout, QFrame, QFileDialog, QMessageBox,
    QSplitter, QTreeWidget, QTreeWidgetItem, QAbstractItemView,
    QSizePolicy, QSpacerItem, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import (
    Qt, QSize, QTimer, QPropertyAnimation, QEasingCurve,
    pyqtSignal, QThread, QMutex, QWaitCondition, QRect, QPoint, QRectF
)
from PyQt6.QtGui import QPixmap, QIcon, QImage, QPainter, QColor, QFont, QFontMetrics, QPalette, QPen, QBrush
from PyQt6.QtSvg import QSvgRenderer


# ==================== 管理员权限检查与提升 ====================
def is_admin():
    """检查是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def run_as_admin():
    """以管理员权限重新运行程序"""
    try:
        if sys.platform == 'win32':
            script = os.path.abspath(sys.argv[0])
            params = ' '.join([script] + sys.argv[1:])
            # 使用 ShellExecuteW 以管理员权限运行
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, f'"{script}"', None, 1
            )
            sys.exit(0)
    except Exception as e:
        print(f"申请管理员权限失败: {e}")


# ==================== ICO 文件解析器 ====================
class IcoParser:
    """解析 .ico 文件并提取图像"""
    
    # 图标缓存：{(filepath, size): QPixmap}
    _pixmap_cache: Dict[Tuple[str, int], QPixmap] = {}
    _cache_enabled = True
    
    @classmethod
    def clear_cache(cls):
        """清空图标缓存"""
        cls._pixmap_cache.clear()

    @classmethod
    def evict(cls, filepath: str):
        if not filepath:
            return
        keys = [k for k in cls._pixmap_cache.keys() if k and k[0] == filepath]
        for k in keys:
            cls._pixmap_cache.pop(k, None)
    
    @classmethod
    def set_cache_enabled(cls, enabled: bool):
        """启用/禁用缓存"""
        cls._cache_enabled = enabled
    
    @classmethod
    def load_ico(cls, filepath: str, size: int = 64) -> Optional[QPixmap]:
        """加载 ico 文件并返回指定尺寸的 QPixmap（带缓存）"""
        # 检查缓存
        cache_key = (filepath, size)
        if cls._cache_enabled and cache_key in cls._pixmap_cache:
            return cls._pixmap_cache[cache_key]
        
        try:
            pixmap = QPixmap(filepath)
            if not pixmap.isNull():
                result = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                if cls._cache_enabled:
                    cls._pixmap_cache[cache_key] = result
                return result
            
            with open(filepath, 'rb') as f:
                data = f.read(6)
                if len(data) < 6:
                    return None
                
                reserved, ico_type, count = struct.unpack('<HHH', data)
                if ico_type != 1:
                    return None
                
                best_entry = None
                best_size = 0
                
                for i in range(count):
                    entry_data = f.read(16)
                    if len(entry_data) < 16:
                        break
                    
                    width, height, colors, reserved2, planes, bpp, size_img, offset = struct.unpack('<BBBBHHII', entry_data)
                    img_size = max(width if width > 0 else 256, height if height > 0 else 256)
                    if best_entry is None or abs(img_size - size) < abs(best_size - size):
                        best_entry = (offset, size_img, width, height)
                        best_size = img_size
                
                if best_entry is None:
                    return None
                
                offset, size_img, width, height = best_entry
                f.seek(offset)
                img_data = f.read(size_img)
                
                if img_data[:4] == b'\x89PNG':
                    pixmap = QPixmap()
                    if pixmap.loadFromData(img_data, 'PNG'):
                        result = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        if cls._cache_enabled:
                            cls._pixmap_cache[cache_key] = result
                        return result
                
                pixmap = QPixmap()
                if pixmap.loadFromData(img_data, 'BMP'):
                    result = pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    if cls._cache_enabled:
                        cls._pixmap_cache[cache_key] = result
                    return result
                
                return None
                
        except Exception as e:
            print(f"加载 ICO 失败 {filepath}: {e}")
            return None
        
        return None


# ==================== 文件夹图标读取器 ====================
class FolderIconReader:
    """读取文件夹的自定义图标"""
    
    @staticmethod
    def get_folder_icon(folder_path: str, size: int = 16) -> Optional[QIcon]:
        """读取文件夹的自定义图标"""
        try:
            desktop_ini_path = os.path.join(folder_path, 'desktop.ini')
            
            if not os.path.exists(desktop_ini_path):
                return None
            
            with open(desktop_ini_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            icon_path = None
            for line in content.split('\n'):
                line = line.strip()
                if line.lower().startswith('iconresource'):
                    value = line.split('=', 1)[1].strip()
                    if ',' in value:
                        value = value.rsplit(',', 1)[0]
                    icon_path = value
                    break
            
            if not icon_path:
                return None
            
            if not os.path.isabs(icon_path):
                icon_path = os.path.abspath(os.path.join(folder_path, icon_path))
            
            if not os.path.exists(icon_path):
                return None
            
            if icon_path.lower().endswith('.ico'):
                pixmap = IcoParser.load_ico(icon_path, size)
                if pixmap:
                    return QIcon(pixmap)
            
            return None
            
        except Exception as e:
            return None


# ==================== 文件夹缓存管理器 ====================
class FolderCache:
    """文件夹结构缓存管理"""
    
    CACHE_VERSION = 6  # 版本升级，增加已应用图标的文件夹记录
    
    def __init__(self, cache_dir: str = None):
        if cache_dir is None:
            cache_dir = os.path.join(get_app_root_dir(), '.cache')
        
        self.cache_dir = Path(cache_dir)
        try:
            self.cache_dir.mkdir(exist_ok=True)
        except Exception as e:
            print(f"创建缓存目录失败: {e}")
        
        self.folder_cache_file = self.cache_dir / 'folder_cache.json'
        self.folder_cache: Dict = {}
        self.recent_folders: List[str] = []  # 最近打开的文件夹列表
        self.subfolder_cache: Dict[str, List[str]] = {}  # 文件夹的子文件夹列表缓存
        self.applied_folders: Dict[str, List[str]] = {}  # 记录每个根文件夹下已应用图标的文件夹列表
        
        self.load_folder_cache()
    
    def load_folder_cache(self) -> Dict:
        if self.folder_cache_file.exists():
            try:
                with open(self.folder_cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if data.get('version') == self.CACHE_VERSION:
                        self.folder_cache = data.get('folders', {})
                        self.recent_folders = data.get('recent_folders', [])
                        self.subfolder_cache = data.get('subfolder_cache', {})
                        self.applied_folders = data.get('applied_folders', {})
                        return self.folder_cache
                    elif data.get('version', 0) < self.CACHE_VERSION:
                        # 旧版本缓存，保留 recent_folders 和 applied_folders（如果有）
                        self.recent_folders = data.get('recent_folders', [])
                        self.applied_folders = data.get('applied_folders', {})
            except Exception as e:
                print(f"加载文件夹缓存失败: {e}")
        return {}
    
    def save_folder_cache(self, folders: Dict):
        self.folder_cache = folders
        self._save()
    
    def add_recent_folder(self, folder_path: str):
        """添加最近打开的文件夹"""
        if folder_path in self.recent_folders:
            self.recent_folders.remove(folder_path)
        self.recent_folders.insert(0, folder_path)
        # 只保留最近10个
        self.recent_folders = self.recent_folders[:10]
        self._save()
    
    def get_last_folder(self) -> Optional[str]:
        """获取上次打开的文件夹"""
        if self.recent_folders:
            last = self.recent_folders[0]
            if os.path.exists(last):
                return last
        return None
    
    def save_subfolders(self, folder_path: str, subfolders: List[str]):
        """缓存文件夹的子文件夹列表"""
        self.subfolder_cache[folder_path] = subfolders
        self._save()
    
    def get_subfolders(self, folder_path: str) -> Optional[List[str]]:
        """获取缓存的子文件夹列表"""
        subfolders = self.subfolder_cache.get(folder_path)
        if subfolders:
            # 验证缓存的文件夹是否仍然存在
            valid_subfolders = [f for f in subfolders if os.path.exists(f)]
            if len(valid_subfolders) == len(subfolders):
                return valid_subfolders
        return None
    
    def remove_subfolder_cache(self, folder_path: str):
        """移除某个文件夹的子文件夹缓存"""
        if folder_path in self.subfolder_cache:
            del self.subfolder_cache[folder_path]
            self._save()
    
    def add_applied_folders(self, root_folder: str, applied_folders: List[str]):
        """批量记录已应用图标的文件夹"""
        if root_folder not in self.applied_folders:
            self.applied_folders[root_folder] = []
        
        for folder in applied_folders:
            if folder not in self.applied_folders[root_folder]:
                self.applied_folders[root_folder].append(folder)
        
        self._save()
    
    def get_applied_folders(self, root_folder: str) -> List[str]:
        """获取某个根文件夹下已应用图标的文件夹列表
        
        返回已验证存在的文件夹列表
        """
        folders = self.applied_folders.get(root_folder, [])
        # 过滤掉不存在的文件夹
        return [f for f in folders if os.path.exists(f)]
    
    def remove_applied_folders(self, root_folder: str, folders_to_remove: List[str]):
        """从已应用列表中移除文件夹（恢复图标后调用）"""
        if root_folder in self.applied_folders:
            for folder in folders_to_remove:
                if folder in self.applied_folders[root_folder]:
                    self.applied_folders[root_folder].remove(folder)
            
            # 如果列表为空，删除整个键
            if not self.applied_folders[root_folder]:
                del self.applied_folders[root_folder]
            
            self._save()
    
    def clear_applied_folders(self, root_folder: str):
        """清除某个根文件夹的所有已应用记录"""
        if root_folder in self.applied_folders:
            del self.applied_folders[root_folder]
            self._save()
    
    def _save(self):
        try:
            with open(self.folder_cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'version': self.CACHE_VERSION,
                    'folders': self.folder_cache,
                    'recent_folders': self.recent_folders,
                    'subfolder_cache': self.subfolder_cache,
                    'applied_folders': self.applied_folders
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存缓存失败: {e}")
    
    def clear_cache(self):
        self.folder_cache = {}
        self.recent_folders = []
        self.subfolder_cache = {}
        self.applied_folders = {}
        if self.folder_cache_file.exists():
            self.folder_cache_file.unlink()
        
        if self.cache_dir.exists():
            try:
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(exist_ok=True)
            except:
                pass


# ==================== 懒加载文件夹树组件 ====================
class LazyFolderTreeWidget(QTreeWidget):
    """懒加载文件夹树组件"""
    
    # 定义信号
    apply_icon_requested = pyqtSignal(str)  # 应用图标信号
    restore_icon_requested = pyqtSignal(str)  # 恢复图标信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)  # 隐藏标题
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 移除选中时的蚂蚁线边框
        
        self._scanned_paths = set()
        self._icon_size = 16
        
        self.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #ddd;
                border-radius: 4px;
                background: #fff;
                color: #333333;
            }
            QTreeWidget::item {
                padding: 4px;
                border-radius: 3px;
                color: #333333;
                outline: none;
            }
            QTreeWidget::item:selected {
                background: #e3f2fd;
                color: #000000;
                outline: none;
            }
            QTreeWidget::item:hover {
                background: #f5f5f5;
            }
            QTreeWidget::item:focus {
                outline: none;
                border: none;
            }
            QHeaderView::section {
                color: #333333;
            }
            /* 滚动条样式 */
            QScrollBar:vertical {
                border: none;
                background: #f0f0f0;
                width: 10px;
                margin: 0px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #c0c0c0;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #a0a0a0;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        
        self.itemExpanded.connect(self._on_item_expanded)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
    
    def _show_context_menu(self, position):
        """显示右键菜单"""
        item = self.itemAt(position)
        if not item:
            return
        
        folder_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not folder_path:
            return
        
        from PyQt6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
            }
        """)
        
        action_apply = menu.addAction("✨ 应用图标")
        action_restore = menu.addAction("↩️ 恢复默认")
        
        action = menu.exec(self.mapToGlobal(position))
        
        if action == action_apply:
            if self.apply_icon_requested:
                self.apply_icon_requested.emit(folder_path)
        elif action == action_restore:
            if self.restore_icon_requested:
                self.restore_icon_requested.emit(folder_path)
    
    def highlight_success(self, folder_path: str):
        """成功应用图标后，刷新并选中该文件夹"""
        # 刷新图标显示
        self.refresh_item_icon(folder_path)
    
    def _on_item_expanded(self, item: QTreeWidgetItem):
        folder_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not folder_path:
            return
        
        if folder_path in self._scanned_paths:
            return
        
        has_placeholder = False
        for i in range(item.childCount()):
            child = item.child(i)
            if child.data(0, Qt.ItemDataRole.UserRole) == "__placeholder__":
                has_placeholder = True
                break
        
        if has_placeholder:
            item.takeChildren()
            self._load_subfolders(item, folder_path)
    
    def _get_folder_icon(self, folder_path: str) -> QIcon:
        custom_icon = FolderIconReader.get_folder_icon(folder_path, self._icon_size)
        if custom_icon:
            return custom_icon
        return self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon)
    
    def _load_subfolders(self, parent_item: QTreeWidgetItem, folder_path: str):
        try:
            subfolders = []
            
            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.startswith('.'):
                            continue
                        try:
                            if sys.platform == 'win32':
                                import stat
                                attrs = entry.stat(follow_symlinks=False).st_file_attributes
                                if attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM):
                                    continue
                        except:
                            pass
                        subfolders.append((entry.name, entry.path))
            
            subfolders.sort(key=lambda x: x[0].lower())
            
            for name, path in subfolders:
                child_item = QTreeWidgetItem(parent_item)
                child_item.setText(0, name)
                child_item.setData(0, Qt.ItemDataRole.UserRole, path)
                child_item.setIcon(0, self._get_folder_icon(path))
                
                has_children = self._has_subfolders(path)
                if has_children:
                    placeholder = QTreeWidgetItem(child_item)
                    placeholder.setText(0, "加载中...")
                    placeholder.setData(0, Qt.ItemDataRole.UserRole, "__placeholder__")
            
            self._scanned_paths.add(folder_path)
            
        except PermissionError:
            pass
        except Exception as e:
            print(f"加载子文件夹失败: {e}")
    
    def _has_subfolders(self, folder_path: str) -> bool:
        try:
            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.startswith('.'):
                            continue
                        try:
                            if sys.platform == 'win32':
                                import stat
                                attrs = entry.stat(follow_symlinks=False).st_file_attributes
                                if attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM):
                                    continue
                        except:
                            pass
                        return True
            return False
        except:
            return False
    
    def load_root_folder(self, root_path: str):
        self.clear()
        self._scanned_paths.clear()
        
        if not os.path.exists(root_path):
            return
        
        root_item = QTreeWidgetItem(self)
        root_item.setText(0, os.path.basename(root_path))
        root_item.setData(0, Qt.ItemDataRole.UserRole, root_path)
        root_item.setIcon(0, self._get_folder_icon(root_path))
        
        subfolders = []
        try:
            with os.scandir(root_path) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.startswith('.'):
                            continue
                        try:
                            if sys.platform == 'win32':
                                import stat
                                attrs = entry.stat(follow_symlinks=False).st_file_attributes
                                if attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM):
                                    continue
                        except:
                            pass
                        subfolders.append((entry.name, entry.path))
        except PermissionError:
            pass
        except Exception as e:
            print(f"加载根文件夹失败: {e}")
        
        subfolders.sort(key=lambda x: x[0].lower())
        
        for name, path in subfolders:
            child_item = QTreeWidgetItem(root_item)
            child_item.setText(0, name)
            child_item.setData(0, Qt.ItemDataRole.UserRole, path)
            child_item.setIcon(0, self._get_folder_icon(path))
            
            has_children = self._has_subfolders(path)
            if has_children:
                placeholder = QTreeWidgetItem(child_item)
                placeholder.setText(0, "加载中...")
                placeholder.setData(0, Qt.ItemDataRole.UserRole, "__placeholder__")
        
        self._scanned_paths.add(root_path)
        root_item.setExpanded(True)
    
    def refresh_all_icons(self):
        """递归刷新树中所有项的图标"""
        def update_item(item: QTreeWidgetItem):
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path and path != "__placeholder__":
                item.setIcon(0, self._get_folder_icon(path))
            
            for i in range(item.childCount()):
                update_item(item.child(i))
        
        for i in range(self.topLevelItemCount()):
            update_item(self.topLevelItem(i))

    def refresh_item_icon(self, folder_path: str):
        def update_icon(item: QTreeWidgetItem):
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path == folder_path:
                item.setIcon(0, self._get_folder_icon(path))
                return True
            
            for i in range(item.childCount()):
                if update_icon(item.child(i)):
                    return True
            return False
        
        for i in range(self.topLevelItemCount()):
            if update_icon(self.topLevelItem(i)):
                break


# ==================== 滚动标签组件 ====================
class ScrollingLabel(QWidget):
    """支持文字滚动显示的标签组件
    
    特性：
    - 文本超出时末尾显示 "..." 提示用户名称过长
    - 悬停时滚动显示完整名称
    - 滚动到最右侧时才完整显示名称末尾
    """
    
    def __init__(self, text: str = "", max_width: int = 80, parent=None):
        super().__init__(parent)
        self._text = text
        self._max_width = max_width
        self._scroll_offset = 0
        self._scroll_direction = 1  # 1: 向左滚动, -1: 向右滚动
        self._is_scrolling = False
        self._text_width = 0
        self._pause_count = 0
        self._ellipsis_width = 0  # 省略号宽度
        
        self.setFixedHeight(16)
        self.setFixedWidth(max_width)
        
        # 计算文本宽度
        font = QFont("Microsoft YaHei", 10)
        fm = QFontMetrics(font)
        self._text_width = fm.horizontalAdvance(text)
        self._ellipsis_width = fm.horizontalAdvance("...")
        
        # 滚动定时器
        self._scroll_timer = QTimer(self)
        self._scroll_timer.timeout.connect(self._on_scroll)
        self._scroll_timer.setInterval(50)  # 滚动速度
        
        # 开启鼠标追踪，确保能接收到鼠标移动事件
        self.setMouseTracking(True)
        
    def text(self) -> str:
        return self._text
    
    def setText(self, text: str):
        self._text = text
        font = QFont("Microsoft YaHei", 10)
        fm = QFontMetrics(font)
        self._text_width = fm.horizontalAdvance(text)
        self._ellipsis_width = fm.horizontalAdvance("...")
        self._scroll_offset = 0
        self._is_scrolling = False
        self._scroll_timer.stop()
        self.update()
    
    def start_scroll_from_parent(self):
        """从父组件调用的滚动启动方法"""
        if self._text_width > self._max_width:
            self._start_scrolling()
    
    def stop_scroll_from_parent(self):
        """从父组件调用的滚动停止方法"""
        self._stop_scrolling()
    
    def _start_scrolling(self):
        if self._text_width > self._max_width:
            self._is_scrolling = True
            self._scroll_offset = 0
            self._pause_count = 20  # 跳过初始暂停
            self._scroll_direction = 1
            self._scroll_timer.start()
            self.update()
    
    def _stop_scrolling(self):
        self._is_scrolling = False
        self._scroll_timer.stop()
        self._scroll_offset = 0
        self.update()
    
    def _on_scroll(self):
        if not self._is_scrolling:
            return
        
        # 暂停计数（仅在边界处使用）
        if self._pause_count < 20:
            self._pause_count += 1
            return
        
        # 滚动到最右边时能看到完整名称
        max_scroll = self._text_width - self._max_width + 15
        self._scroll_offset += self._scroll_direction * 2
        
        # 到达右边界（显示完整名称），暂停后反向
        if self._scroll_offset >= max_scroll:
            self._scroll_offset = max_scroll
            self._scroll_direction = -1
            self._pause_count = 0
        # 到达左边界，暂停后反向
        elif self._scroll_offset <= 0:
            self._scroll_offset = 0
            self._scroll_direction = 1
            self._pause_count = 0
            
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 设置字体和颜色
        font = QFont("Microsoft YaHei", 10)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#333333")))
        
        if self._text_width > self._max_width:
            if self._is_scrolling:
                # 滚动中：显示滚动的文本
                painter.drawText(-self._scroll_offset + 5, 12, self._text)
            else:
                # 未滚动：显示文本 + 末尾省略号
                # 计算能显示多少字符
                available_width = self._max_width - self._ellipsis_width - 8
                display_text = self._text
                
                # 逐步截断直到适合宽度
                fm = QFontMetrics(font)
                while fm.horizontalAdvance(display_text) > available_width and len(display_text) > 0:
                    display_text = display_text[:-1]
                
                # 绘制截断的文本 + 省略号
                painter.drawText(5, 12, display_text + "...")
        else:
            # 不需要滚动：居中绘制
            x = (self._max_width - self._text_width) // 2
            painter.drawText(x, 12, self._text)


class RoundedMenu(QWidget):
    """自定义圆角菜单，解决原生QMenu圆角显示问题"""
    
    closed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.Popup |
            Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
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

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)
    
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


# ==================== 单个图标项组件 ====================
class IconItem(QFrame):
    """单个图标项组件"""
    
    double_clicked = pyqtSignal(str)
    clicked = pyqtSignal(object)  # 新增：点击信号，传递自己
    delete_requested = pyqtSignal(str, str)  # 删除请求信号 (path, name)
    apply_requested = pyqtSignal(str)  # 新增：应用请求信号 (path)
    
    _current_selected = None  # 类变量，记录当前选中的项
    
    def __init__(self, icon_path: str, icon_name: str, icon_size: int = 64, parent=None):
        super().__init__(parent)
        self.icon_path = icon_path
        self.icon_name = icon_name
        self.icon_size = icon_size
        self._context_menu = None
        
        self.setFixedSize(icon_size + 20, icon_size + 40)
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)
        
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedSize(icon_size, icon_size)
        self.icon_label.setStyleSheet("background: transparent;")
        layout.addWidget(self.icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        
        # 使用滚动标签替代原来的静态标签
        self.name_label = ScrollingLabel(icon_name, max_width=icon_size + 10)
        layout.addWidget(self.name_label, alignment=Qt.AlignmentFlag.AlignHCenter)
        
        self.setStyleSheet("""
            IconItem {
                background: transparent;
                border-radius: 6px;
            }
            IconItem:hover {
                background: #e3f2fd;
            }
            IconItem[selected="true"] {
                background: #bbdefb;
                border: 2px solid #2196f3;
            }
        """)
        
        self._selected = False
        self._loaded = False
    
    def enterEvent(self, event):
        """鼠标进入图标项时，启动名称滚动"""
        self.name_label.start_scroll_from_parent()
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开图标项时，停止名称滚动"""
        self.name_label.stop_scroll_from_parent()
        super().leaveEvent(event)
    
    def load_icon(self):
        if self._loaded:
            return
        
        pixmap = IcoParser.load_ico(self.icon_path, self.icon_size)
        if pixmap:
            self.icon_label.setPixmap(pixmap)
        else:
            self.icon_label.setText("X")
            self.icon_label.setStyleSheet("color: #999999; font-size: 24px;")
        
        self._loaded = True
    
    def set_selected(self, selected: bool):
        # 先取消之前选中的项
        if selected and IconItem._current_selected and IconItem._current_selected != self:
            try:
                # 检查对象是否已被删除（sip.isdeleted 在 PyQt6 中不可用，用 try-except 替代）
                IconItem._current_selected.set_selected(False)
            except RuntimeError:
                # 对象已被删除，清除引用
                IconItem._current_selected = None
        
        self._selected = selected
        try:
            self.setProperty("selected", selected)
            self.style().unpolish(self)
            self.style().polish(self)
        except RuntimeError:
            # 当前对象也已被删除，直接返回
            return
        
        if selected:
            IconItem._current_selected = self
        elif IconItem._current_selected == self:
            IconItem._current_selected = None
    
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self.icon_path)
        super().mouseDoubleClickEvent(event)
    
    def _build_context_menu(self):
        menu = RoundedMenu(self)
        self._context_menu = menu
        menu.closed.connect(lambda: setattr(self, "_context_menu", None))
        
        apply_action = menu.addAction("🎯 应用图标")
        apply_action.triggered = lambda: self.apply_requested.emit(self.icon_path)
        
        if "CustomIco" in self.icon_path:
            delete_action = menu.addAction("🗑️ 删除图标")
            delete_action.triggered = lambda: self.delete_requested.emit(self.icon_path, self.icon_name)
        
        return menu
    
    def contextMenuEvent(self, event):
        """右键菜单事件"""
        try:
            self.set_selected(True)
        except Exception:
            pass
        menu = self._build_context_menu()
        menu.exec(event.globalPos())
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.set_selected(True)
            self.clicked.emit(self)


# ==================== 字母导航栏 ====================
class AlphaNavigationBar(QWidget):
    """字母导航栏"""
    
    letter_clicked = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(50)
        self._current_letter = None
        self._custom_active = False  # 独立记录自定义过滤按钮是否开启
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(2)
        
        # 自定义图标按钮（铅笔）
        self.btn_custom = QPushButton("✏️")  # 使用带变体选择符的 emoji 确保较好的渲染
        self.btn_custom.setFixedSize(40, 26)
        self.btn_custom.setToolTip("显示自定义图标")
        # 设置支持彩色 Emoji 的字体
        self.btn_custom.setFont(QFont("Segoe UI Emoji", 12))
        self.btn_custom.clicked.connect(lambda: self.letter_clicked.emit("✏"))
        layout.addWidget(self.btn_custom)
        
        self.btn_num = QPushButton("#")
        self.btn_num.setFixedSize(40, 26)
        self.btn_num.clicked.connect(lambda: self.letter_clicked.emit("#"))
        layout.addWidget(self.btn_num)
        
        self.letter_buttons = {}
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            btn = QPushButton(letter)
            btn.setFixedSize(40, 26)
            btn.clicked.connect(lambda checked, l=letter: self.letter_clicked.emit(l))
            layout.addWidget(btn)
            self.letter_buttons[letter] = btn
        
        layout.addStretch()
        self._apply_styles()
    
    def _apply_styles(self):
        self.setStyleSheet("""
            AlphaNavigationBar {
                background-color: #f0f0f0;
                border-radius: 8px;
            }
        """)
        
        button_style = """
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 5px;
                font-family: 'Arial', 'Microsoft YaHei', sans-serif;
                font-size: 12px;
                font-weight: bold;
                color: #333333;
            }
            QPushButton:hover {
                background-color: #e3f2fd;
                border-color: #2196f3;
                color: #1976d2;
            }
            QPushButton:pressed {
                background-color: #bbdefb;
            }
        """
        
        self.btn_num.setStyleSheet(button_style)
        self.btn_custom.setStyleSheet(button_style)
        for btn in self.letter_buttons.values():
            btn.setStyleSheet(button_style)
    
    def set_custom_active(self, active: bool):
        """设置自定义图标按钮的高亮状态"""
        self._custom_active = active
        self._update_button_styles()

    def set_current_letter(self, letter: str):
        """设置当前选中的字母分区高亮"""
        self._current_letter = letter
        self._update_button_styles()

    def _update_button_styles(self):
        """统一更新所有按钮的样式"""
        normal_style = """
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 5px;
                font-family: 'Arial', 'Microsoft YaHei', sans-serif;
                font-size: 12px;
                font-weight: bold;
                color: #333333;
            }
            QPushButton:hover {
                background-color: #e3f2fd;
                border-color: #2196f3;
                color: #1976d2;
            }
        """
        
        active_style = """
            QPushButton {
                background-color: #2196f3;
                border: 1px solid #2196f3;
                border-radius: 5px;
                font-family: 'Arial', 'Microsoft YaHei', sans-serif;
                font-size: 12px;
                font-weight: bold;
                color: #ffffff;
            }
        """
        
        # 更新铅笔按钮
        self.btn_custom.setStyleSheet(active_style if self._custom_active else normal_style)
        
        # 更新数字按钮
        self.btn_num.setStyleSheet(active_style if self._current_letter == "#" else normal_style)
        
        # 更新字母按钮
        for letter, btn in self.letter_buttons.items():
            btn.setStyleSheet(active_style if self._current_letter == letter else normal_style)


# ==================== 图标网格内容区域 ====================
class IconGridContent(QWidget):
    """图标网格内容"""
    
    icon_double_clicked = pyqtSignal(str)
    refresh_requested = pyqtSignal()  # 新增：刷新请求信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.icon_items: List[IconItem] = []
        self.icon_data: List[Tuple[str, str]] = []
        self.section_headers: Dict[str, QWidget] = {}
        
        # 缓存：保存原始布局的控件引用
        self._cached_widgets: List[QWidget] = []  # 缓存所有创建的控件（header + grid_widget）
        self._is_filtering = False  # 是否处于搜索过滤状态
        
        self._icon_size = 64
        self._icon_item_width = 84  # 单个图标项的宽度（icon_size + 20）
        self._cols = 6  # 默认列数，会在 resize 时动态计算
        self._icon_name_norm: Dict[str, str] = {}
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(6)
        
        self.hint_label = QLabel("请选择文件夹\n从左侧导航栏选择文件夹，或直接拖拽文件夹到图标上")
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setStyleSheet("color: #666666; font-size: 16px; padding: 40px;")
        self.hint_label.setWordWrap(True)
        self.main_layout.addWidget(self.hint_label)
        self.main_layout.addStretch()

    @staticmethod
    def _normalize_text(text: str) -> str:
        if text is None:
            return ""
        s = str(text)
        s = unicodedata.normalize("NFKC", s)
        s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
        return s.casefold().strip()

    @staticmethod
    def _section_letter(name: str) -> str:
        if not name:
            return "#"
        s = unicodedata.normalize("NFKC", str(name)).lstrip()
        if not s:
            return "#"
        ch = s[0].upper()
        if "A" <= ch <= "Z":
            return ch
        return "#"
    
    def load_icons(self, ico_dir: str):
        with perf_span("load_icons.total", ico_dir=ico_dir):
            self.clear_icons()
        
            if not os.path.exists(ico_dir):
                self.hint_label.show()
                self.hint_label.setText(f"图标文件夹不存在：{ico_dir}")
                return
        
            ico_files = []
            with perf_span("load_icons.scan"):
                for root, dirs, files in os.walk(ico_dir):
                    for file in files:
                        if file.lower().endswith('.ico'):
                            name = os.path.splitext(file)[0]
                            path = os.path.join(root, file)
                            ico_files.append((path, name))
        
            if not ico_files:
                self.hint_label.show()
                self.hint_label.setText("未找到 .ico 文件")
                return
        
            with perf_span("load_icons.sort"):
                self._icon_name_norm = {path: self._normalize_text(name) for path, name in ico_files}
                ico_files.sort(key=lambda x: self._icon_name_norm.get(x[0], self._normalize_text(x[1])))
                self.icon_data = ico_files
                self.hint_label.hide()
        
            parent_scroll = self.parent()
            if parent_scroll and hasattr(parent_scroll, 'viewport'):
                initial_width = parent_scroll.viewport().width()
                self._cols = self._calculate_cols(initial_width)
        
            with perf_span("load_icons.build_ui"):
                self._create_grid_layout()
    
    def _create_grid_layout(self, _skip_update_control=False):
        """创建图标网格布局，同时保存到缓存"""
        # 如果外部已经控制更新，跳过内部控制
        if not _skip_update_control:
            main_window = self.window()
            if main_window:
                main_window.setUpdatesEnabled(False)
        else:
            main_window = None
        
        try:
            # 1. 彻底清理当前布局（保留 hint_label 但移出显示）
            while self.main_layout.count():
                item = self.main_layout.takeAt(0)
                if item and item.widget() == self.hint_label:
                    self.hint_label.hide()
            
            # 2. 如果有现成的缓存且不在过滤模式，直接还原
            if self._cached_widgets and not self._is_filtering:
                for widget in self._cached_widgets:
                    self.main_layout.addWidget(widget)
                self.main_layout.addStretch()
                QTimer.singleShot(100, self._load_visible_icons)
                return
            
            # 3. 如果没有缓存，则根据 icon_data 创建新布局
            self.icon_items = []
            self.section_headers = {}
            
            if not self.icon_data:
                self.hint_label.show()
                self.main_layout.addWidget(self.hint_label)
                self.main_layout.addStretch()
                return
            
            self.hint_label.hide()
            grouped = defaultdict(list)
            for path, name in self.icon_data:
                letter = self._section_letter(name)
                grouped[letter].append((path, name))
            
            sorted_letters = sorted(grouped.keys(), key=lambda x: (x != '#', x))
            
            for letter in sorted_letters:
                items = grouped[letter]
                
                header = self._create_section_header(letter)
                self.main_layout.addWidget(header)
                self.section_headers[letter] = header
                self._cached_widgets.append(header)
                
                grid_widget = QWidget()
                grid_widget.setStyleSheet("background: transparent;")
                grid_layout = QGridLayout(grid_widget)
                grid_layout.setContentsMargins(0, 0, 0, 10)
                grid_layout.setSpacing(6)
                grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                
                for idx, (path, name) in enumerate(items):
                    row = idx // self._cols
                    col = idx % self._cols
                    
                    icon_item = IconItem(path, name, self._icon_size)
                    icon_item.double_clicked.connect(self.icon_double_clicked.emit)
                    icon_item.apply_requested.connect(self.icon_double_clicked.emit)  # 复用双击信号
                    icon_item.delete_requested.connect(self._on_delete_icon)
                    grid_layout.addWidget(icon_item, row, col)
                    self.icon_items.append(icon_item)
                
                # 设置列伸缩，确保列向左对齐，解决图标间隙过大问题
                grid_layout.setColumnStretch(self._cols, 1)
                self.main_layout.addWidget(grid_widget, 0, Qt.AlignmentFlag.AlignLeft)
                self._cached_widgets.append(grid_widget)
            
            self.main_layout.addStretch()
            QTimer.singleShot(100, self._load_visible_icons)
        finally:
            # 只有内部控制时才恢复更新
            if not _skip_update_control and main_window:
                main_window.setUpdatesEnabled(True)
    
    def _create_section_header(self, letter: str) -> QWidget:
        header = QFrame()
        header.setFixedHeight(32)
        header.setStyleSheet("""
            QFrame {
                background-color: #e8e8e8;
                border-radius: 4px;
            }
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 0, 12, 0)
        
        label = QLabel(f"  {letter}  ")
        label.setStyleSheet("""
            font-weight: bold;
            font-size: 14px;
            color: #333333;
            background: transparent;
            border: none;
        """)
        layout.addWidget(label)
        layout.addStretch()
        
        return header
    
    def clear_icons(self):
        """完全清除所有图标、标题和缓存控件"""
        # 1. 清空布局中的所有控件，并彻底删除它们
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            if item and item.widget():
                # 如果是提示标签，暂时不删除，只是移出布局
                if item.widget() == self.hint_label:
                    self.hint_label.hide()
                    continue
                item.widget().deleteLater()
        
        # 2. 清理缓存和数据列表
        for widget in self._cached_widgets:
            if widget != self.hint_label:
                widget.deleteLater()
        
        self.icon_items = []
        self.icon_data = []
        self.section_headers = {}
        self._cached_widgets = []
        self._is_filtering = False
        
        # 3. 重新添加提示标签到布局（它在初始化时就被创建了）
        self.main_layout.addWidget(self.hint_label)
        self.main_layout.addStretch()

    def _reset_view_keep_data(self):
        """清理布局和缓存控件，但保留 icon_data（用于删除后快速重建）"""
        while self.main_layout.count():
            item = self.main_layout.takeAt(0)
            if item and item.widget():
                if item.widget() == self.hint_label:
                    self.hint_label.hide()
                    continue
                item.widget().deleteLater()
        
        for widget in self._cached_widgets:
            if widget != self.hint_label:
                widget.deleteLater()
        
        self.icon_items = []
        self.section_headers = {}
        self._cached_widgets = []
        self._is_filtering = False
        
        self.main_layout.addWidget(self.hint_label)
        self.main_layout.addStretch()

    def _remove_icon_from_layout(self, layout, ico_path: str, *, relayout_threshold: int = 200) -> bool:
        if not layout:
            return False
        with perf_span("delete_icon.remove_from_layout.search"):
            target_widget = None
            for i in range(layout.count()):
                item = layout.itemAt(i)
                w = item.widget() if item else None
                if not w:
                    continue
                if isinstance(w, IconItem) and getattr(w, "icon_path", None) == ico_path:
                    target_widget = w
                    break
            if not target_widget:
                return False
        try:
            layout.removeWidget(target_widget)
        except Exception:
            pass
        try:
            target_widget.setParent(None)
        except Exception:
            pass
        try:
            target_widget.deleteLater()
        except Exception:
            pass
        try:
            self.icon_items.remove(target_widget)
        except Exception:
            pass

        icon_widgets = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            w = item.widget() if item else None
            if isinstance(w, IconItem):
                icon_widgets.append(w)

        if len(icon_widgets) <= relayout_threshold:
            with perf_span("delete_icon.remove_from_layout.relayout", count=len(icon_widgets)):
                for w in icon_widgets:
                    try:
                        layout.removeWidget(w)
                    except Exception:
                        pass
                for idx, w in enumerate(icon_widgets):
                    row = idx // self._cols
                    col = idx % self._cols
                    layout.addWidget(w, row, col)
                try:
                    layout.setColumnStretch(self._cols, 1)
                except Exception:
                    pass

        return True

    def _remove_icon_from_cached_widgets(self, ico_path: str) -> bool:
        removed = False
        for widget in list(self._cached_widgets):
            if not widget or isinstance(widget, QFrame):
                continue
            try:
                layout = widget.layout()
            except Exception:
                continue
            if self._remove_icon_from_layout(layout, ico_path):
                removed = True
        return removed
    
    def _on_delete_icon(self, ico_path: str, icon_name: str):
        """处理图标删除请求"""
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要永久删除自定义图标 '{icon_name}' 及其配置吗？\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            with perf_span("delete_icon.total", icon=icon_name):
                try:
                    # 记录当前的过滤模式
                    nav_bar = None
                    main_window = self.window()
                    if main_window and hasattr(main_window, 'nav_bar'):
                        nav_bar = main_window.nav_bar
                    
                    was_filtering_custom = nav_bar._custom_active if nav_bar else False
                    
                    # 1. 删除 .ico 文件
                    with perf_span("delete_icon.fs.remove_ico"):
                        if os.path.exists(ico_path):
                            os.remove(ico_path)
                    
                    # 2. 删除对应的 .json 缓存文件
                    base_path = get_app_root_dir()
                    cache_dir = os.path.join(base_path, ".cache", "Save")
                    json_path = os.path.join(cache_dir, f"{icon_name}.json")
                    
                    with perf_span("delete_icon.fs.remove_json"):
                        if os.path.exists(json_path):
                            os.remove(json_path)
                    
                    with perf_span("delete_icon.cache.evict"):
                        IcoParser.evict(ico_path)
                    
                    # 4. 更新内存中的数据列表（避免全量磁盘扫描）
                    with perf_span("delete_icon.update_data"):
                        old_len = len(self.icon_data)
                        self.icon_data = [(p, n) for p, n in self.icon_data if p != ico_path]
                        self._icon_name_norm.pop(ico_path, None)
                        _append_perf_event({"name": "delete_icon.data_len", "before": old_len, "after": len(self.icon_data)})
                    
                    removed_visible = False
                    removed_cached = False
                    used_fallback_rebuild = False

                    with perf_span("delete_icon.update_ui"):
                        with perf_span("delete_icon.update_ui.remove_visible"):
                            try:
                                for item in list(self.icon_items):
                                    if getattr(item, "icon_path", None) == ico_path:
                                        parent = item.parentWidget()
                                        layout = parent.layout() if parent else None
                                        removed_visible = self._remove_icon_from_layout(layout, ico_path)
                                        break
                            except Exception:
                                removed_visible = False

                        with perf_span("delete_icon.update_ui.remove_cached"):
                            removed_cached = self._remove_icon_from_cached_widgets(ico_path)
                        _append_perf_event({"name": "delete_icon.removed", "visible": removed_visible, "cached": removed_cached})

                        if not removed_visible and not removed_cached:
                            used_fallback_rebuild = True
                            self._reset_view_keep_data()
                            if not self.icon_data:
                                self.hint_label.show()
                                self.hint_label.setText("未找到 .ico 文件")
                            else:
                                self.hint_label.hide()
                                self._create_grid_layout()
                    
                    if was_filtering_custom and used_fallback_rebuild:
                        self.filter_custom_icons()
                    
                    if main_window and hasattr(main_window, 'statusBar'):
                        main_window.statusBar().showMessage(f"已删除图标: {icon_name}", 3000)
                
                except Exception as e:
                    QMessageBox.warning(self, "删除失败", f"无法删除图标：{str(e)}")

    def _load_visible_icons(self):
        for item in self.icon_items:
            if item.isVisible():
                item.load_icon()
    
    def _calculate_cols(self, available_width: int) -> int:
        """根据可用宽度计算列数"""
        if available_width <= 0:
            return 6
        # 计算列数，每列宽度 = 图标项宽度 + 间距
        cols = max(1, available_width // (self._icon_item_width + 6))
        return cols
    
    def relayout_for_width(self, new_width: int):
        """根据新宽度重新布局图标"""
        if not self.icon_data:
            return
        
        new_cols = self._calculate_cols(new_width)
        if new_cols != self._cols:
            self._cols = new_cols
            self._rebuild_grid_layout()
    
    def _rebuild_grid_layout(self):
        """重建网格布局（仅调整列数，不重新加载图标数据）"""
        if not self.icon_data or self._is_filtering:
            return
        
        main_window = self.window()
        if main_window:
            main_window.setUpdatesEnabled(False)
        
        try:
            # 记录每个 letter 对应的 header 在布局中的位置
            letter_layout_info = []  # [(letter, header_idx), ...]
            
            # 先清空布局中的所有项（但不删除 header）
            while self.main_layout.count():
                item = self.main_layout.takeAt(0)
                if item and item.widget():
                    widget = item.widget()
                    # header 保留引用但不加入布局，稍后重建
                    if isinstance(widget, QFrame) and widget in self.section_headers.values():
                        pass  # header 不删除，只移出布局
                    else:
                        widget.deleteLater()
            
            # 删除旧的 grid_widget
            for widget in self._cached_widgets:
                if not isinstance(widget, QFrame):  # 不是 header
                    widget.deleteLater()
            
            self._cached_widgets = []
            self.icon_items = []
            
            # 重新分组创建 grid
            grouped = defaultdict(list)
            for path, name in self.icon_data:
                letter = self._section_letter(name)
                grouped[letter].append((path, name))
            
            sorted_letters = sorted(grouped.keys(), key=lambda x: (x != '#', x))
            
            for letter in sorted_letters:
                items = grouped[letter]
                
                # 添加 header
                header = self.section_headers.get(letter)
                if header:
                    self.main_layout.addWidget(header)
                    self._cached_widgets.append(header)
                
                # 创建 grid_widget
                grid_widget = QWidget()
                grid_widget.setStyleSheet("background: transparent;")
                grid_layout = QGridLayout(grid_widget)
                grid_layout.setContentsMargins(0, 0, 0, 10)
                grid_layout.setSpacing(6)
                grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                
                for idx, (path, name) in enumerate(items):
                    row = idx // self._cols
                    col = idx % self._cols
                    
                    icon_item = IconItem(path, name, self._icon_size)
                    icon_item.double_clicked.connect(self.icon_double_clicked.emit)
                    icon_item.apply_requested.connect(self.icon_double_clicked.emit)  # 复用双击信号
                    icon_item.delete_requested.connect(self._on_delete_icon)
                    grid_layout.addWidget(icon_item, row, col)
                    self.icon_items.append(icon_item)
                
                # 设置列伸缩，确保搜索结果向左对齐
                grid_layout.setColumnStretch(self._cols, 1)
                self.main_layout.addWidget(grid_widget, 0, Qt.AlignmentFlag.AlignLeft)
                self._cached_widgets.append(grid_widget)
            
            self.main_layout.addStretch()
            QTimer.singleShot(100, self._load_visible_icons)
        finally:
            if main_window:
                main_window.setUpdatesEnabled(True)
    
    def filter_custom_icons(self):
        """只显示 CustomIco 目录下的图标"""
        # 获取顶层窗口来禁用更新
        main_window = self.window()
        if main_window:
            main_window.setUpdatesEnabled(False)
        
        try:
            self._is_filtering = True
            
            # 隐藏所有缓存的控件
            for widget in self._cached_widgets:
                widget.hide()
            
            # 清空当前布局，并删除上一次搜索/过滤创建的临时控件
            while self.main_layout.count():
                item = self.main_layout.takeAt(0)
                if item and item.widget():
                    widget = item.widget()
                    if widget not in self._cached_widgets:
                        widget.deleteLater()
            
            # 过滤 CustomIco 目录下的图标，并按名称排序
            filtered_data = []
            for path, name in self.icon_data:
                if "CustomIco" in path:
                    filtered_data.append((path, name))
            
            filtered_data.sort(key=lambda x: self._icon_name_norm.get(x[0], self._normalize_text(x[1])))
            
            self.icon_items = []
            self.section_headers = {}
            
            if not filtered_data:
                self.hint_label = QLabel("未找到自定义图标")
                self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.hint_label.setStyleSheet("color: #666666; font-size: 16px; padding: 40px;")
                self.main_layout.addWidget(self.hint_label)
                self.main_layout.addStretch()
                return
            
            # 按首字母分组显示
            grouped = defaultdict(list)
            for path, name in filtered_data:
                letter = self._section_letter(name)
                grouped[letter].append((path, name))
            
            sorted_letters = sorted(grouped.keys(), key=lambda x: (x != '#', x))
            
            for letter in sorted_letters:
                items = grouped[letter]
                header = self._create_section_header(letter)
                self.main_layout.addWidget(header)
                self.section_headers[letter] = header
                
                grid_widget = QWidget()
                grid_widget.setStyleSheet("background: transparent;")
                grid_layout = QGridLayout(grid_widget)
                grid_layout.setContentsMargins(0, 0, 0, 10)
                grid_layout.setSpacing(6)
                grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                
                for i, (path, name) in enumerate(items):
                    row = i // self._cols
                    col = i % self._cols
                    icon_item = IconItem(path, name, self._icon_size)
                    icon_item.double_clicked.connect(self.icon_double_clicked.emit)
                    icon_item.apply_requested.connect(self.icon_double_clicked.emit)  # 复用双击信号
                    icon_item.delete_requested.connect(self._on_delete_icon)
                    grid_layout.addWidget(icon_item, row, col)
                    self.icon_items.append(icon_item)
                
                # 设置一个很大的列伸缩，把前面的列挤到左边，解决空隙问题
                grid_layout.setColumnStretch(self._cols, 1)
                self.main_layout.addWidget(grid_widget, 0, Qt.AlignmentFlag.AlignLeft)
            
            self.main_layout.addStretch()
            QTimer.singleShot(100, self._load_visible_icons)
            
        finally:
            if main_window:
                main_window.setUpdatesEnabled(True)

    def scroll_to_section(self, letter: str):
        if letter in self.section_headers:
            header = self.section_headers[letter]
            return header.geometry().top()
        return 0
    
    def filter_icons(self, keyword: str):
        keyword_norm = self._normalize_text(keyword)
        
        main_window = self.window()
        if main_window:
            main_window.setUpdatesEnabled(False)
        
        with perf_span("filter_icons.total", keyword_len=len(keyword_norm), total=len(self.icon_data)):
            try:
                if not keyword_norm:
                    with perf_span("filter_icons.clear_restore"):
                        self._is_filtering = False
                        
                        while self.main_layout.count():
                            item = self.main_layout.takeAt(0)
                            if item and item.widget():
                                widget = item.widget()
                                if widget not in self._cached_widgets:
                                    widget.deleteLater()
                        
                        if self._cached_widgets:
                            for widget in self._cached_widgets:
                                widget.show()
                                self.main_layout.addWidget(widget)
                            
                            self.section_headers = {}
                            self.icon_items = []
                            for widget in self._cached_widgets:
                                if isinstance(widget, QFrame):
                                    label = widget.findChild(QLabel)
                                    if label:
                                        letter = label.text().strip()
                                        self.section_headers[letter] = widget
                                else:
                                    layout = widget.layout()
                                    if layout:
                                        for i in range(layout.count()):
                                            item = layout.itemAt(i)
                                            if item and item.widget() and isinstance(item.widget(), IconItem):
                                                self.icon_items.append(item.widget())
                            
                            self.main_layout.addStretch()
                            QTimer.singleShot(100, self._load_visible_icons)
                    return
                
                self._is_filtering = True
                
                for widget in self._cached_widgets:
                    widget.hide()
                
                while self.main_layout.count():
                    item = self.main_layout.takeAt(0)
                    if item and item.widget():
                        widget = item.widget()
                        if widget not in self._cached_widgets:
                            widget.deleteLater()
                
                with perf_span("filter_icons.match", keyword_len=len(keyword_norm), total=len(self.icon_data)):
                    filtered_data = [
                        (path, name)
                        for path, name in self.icon_data
                        if keyword_norm in self._icon_name_norm.get(path, self._normalize_text(name))
                    ]
                
                self.icon_items = []
                self.section_headers = {}
                
                if not filtered_data:
                    self.hint_label = QLabel("未找到匹配的图标")
                    self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.hint_label.setStyleSheet("color: #666666; font-size: 16px; padding: 40px;")
                    self.main_layout.addWidget(self.hint_label)
                    self.main_layout.addStretch()
                    return
                
                grouped = defaultdict(list)
                for path, name in filtered_data:
                    letter = self._section_letter(name)
                    grouped[letter].append((path, name))
                
                sorted_letters = sorted(grouped.keys(), key=lambda x: (x != '#', x))
                
                for letter in sorted_letters:
                    items = grouped[letter]
                    
                    header = self._create_section_header(letter)
                    self.main_layout.addWidget(header)
                    self.section_headers[letter] = header
                    
                    grid_widget = QWidget()
                    grid_widget.setStyleSheet("background: transparent;")
                    grid_layout = QGridLayout(grid_widget)
                    grid_layout.setContentsMargins(0, 0, 0, 10)
                    grid_layout.setSpacing(6)
                    grid_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                    
                    for idx, (path, name) in enumerate(items):
                        row = idx // self._cols
                        col = idx % self._cols
                        
                        icon_item = IconItem(path, name, self._icon_size)
                        icon_item.double_clicked.connect(self.icon_double_clicked.emit)
                        icon_item.apply_requested.connect(self.icon_double_clicked.emit)
                        icon_item.delete_requested.connect(self._on_delete_icon)
                        grid_layout.addWidget(icon_item, row, col)
                        self.icon_items.append(icon_item)
                    
                    grid_layout.setColumnStretch(self._cols, 1)
                    self.main_layout.addWidget(grid_widget, 0, Qt.AlignmentFlag.AlignLeft)
                
                self.main_layout.addStretch()
                QTimer.singleShot(100, self._load_visible_icons)
            finally:
                if main_window:
                    main_window.setUpdatesEnabled(True)


# ==================== 图标滚动区域 ====================
class IconScrollArea(QScrollArea):
    """图标滚动区域"""
    
    # 滚动时通知当前可见的首字母分区
    section_changed = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #ffffff;
            }
            QScrollBar:vertical {
                width: 12px;
                background-color: #f5f5f5;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #c0c0c0;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #9e9e9e;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)
        
        self.icon_content = IconGridContent()
        self.setWidget(self.icon_content)
        
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        
        # resize 防抖定时器（延迟 100ms 避免频繁重建）
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._on_resize_timeout)
        self._last_width = 0
        self._resize_delay = 100  # 防抖延迟时间（毫秒）
    
    def resizeEvent(self, event):
        """窗口大小变化时通知内容区域重新布局"""
        super().resizeEvent(event)
        self._resize_timer.start(self._resize_delay)
    
    def _on_resize_timeout(self):
        """resize 防抖结束后重新布局"""
        new_width = self.viewport().width()
        if abs(new_width - self._last_width) >= 50:
            self._last_width = new_width
            self.icon_content.relayout_for_width(new_width)
    
    def _on_scroll_changed(self, value):
        self.icon_content._load_visible_icons()
        # 检测当前可见的首字母分区
        current_letter = self._get_visible_section()
        if current_letter:
            self.section_changed.emit(current_letter)
    
    def _get_visible_section(self) -> Optional[str]:
        """获取当前视口顶部最接近的首字母分区"""
        if not self.icon_content.section_headers:
            return None
        
        viewport_top = self.verticalScrollBar().value()
        
        # 收集所有分区头部的位置
        all_sections = []
        for letter, header in self.icon_content.section_headers.items():
            if header.isVisible():
                # 获取 header 在内容区域中的绝对位置
                header_pos = header.mapTo(self.icon_content, header.rect().topLeft())
                header_top = header_pos.y()
                all_sections.append((header_top, letter))
        
        if not all_sections:
            return None
        
        # 按位置排序
        all_sections.sort(key=lambda x: x[0])
        
        # 找到视口顶部所在的分区：最后一个位置 <= viewport_top 的分区
        current_letter = all_sections[0][1]  # 默认第一个
        for pos, letter in all_sections:
            if pos <= viewport_top + 20:  # 允许一点容差
                current_letter = letter
            else:
                break  # 已经超过了视口顶部，停止
        
        return current_letter
    
    def scroll_to_section(self, letter: str):
        pos = self.icon_content.scroll_to_section(letter)
        if pos > 0:
            self.verticalScrollBar().setValue(pos - 10)


# ==================== 图标应用器 ====================
class IconApplicator:
    """图标应用器"""
    
    @staticmethod
    def apply_icon(folder_path: str, icon_path: str) -> Tuple[bool, str]:
        try:
            if not os.path.exists(folder_path):
                return False, "文件夹不存在"
            
            if not os.path.exists(icon_path):
                return False, "图标文件不存在"
            
            icon_abs_path = os.path.abspath(icon_path)
            desktop_ini_path = os.path.join(folder_path, 'desktop.ini')
            
            # 如果已存在 desktop.ini，先清除旧的图标设置
            if os.path.exists(desktop_ini_path):
                # 移除文件属性，以便修改
                try:
                    subprocess.run(f'attrib -r "{folder_path}"', shell=True, check=False, timeout=5)
                    subprocess.run(f'attrib -h -s -r "{desktop_ini_path}"', shell=True, check=False, timeout=5)
                except Exception as e:
                    print(f"清除属性失败（可忽略）: {e}")
            
            ini_content = f"""[.ShellClassInfo]
IconResource={icon_abs_path},0
[ViewState]
Mode=
Vid=
FolderType=Pictures
Logo={icon_abs_path}
"""
            
            # 方法1：直接尝试写入
            try:
                with open(desktop_ini_path, 'w', encoding='utf-8') as f:
                    f.write(ini_content)
            except PermissionError:
                # 方法2：使用管理员权限的 PowerShell 写入
                ps_script = f'''
$file = "{desktop_ini_path}"
$content = @"
[.ShellClassInfo]
IconResource={icon_abs_path},0
[ViewState]
Mode=
Vid=
FolderType=Pictures
Logo={icon_abs_path}
"@
Set-Content -Path $file -Value $content -Encoding UTF8
'''
                try:
                    result = subprocess.run(
                        ['powershell', '-Command', ps_script],
                        capture_output=True,
                        text=True,
                        shell=True,
                        timeout=10
                    )
                    
                    if result.returncode != 0 and not os.path.exists(desktop_ini_path):
                        return False, f"无法写入 desktop.ini\n\n该文件夹可能是系统保护目录：\n{folder_path}\n\n解决方案：\n1. 选择普通文件夹（如桌面、D盘非Program Files目录）\n2. 或将软件安装到非系统保护目录后再修改图标"
                except subprocess.TimeoutExpired:
                    return False, "PowerShell 执行超时，请重试"
                except Exception as e:
                    return False, f"写入失败：{str(e)}"
            
            # 设置文件属性
            try:
                subprocess.run(f'attrib +h +s "{desktop_ini_path}"', shell=True, check=False, timeout=5)
                subprocess.run(f'attrib +r "{folder_path}"', shell=True, check=False, timeout=5)
            except Exception as e:
                print(f"设置属性失败（可忽略）: {e}")
            
            # 强制刷新文件夹图标缓存
            try:
                IconApplicator._refresh_folder_icon(folder_path)
            except Exception as e:
                print(f"刷新图标缓存失败（可忽略）: {e}")
            
            return True, "图标应用成功！\n\n文件夹图标已更新，请查看效果。\n如果图标未变化，请尝试刷新文件夹或重启资源管理器。"
            
        except PermissionError as e:
            return False, f"权限不足\n\n错误详情: {str(e)}\n\n请以管理员身份运行程序"
        except Exception as e:
            print(f"apply_icon 异常: {e}")
            return False, f"应用失败：{str(e)}"
    
    @staticmethod
    def restore_icon(folder_path: str) -> Tuple[bool, str]:
        """恢复文件夹为默认图标"""
        try:
            if not os.path.exists(folder_path):
                return False, "文件夹不存在"
            
            desktop_ini_path = os.path.join(folder_path, 'desktop.ini')
            
            if not os.path.exists(desktop_ini_path):
                return False, "该文件夹未设置自定义图标"
            
            # 移除文件夹和文件的只读、隐藏、系统属性
            try:
                subprocess.run(f'attrib -r "{folder_path}"', shell=True, check=False, timeout=5)
                subprocess.run(f'attrib -h -s -r "{desktop_ini_path}"', shell=True, check=False, timeout=5)
            except Exception as e:
                print(f"清除属性失败（可忽略）: {e}")
            
            # 删除 desktop.ini 文件
            try:
                os.remove(desktop_ini_path)
            except PermissionError:
                # 如果直接删除失败，尝试用 PowerShell 删除
                ps_script = f'Remove-Item -Path "{desktop_ini_path}" -Force'
                try:
                    result = subprocess.run(
                        ['powershell', '-Command', ps_script],
                        capture_output=True,
                        text=True,
                        shell=True,
                        timeout=10
                    )
                    if result.returncode != 0 and os.path.exists(desktop_ini_path):
                        return False, "删除 desktop.ini 失败，请以管理员身份运行程序"
                except subprocess.TimeoutExpired:
                    return False, "PowerShell 执行超时，请重试"
                except Exception as e:
                    return False, f"删除失败：{str(e)}"
            
            # 刷新图标缓存
            try:
                IconApplicator._refresh_folder_icon(folder_path)
            except Exception as e:
                print(f"刷新图标缓存失败（可忽略）: {e}")
            
            return True, "图标已恢复为默认样式！\n\n请刷新文件夹查看效果。"
            
        except PermissionError as e:
            return False, f"权限不足\n\n错误详情: {str(e)}\n\n请以管理员身份运行程序"
        except Exception as e:
            print(f"restore_icon 异常: {e}")
            return False, f"恢复失败：{str(e)}"
    
    @staticmethod
    def _refresh_folder_icon(folder_path: str):
        """强制刷新文件夹图标"""
        try:
            # 方法1：修改文件夹的修改时间，触发 Windows 重新读取
            try:
                os.utime(folder_path, None)
            except Exception as e:
                print(f"修改时间失败（可忽略）: {e}")
            
            # 方法2：通过 IE4UINIT.exe 刷新图标缓存
            try:
                subprocess.run('ie4uinit.exe -show', shell=True, check=False, timeout=5)
            except Exception as e:
                print(f"ie4uinit 执行失败（可忽略）: {e}")
            
            # 方法3：通知系统文件夹发生变化
            try:
                if sys.platform == 'win32':
                    ctypes.windll.shell32.SHChangeNotify(
                        0x08000000,  # SHCNE_ASSOCCHANGED
                        0x00001000,  # SHCNF_FLUSH
                        None,
                        None
                    )
            except Exception as e:
                print(f"SHChangeNotify 调用失败（可忽略）: {e}")
        except Exception as e:
            print(f"刷新图标缓存失败: {e}")


# ==================== 主窗口 ====================
class FolderIconChanger(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        
        self.cache = FolderCache()
        self.current_folder_path: Optional[str] = None
        
        self.init_ui()
        # 延迟加载数据，避开初始化期间的各种事件冲突
        QTimer.singleShot(200, self.load_initial_data)
    
    def init_ui(self):
        self.setWindowTitle("Folder Icon Changer")
        # 默认窗口大小 921×714
        self.setMinimumSize(921, 714)
        self.resize(921, 714)
        
        # 全局样式 - 所有文字黑色
        self.setStyleSheet("""
            QMainWindow {
                background: #fafafa;
            }
            QWidget {
                color: #333333;
            }
            QLineEdit {
                padding: 8px 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: #fff;
                font-size: 13px;
                color: #333333;
            }
            QLineEdit:focus {
                border-color: #2196f3;
            }
            QLabel {
                color: #333333;
            }
        """)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self._create_content_area(main_layout)
        
        # 状态栏显示管理员状态
        admin_status = " [管理员模式]" if is_admin() else " [普通模式 - 部分功能可能受限]"
        self.statusBar().showMessage(f"就绪{admin_status}")
    
    def _create_content_area(self, parent_layout):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)
        
        # 右侧区域：搜索框+图标列表+字母导航
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        
        # 搜索框区域
        search_container = QWidget()
        search_container.setFixedHeight(50)
        search_container.setStyleSheet("""
            background: #fff;
            border-bottom: 1px solid #e0e0e0;
        """)
        
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(12, 8, 12, 8)
        search_layout.setSpacing(8)

        self.download_pack_btn = QPushButton()
        self.download_pack_btn.setFixedSize(32, 32)
        self.download_pack_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.download_pack_btn.setToolTip("打开图标包下载器")
        self.download_pack_btn.setStyleSheet("""
            QPushButton {
                background: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 16px;
            }
            QPushButton:hover {
                background: #e3f2fd;
                border-color: #2196f3;
            }
            QPushButton:pressed {
                background: #bbdefb;
            }
        """)
        self.download_pack_btn.setIcon(self._create_download_icon())
        self.download_pack_btn.setIconSize(QSize(16, 16))
        self.download_pack_btn.clicked.connect(self.open_icon_downloader_ui)
        search_layout.addWidget(self.download_pack_btn)
        
        # 搜索框容器 - 整体胶囊形
        search_box_container = QWidget()
        search_box_container.setFixedHeight(32)
        search_box_container.setStyleSheet("""
            QWidget {
                background: #f5f5f5;
                border-radius: 16px;
            }
        """)
        search_box_layout = QHBoxLayout(search_box_container)
        search_box_layout.setContentsMargins(0, 0, 0, 0)
        search_box_layout.setSpacing(0)
        
        # 搜索输入框
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索图标...")
        self.search_input.setFixedHeight(32)
        self.search_input.returnPressed.connect(self._on_search_btn_clicked)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        self.search_input.setStyleSheet("""
            QLineEdit {
                padding: 0 0 0 16px;
                border: none;
                border-top-left-radius: 16px;
                border-bottom-left-radius: 16px;
                background: transparent;
                font-size: 12px;
            }
        """)
        
        # 防抖定时器：用户停止输入1秒后自动搜索
        self._search_debounce_timer = QTimer(self)
        self._search_debounce_timer.setSingleShot(True)
        self._search_debounce_timer.timeout.connect(self._on_debounce_search)
        search_box_layout.addWidget(self.search_input, 1)
        
        # 清空按钮
        self.clear_btn = QPushButton("×")
        self.clear_btn.setFixedSize(28, 32)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.clicked.connect(self._on_clear_search)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #999999;
                border: none;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #666666;
            }
        """)
        search_box_layout.addWidget(self.clear_btn)
        
        # 搜索按钮 - 与输入框合为一体
        self.search_btn = QPushButton("🔍 搜索")
        self.search_btn.setFixedSize(72, 32)
        self.search_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_btn.clicked.connect(self._on_search_btn_clicked)
        self.search_btn.setStyleSheet("""
            QPushButton {
                background: #2196f3;
                color: white;
                border: none;
                border-top-right-radius: 16px;
                border-bottom-right-radius: 16px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #1976d2;
            }
            QPushButton:pressed {
                background: #1565c0;
            }
        """)
        search_box_layout.addWidget(self.search_btn)
        
        search_layout.addWidget(search_box_container, 1)
        
        # 制作图标按钮 - 独立按钮，与搜索框样式一致
        self.create_icon_btn = QPushButton("🎨 制作图标")
        self.create_icon_btn.setFixedHeight(32)
        self.create_icon_btn.setFixedWidth(100)
        self.create_icon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_icon_btn.clicked.connect(self._on_create_icon_clicked)
        self.create_icon_btn.setStyleSheet("""
            QPushButton {
                background: #4caf50;
                color: white;
                border: none;
                border-radius: 16px;
                font-size: 12px;
                font-weight: bold;
                margin-left: 8px;
            }
            QPushButton:hover {
                background: #43a047;
            }
            QPushButton:pressed {
                background: #388e3c;
            }
        """)
        search_layout.addWidget(self.create_icon_btn)
        
        right_layout.addWidget(search_container)
        
        # 图标滚动区域
        self.scroll_area = IconScrollArea()
        self.icon_content = self.scroll_area.icon_content
        self.icon_content.icon_double_clicked.connect(self._on_icon_double_clicked)
        # 移除 refresh_requested 连接，因为逻辑已移至 IconGridContent 内部
        right_layout.addWidget(self.scroll_area, 1)
        
        splitter.addWidget(right_panel)
        
        self.nav_bar = AlphaNavigationBar()
        self.nav_bar.letter_clicked.connect(self._on_letter_clicked)
        # 滚动时联动更新导航按钮高亮（排除自定义图标模式）
        self.scroll_area.section_changed.connect(self._on_scroll_section_changed)
        splitter.addWidget(self.nav_bar)
        
        splitter.setSizes([300, 600, 50])
        
        parent_layout.addWidget(splitter)
    
    def _create_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(300)
        panel.setStyleSheet("background: #fafafa;")
        
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 选择文件夹按钮 - 低饱和度绿色 + emoji
        btn_select = QPushButton("📁 选择文件夹")
        btn_select.setObjectName("btnSelectFolder")
        btn_select.setStyleSheet("""
            QPushButton {
                padding: 10px 16px;
                background: #81c784;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #66bb6a;
            }
        """)
        btn_select.clicked.connect(self._select_root_folder)
        layout.addWidget(btn_select)
        
        self.folder_tree = LazyFolderTreeWidget()
        self.folder_tree.apply_icon_requested.connect(self._on_context_apply_icon)
        self.folder_tree.restore_icon_requested.connect(self._on_context_restore_icon)
        layout.addWidget(self.folder_tree)
        
        # 底部按钮区域 - 与右侧字母按钮样式一致
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(6)
        
        # 按钮样式 - 圆角矩形，左右边距增加6px
        button_style = """
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #d0d0d0;
                border-radius: 5px;
                font-family: 'Arial', 'Microsoft YaHei', sans-serif;
                font-size: 11px;
                font-weight: bold;
                color: #333333;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: #e3f2fd;
                border-color: #2196f3;
                color: #1976d2;
            }
            QPushButton:pressed {
                background-color: #bbdefb;
            }
        """
        
        # 刷新按钮
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setMinimumHeight(30)
        btn_refresh.setStyleSheet(button_style)
        btn_refresh.setToolTip("刷新文件夹列表")
        btn_refresh.clicked.connect(self._refresh_folder_tree)
        btn_layout.addWidget(btn_refresh, 1)
        
        # 应用到子文件夹开关按钮
        self.btn_apply_subfolders = QPushButton("📁 应用到子文件夹")
        self.btn_apply_subfolders.setMinimumHeight(30)
        self.btn_apply_subfolders.setCheckable(True)
        self.btn_apply_subfolders.setStyleSheet(button_style)
        self.btn_apply_subfolders.setToolTip("勾选后，双击图标将应用到所有子文件夹")
        self.btn_apply_subfolders.clicked.connect(self._on_apply_subfolders_toggled)
        btn_layout.addWidget(self.btn_apply_subfolders, 1)
        
        layout.addLayout(btn_layout)
        
        # 自动匹配按钮 - 与选择文件夹按钮长度一致，颜色与搜索按钮一致
        self.btn_auto_match = QPushButton("🎯 自动匹配")
        self.btn_auto_match.setFixedHeight(36)
        self.btn_auto_match.setStyleSheet("""
            QPushButton {
                padding: 10px 16px;
                background: #2196f3;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #1976d2;
            }
            QPushButton:pressed {
                background: #1565c0;
            }
        """)
        self.btn_auto_match.setToolTip("自动匹配文件夹名称相关的图标")
        self.btn_auto_match.clicked.connect(self._on_auto_match_clicked)
        layout.addWidget(self.btn_auto_match)
        
        return panel
    
    def load_initial_data(self):
        # 加载图标
        ico_dir = get_ico_directory()
        if os.path.exists(ico_dir):
            self.icon_content.load_icons(ico_dir)
            admin_status = " [管理员模式]" if is_admin() else " [普通模式]"
            self.statusBar().showMessage(f"已加载 {len(self.icon_content.icon_data)} 个图标{admin_status}")
            # 默认点亮符号按钮
            self.nav_bar.set_current_letter("#")
        else:
            expected_path = get_resource_path('ico')
            self.statusBar().showMessage(f"未找到 ico 文件夹: {expected_path}")
        
        # 自动加载上次打开的文件夹
        last_folder = self.cache.get_last_folder()
        if last_folder:
            self.current_folder_path = last_folder
            self.folder_tree.load_root_folder(last_folder)
            self.statusBar().showMessage(f"已加载: {last_folder}")
        
        # 延迟打印初始调试信息，等窗口完全显示
        QTimer.singleShot(100, self._print_debug_info)
    
    def resizeEvent(self, event):
        """窗口大小变化时更新调试信息"""
        super().resizeEvent(event)
        self._print_debug_info()
    
    def changeEvent(self, event):
        """处理窗口状态变化事件"""
        if event.type() == event.Type.ActivationChange:
            if self.isActiveWindow():
                # 当窗口重新获得焦点时，自动刷新数据
                self._auto_refresh_data()
        super().changeEvent(event)

    def _auto_refresh_data(self):
        """静默自动刷新数据"""
        # 1. 清除图标解析器缓存，确保能读取到刚保存的新图标
        IcoParser.clear_cache()
        
        # 2. 刷新右侧图标网格
        ico_dir = get_ico_directory()
        if os.path.exists(ico_dir):
            # 记录当前状态，避免刷新时重置视图
            was_filtering_custom = self.nav_bar._custom_active
            
            # 只有在没有输入搜索词的情况下才静默重载图标
            if not self.search_input.text().strip():
                self.icon_content.load_icons(ico_dir)
                if was_filtering_custom:
                    self.icon_content.filter_custom_icons()
        
        # 3. 刷新左侧文件夹树的图标
        if self.current_folder_path:
            # 遍历树，更新所有可见项的图标
            self.folder_tree.refresh_all_icons()

    def _print_debug_info(self):
        """打印调试信息到控制台"""
        window_width = self.width()
        window_height = self.height()
        left_panel_width = self.folder_tree.width() if hasattr(self, 'folder_tree') else 0
        
        print(f"窗口大小: {window_width} × {window_height} | 左侧栏宽度: {left_panel_width}")
    
    def _select_root_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            self.current_folder_path = folder
            self.folder_tree.load_root_folder(folder)
            self.cache.add_recent_folder(folder)  # 记录到历史
            self.statusBar().showMessage(f"已加载: {folder}")
    
    def _refresh_folder_tree(self):
        if self.current_folder_path:
            self.folder_tree.load_root_folder(self.current_folder_path)
            self.statusBar().showMessage("已刷新")
    
    def _on_search_text_changed(self, text: str):
        """搜索框文本变化时，启动防抖定时器"""
        # 重置定时器，等待用户停止输入
        self._search_debounce_timer.start(500)  # 0.5秒后触发

    def _create_download_icon(self) -> QIcon:
        svg = """
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24">
  <path fill="#2196f3" d="M5 20h14v-2H5v2zm7-18c-.55 0-1 .45-1 1v9.59l-3.3-3.3a1 1 0 0 0-1.4 1.42l5.0 5.0c.39.39 1.02.39 1.41 0l5.0-5.0a1 1 0 1 0-1.41-1.42L13 12.59V3c0-.55-.45-1-1-1z"/>
</svg>
"""
        renderer = QSvgRenderer(bytearray(svg, "utf-8"))
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def open_icon_downloader_ui(self):
        proc = open_icon_downloader_ui(self, test_mode=False)
        if proc:
            # 启动一个定时器，每隔 5 秒刷新一次图标列表
            self._downloader_timer = QTimer(self)
            self._downloader_timer.setInterval(5000)  # 5秒
            
            def check_and_refresh():
                # 检查进程是否仍在运行
                if proc.poll() is not None:
                    # 进程已退出，停止定时器并进行最后一次刷新
                    self._downloader_timer.stop()
                    self._downloader_timer = None
                    self._auto_refresh_data()
                else:
                    # 进程仍在运行，定期刷新
                    self._auto_refresh_data()
                    
            self._downloader_timer.timeout.connect(check_and_refresh)
            self._downloader_timer.start()
    
    def _on_create_icon_clicked(self):
        """点击“制作图标”按钮：打开 icon_creator.py"""
        # 获取当前选中的文件夹路径
        selected_path = ""
        selected_items = self.folder_tree.selectedItems()
        if selected_items:
            selected_path = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        
        base_path = get_app_dir()
        creator_script = os.path.join(base_path, "icon_creator.py")
        creator_exe = os.path.join(base_path, "icon_creator.exe")
        
        # 启动进程
        try:
            if getattr(sys, 'frozen', False):
                if os.path.exists(creator_exe):
                    cmd = [creator_exe]
                else:
                    cmd = [sys.executable, "--run-creator"]
            else:
                cmd = [sys.executable, creator_script]

            if selected_path:
                clean_path = os.path.abspath(os.path.normpath(selected_path))
                cmd.append(clean_path)

            subprocess.Popen(cmd, cwd=base_path)
            self.statusBar().showMessage(f"正在启动图标制作器... {f'已传递路径: {os.path.basename(selected_path)}' if selected_path else ''}")
        except Exception as e:
            QMessageBox.warning(self, "启动失败", f"无法启动图标制作器：{str(e)}")

    def _on_debounce_search(self):
        """防抖定时器触发：执行搜索"""
        text = self.search_input.text()
        self.icon_content.filter_icons(text)
        if text:
            self.nav_bar.set_current_letter("")  # 搜索时清除字母高亮
    
    def _on_search_btn_clicked(self):
        """搜索按钮点击事件：立即搜索"""
        # 停止防抖定时器，避免重复搜索
        self._search_debounce_timer.stop()
        text = self.search_input.text()
        self.icon_content.filter_icons(text)
        if text:
            self.nav_bar.set_current_letter("")  # 搜索时清除字母高亮
    
    def _on_clear_search(self):
        """清空搜索框并清除过滤"""
        # 停止防抖定时器
        self._search_debounce_timer.stop()
        self.search_input.clear()
        self.icon_content.filter_icons("")
        self.nav_bar.set_custom_active(False)  # 清除搜索同时也清除自定义过滤状态
    
    def _on_scroll_section_changed(self, letter: str):
        """滚轮滚动导致的分区切换事件"""
        self.nav_bar.set_current_letter(letter)

    def _on_letter_clicked(self, letter: str):
        if letter == "✏":
            # 如果当前已经是自定义模式，则关闭它（切换回全部图标）
            if self.nav_bar._custom_active:
                self.icon_content.filter_icons("")
                self.nav_bar.set_custom_active(False)
            else:
                self.search_input.clear()  # 切换到自定义图标模式时清空搜索框
                self.icon_content.filter_custom_icons()
                self.nav_bar.set_custom_active(True)
        else:
            # 点击字母分区，直接跳转，不取消自定义过滤模式
            self.scroll_area.scroll_to_section(letter)
            self.nav_bar.set_current_letter(letter)
    
    def _apply_icon_to_single_folder(self, folder_path: str, icon_path: str) -> bool:
        """应用图标到单个文件夹（统一入口）
        
        Args:
            folder_path: 目标文件夹路径
            icon_path: 图标文件路径
            
        Returns:
            是否应用成功
        """
        success, message = IconApplicator.apply_icon(folder_path, icon_path)
        if success:
            # 记录到缓存
            if self.current_folder_path:
                self.cache.add_applied_folders(self.current_folder_path, [folder_path])
            self.folder_tree.refresh_item_icon(folder_path)
            self.folder_tree.highlight_success(folder_path)
            QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.warning(self, "失败", message)
        return success
    
    def _restore_single_folder_icon(self, folder_path: str) -> bool:
        """恢复单个文件夹为默认图标（统一入口）
        
        Args:
            folder_path: 目标文件夹路径
            
        Returns:
            是否恢复成功
        """
        folder_name = os.path.basename(folder_path)
        reply = QMessageBox.question(
            self, 
            "确认恢复", 
            f"是否恢复 [{folder_name}] 的图标？\n\n这将删除自定义图标设置，恢复为系统默认文件夹图标。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return False
            
        success, message = IconApplicator.restore_icon(folder_path)
        if success:
            self.folder_tree.refresh_item_icon(folder_path)
            QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.warning(self, "失败", message)
        return success
    
    def _on_context_apply_icon(self, folder_path: str):
        """右键菜单：应用图标"""
        # 检查是否选择了图标
        selected_icon = None
        for item in self.icon_content.icon_items:
            if item._selected:
                selected_icon = item.icon_path
                break
        
        if not selected_icon:
            QMessageBox.warning(self, "提示", "还未选择任何图标\n\n请先在右侧图标列表中选择一个图标")
            return
        
        # 检查是否开启了"应用到子文件夹"
        if self.btn_apply_subfolders.isChecked():
            self._apply_icon_to_subfolders(folder_path, selected_icon)
        else:
            self._apply_icon_to_single_folder(folder_path, selected_icon)
    
    def _on_context_restore_icon(self, folder_path: str):
        """右键菜单：恢复默认图标"""
        folder_name = os.path.basename(folder_path)
        
        # 检查是否开启了"应用到子文件夹"
        if self.btn_apply_subfolders.isChecked():
            # 始终从缓存获取已应用图标的文件夹列表
            cached_folders = None
            if self.current_folder_path:
                cached_folders = self.cache.get_applied_folders(self.current_folder_path)
            
            if not cached_folders:
                QMessageBox.information(self, "提示", "没有需要恢复的文件夹\n\n缓存中没有已应用图标的记录")
                return
            
            all_folders = cached_folders
            
            reply = QMessageBox.question(
                self, 
                "确认恢复", 
                f"是否恢复 [{folder_name}] 及其子文件夹的图标？\n\n将恢复 {len(all_folders)} 个文件夹为默认图标。\n（已从缓存读取）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                return
            
            success_count = 0
            fail_count = 0
            restored_folders = []
            
            for folder in all_folders:
                success, message = IconApplicator.restore_icon(folder)
                if success:
                    success_count += 1
                    restored_folders.append(folder)
                else:
                    fail_count += 1
            
            # 从缓存中移除已恢复的文件夹
            if self.current_folder_path and restored_folders:
                self.cache.remove_applied_folders(self.current_folder_path, restored_folders)
            
            # 刷新文件夹树
            if self.current_folder_path:
                self.folder_tree.load_root_folder(self.current_folder_path)
            
            # 显示结果
            QMessageBox.information(
                self,
                "恢复完成",
                f"成功：{success_count} 个文件夹\n失败：{fail_count} 个文件夹"
            )
        else:
            self._restore_single_folder_icon(folder_path)
    
    def _restore_folder_icon(self):
        """恢复文件夹为默认图标（按钮触发）"""
        selected_items = self.folder_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "请先从左侧选择一个文件夹")
            return
        
        folder_path = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        if not folder_path:
            return
        
        self._restore_single_folder_icon(folder_path)
    
    def _on_apply_subfolders_toggled(self, checked: bool):
        """应用到子文件夹开关切换"""
        # 更新按钮样式以反映选中状态
        if checked:
            self.btn_apply_subfolders.setStyleSheet("""
                QPushButton {
                    background-color: #2196f3;
                    border: 2px solid #1976d2;
                    border-radius: 5px;
                    font-family: 'Arial', 'Microsoft YaHei', sans-serif;
                    font-size: 11px;
                    font-weight: bold;
                    color: #ffffff;
                    padding: 4px 12px;
                }
            """)
        else:
            self.btn_apply_subfolders.setStyleSheet("""
                QPushButton {
                    background-color: #ffffff;
                    border: 1px solid #d0d0d0;
                    border-radius: 5px;
                    font-family: 'Arial', 'Microsoft YaHei', sans-serif;
                    font-size: 11px;
                    font-weight: bold;
                    color: #333333;
                    padding: 4px 12px;
                }
                QPushButton:hover {
                    background-color: #e3f2fd;
                    border-color: #2196f3;
                    color: #1976d2;
                }
            """)
    
    def _get_all_subfolders(self, folder_path: str, use_cache: bool = True) -> List[str]:
        """递归获取所有子文件夹
        
        Args:
            folder_path: 文件夹路径
            use_cache: 是否优先使用缓存
        """
        # 优先从缓存读取
        if use_cache:
            cached = self.cache.get_subfolders(folder_path)
            if cached is not None:
                return cached
        
        subfolders = []
        try:
            for entry in os.scandir(folder_path):
                if entry.is_dir(follow_symlinks=False):
                    if entry.name.startswith('.'):
                        continue
                    try:
                        if sys.platform == 'win32':
                            import stat
                            attrs = entry.stat(follow_symlinks=False).st_file_attributes
                            if attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM):
                                continue
                    except:
                        pass
                    subfolders.append(entry.path)
                    subfolders.extend(self._get_all_subfolders(entry.path, use_cache=False))
        except PermissionError:
            pass
        except Exception as e:
            print(f"获取子文件夹失败: {e}")
        
        # 缓存结果
        if use_cache and subfolders:
            self.cache.save_subfolders(folder_path, subfolders)
        
        return subfolders
    
    def _expand_all_children(self, item: QTreeWidgetItem):
        """展开某节点的所有子节点"""
        for i in range(item.childCount()):
            child = item.child(i)
            child.setExpanded(True)
            self._expand_all_children(child)
    
    def _apply_icon_to_subfolders(self, folder_path: str, icon_path: str):
        """将图标应用到文件夹及其所有子文件夹"""
        # 获取所有子文件夹（会自动缓存）
        all_folders = [folder_path] + self._get_all_subfolders(folder_path)
        
        if len(all_folders) <= 1:
            QMessageBox.information(self, "提示", "该文件夹没有子文件夹")
            return
        
        # 确认对话框
        reply = QMessageBox.question(
            self,
            "确认应用",
            f"是否将图标应用到所有子文件夹？\n\n将应用到 {len(all_folders)} 个文件夹",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 显示进度
        success_count = 0
        fail_count = 0
        applied_folders = []  # 记录成功应用的文件夹
        
        for folder in all_folders:
            success, message = IconApplicator.apply_icon(folder, icon_path)
            if success:
                success_count += 1
                applied_folders.append(folder)
            else:
                fail_count += 1
        
        # 记录已应用图标的文件夹到缓存（以当前根文件夹为键）
        if applied_folders and self.current_folder_path:
            self.cache.add_applied_folders(self.current_folder_path, applied_folders)
        
        # 刷新文件夹树
        if self.current_folder_path:
            self.folder_tree.load_root_folder(self.current_folder_path)
        
        # 展开选中的文件夹
        selected_items = self.folder_tree.selectedItems()
        if selected_items:
            selected_items[0].setExpanded(True)
            self._expand_all_children(selected_items[0])
        
        # 显示结果
        QMessageBox.information(
            self,
            "应用完成",
            f"成功：{success_count} 个文件夹\n失败：{fail_count} 个文件夹"
        )
    
    def _on_icon_double_clicked(self, icon_path: str):
        """双击图标应用"""
        selected_items = self.folder_tree.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "提示", "请先从左侧选择一个文件夹")
            return
        
        folder_path = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
        if not folder_path:
            return
        
        # 检查是否开启了"应用到子文件夹"
        if self.btn_apply_subfolders.isChecked():
            self._apply_icon_to_subfolders(folder_path, icon_path)
        else:
            self._apply_icon_to_single_folder(folder_path, icon_path)
    
    def _normalize_name(self, name: str) -> str:
        """规范化名称：移除所有符号，只保留字母和数字
        
        例如：
        - "7-Zip" -> "7zip"
        - "Visual_Studio" -> "visualstudio"
        - "Git-2.42" -> "git242"
        """
        import re
        # 只保留字母和数字，转小写
        return re.sub(r'[^a-zA-Z0-9]', '', name).lower()
    
    def _extract_folder_base_name(self, folder_name: str) -> str:
        """提取文件夹名称的基础部分，忽略版本号等后缀
        
        例如：
        - "BetterJoy_v7.1" -> "BetterJoy"
        - "blender-4.5.5-windows-x64" -> "blender"
        - "VSCode-win32-x64-1.85.0" -> "VSCode"
        - "Python 3.12" -> "Python"
        """
        import re
        
        # 常见版本号模式
        patterns = [
            r'_v?\d+[\.\d]*.*$',      # _v7.1, _1.0.0, _v2.0.0-beta
            r'-\d+[\.\d]*.*$',        # -4.5.5-windows-x64, -1.85.0
            r'\s+v?\d+[\.\d]*.*$',    # 空格+版本号 " 3.12", " v2.0"
            r'_\d{4}.*$',             # 年份后缀 _2023, _2024
            r'_win\d+.*$',            # _win32, _win64
            r'_windows.*$',           # _windows, _windows-x64
            r'-win\d+.*$',            # -win32, -win64
            r'-windows.*$',           # -windows, -windows-x64
            r'-x\d+.*$',              # -x64, -x86
            r'_x\d+.*$',              # _x64, _x86
            r'-linux.*$',             # -linux, -linux-x64
            r'-macos.*$',             # -macos, -macos-arm64
            r'-darwin.*$',            # -darwin
            r'-osx.*$',               # -osx
            r'-arm\d*.*$',            # -arm, -arm64
            r'_beta.*$',              # _beta, _beta1
            r'_alpha.*$',             # _alpha, _alpha1
            r'_rc\d*.*$',             # _rc, _rc1
            r'_final.*$',             # _final
            r'_stable.*$',            # _stable
            r'_portable.*$',          # _portable
            r'-portable.*$',          # -portable
            r'_setup.*$',             # _setup
            r'-setup.*$',             # -setup
            r'_installer.*$',         # _installer
            r'-installer.*$',         # -installer
        ]
        
        result = folder_name
        for pattern in patterns:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        
        # 清理末尾的特殊字符
        result = re.sub(r'[-_\s]+$', '', result)
        
        return result.strip()
    
    def _find_matching_icon(self, folder_name: str) -> Optional[str]:
        """根据文件夹名称查找匹配的图标
        
        匹配规则（按优先级）：
        1. 先提取文件夹基础名称（去除版本号）
        2. 分割名称为多个词（忽略中间的字符或空格）
        3. 优先用第一个词匹配，如果匹配到多个图标有相同前缀：
           - 如果文件夹名与前缀相同，优先匹配第一个
           - 否则跳过前缀，用剩余部分匹配
        4. 如果第一个词没匹配到，尝试用第二个词匹配
        5. 最后回退到完整名称匹配
        
        例如：
        - "IObit Unlocker" → 先搜索 "IObit"，没找到再搜索 "Unlocker"
        - "4k_video" 与图标 "4k_video", "4k_youtube" → 文件夹与前缀 "4k" 相同，匹配 "4k_video"
        - "Adobe_after" 与图标 "Adobe_after", "Adobe_bridge" → 文件夹与前缀 "Adobe" 相同，匹配 "Adobe_after"
        """
        if not self.icon_content.icon_data:
            return None
        
        base_name = self._extract_folder_base_name(folder_name)
        if not base_name:
            return None
        
        # 规范化后的名称用于匹配
        normalized_base = self._normalize_name(base_name)
        if not normalized_base:
            return None
        
        # 分割名称为多个词（按空格、下划线、横线等分割）
        words = self._split_name_to_words(base_name)
        
        # 第一步：尝试用第一个词匹配
        if words:
            first_word = self._normalize_name(words[0])
            if first_word and len(first_word) >= 2:  # 至少2个字符才有意义
                matched_icons = self._find_icons_containing(first_word)
                
                if matched_icons:
                    # 检查是否有前缀冲突
                    result = self._handle_prefix_conflict(matched_icons, normalized_base, first_word)
                    if result:
                        return result
        
        # 第二步：如果第一个词没匹配到，尝试用第二个词匹配
        if len(words) >= 2:
            second_word = self._normalize_name(words[1])
            if second_word and len(second_word) >= 2:
                matched_icons = self._find_icons_containing(second_word)
                
                if matched_icons:
                    # 检查是否有前缀冲突
                    result = self._handle_prefix_conflict(matched_icons, normalized_base, second_word)
                    if result:
                        return result
        
        # 第三步：回退到完整名称匹配
        for icon_path, icon_name in self.icon_content.icon_data:
            normalized_icon = self._normalize_name(icon_name)
            if normalized_base in normalized_icon:
                return icon_path
        
        return None
    
    def _split_name_to_words(self, name: str) -> List[str]:
        """将名称分割为多个词
        
        按空格、下划线、横线等分割，忽略单个字符
        例如：'IObit Unlocker' → ['IObit', 'Unlocker']
             'Adobe_after_effects' → ['Adobe', 'after', 'effects']
        """
        import re
        # 按非字母数字字符分割
        words = re.split(r'[^a-zA-Z0-9]+', name)
        # 过滤空字符串和单个字符
        return [w for w in words if len(w) >= 2]
    
    def _find_icons_containing(self, keyword: str) -> List[Tuple[str, str]]:
        """查找包含指定关键词的所有图标
        
        返回：(icon_path, icon_name) 列表
        """
        matched = []
        for icon_path, icon_name in self.icon_content.icon_data:
            normalized_icon = self._normalize_name(icon_name)
            if keyword in normalized_icon:
                matched.append((icon_path, icon_name))
        return matched
    
    def _handle_prefix_conflict(self, matched_icons: List[Tuple[str, str]], 
                                 folder_normalized: str, keyword: str) -> Optional[str]:
        """处理前缀冲突
        
        如果匹配到多个图标有相同前缀：
        - 如果文件夹名与前缀相同，返回第一个匹配
        - 否则跳过前缀，尝试用剩余部分匹配
        
        参数：
        - matched_icons: 匹配到的图标列表 [(icon_path, icon_name), ...]
        - folder_normalized: 规范化后的文件夹名
        - keyword: 当前搜索的关键词
        
        返回：匹配的图标路径，或 None
        """
        if len(matched_icons) == 1:
            # 只匹配到一个，直接返回
            return matched_icons[0][0]
        
        # 提取所有匹配图标的前缀
        prefixes = []
        for icon_path, icon_name in matched_icons:
            normalized_icon = self._normalize_name(icon_name)
            # 找到关键词在图标名中的位置
            idx = normalized_icon.find(keyword)
            if idx == 0:
                # 关键词在开头，提取前缀（关键词本身就是前缀）
                prefixes.append((keyword, icon_path, icon_name))
            else:
                # 关键词不在开头，可能有其他前缀
                # 提取关键词之前的部分作为前缀
                prefix = normalized_icon[:idx]
                if prefix:
                    prefixes.append((prefix, icon_path, icon_name))
                else:
                    prefixes.append((keyword, icon_path, icon_name))
        
        # 检查是否有相同的前缀
        prefix_count = {}
        for prefix, icon_path, icon_name in prefixes:
            prefix_count[prefix] = prefix_count.get(prefix, 0) + 1
        
        # 找到出现次数最多的前缀（可能是公司名等）
        common_prefix = None
        max_count = 0
        for prefix, count in prefix_count.items():
            if count > max_count and len(prefix) >= 2:
                max_count = count
                common_prefix = prefix
        
        # 如果有公共前缀，且出现次数 >= 2
        if common_prefix and max_count >= 2:
            # 检查文件夹名是否与该前缀相同
            if folder_normalized == common_prefix:
                # 文件夹与前缀相同，返回第一个匹配
                for prefix, icon_path, icon_name in prefixes:
                    if prefix == common_prefix:
                        return icon_path
            
            # 文件夹与前缀不同，跳过前缀匹配，尝试用剩余部分匹配
            # 例如：文件夹 "YouTube"，图标 "4k_video", "4k_youtube"
            # 前缀是 "4k"，文件夹不是 "4k"，所以匹配 "youtube"
            for prefix, icon_path, icon_name in prefixes:
                normalized_icon = self._normalize_name(icon_name)
                # 移除前缀后检查
                remaining = normalized_icon[len(prefix):]
                if remaining and folder_normalized in remaining:
                    return icon_path
                # 或者文件夹包含在图标名中（但不只是前缀）
                if folder_normalized != prefix and folder_normalized in normalized_icon:
                    return icon_path
            
            # 如果上述都没匹配到，返回第一个
            return matched_icons[0][0]
        
        # 没有前缀冲突，返回第一个匹配
        return matched_icons[0][0]
    
    def _on_auto_match_clicked(self):
        """自动匹配按钮点击事件
        
        功能说明：
        - 如果选中了某个子文件夹：只匹配该文件夹
        - 如果没有选中或选中了根目录：匹配当前目录下所有一级子文件夹
        - 不受"应用到子文件夹"开关影响
        - 只匹配母文件夹，不递归匹配子文件夹的子文件夹
        """
        import re
        
        # 检查是否有图标数据
        if not self.icon_content.icon_data:
            QMessageBox.warning(self, "提示", "请先加载图标库\n\n确保 ico 文件夹中存在 .ico 文件")
            return
        
        # 检查是否选择了文件夹
        if not self.current_folder_path:
            QMessageBox.warning(self, "提示", "请先选择一个文件夹")
            return
        
        # 检查是否有选中的子文件夹
        selected_items = self.folder_tree.selectedItems()
        if selected_items:
            selected_path = selected_items[0].data(0, Qt.ItemDataRole.UserRole)
            # 如果选中的不是根目录，则只匹配该文件夹
            if selected_path and selected_path != self.current_folder_path:
                folder_name = os.path.basename(selected_path)
                icon_path = self._find_matching_icon(folder_name)
                
                if not icon_path:
                    QMessageBox.information(self, "提示", f"未找到与 \"{folder_name}\" 匹配的图标")
                    return
                
                # 弹出确认框
                reply = QMessageBox.question(
                    self,
                    "自动匹配确认",
                    f"将对选中的文件夹进行自动匹配\n\n"
                    f"文件夹：{folder_name}\n"
                    f"路径：{selected_path}\n"
                    f"匹配图标：{os.path.splitext(os.path.basename(icon_path))[0]}\n\n"
                    f"是否继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                
                if reply != QMessageBox.StandardButton.Yes:
                    return
                
                # 执行单个文件夹匹配
                self._auto_match_folders([selected_path])
                return
        
        # 获取当前目录下所有一级子文件夹（母文件夹）
        try:
            subfolders = []
            for entry in os.scandir(self.current_folder_path):
                if entry.is_dir(follow_symlinks=False):
                    # 跳过隐藏文件夹
                    if entry.name.startswith('.'):
                        continue
                    try:
                        if sys.platform == 'win32':
                            import stat
                            attrs = entry.stat(follow_symlinks=False).st_file_attributes
                            if attrs & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM):
                                continue
                    except:
                        pass
                    subfolders.append(entry.path)
        except PermissionError:
            QMessageBox.warning(self, "错误", "无法访问该文件夹")
            return
        except Exception as e:
            QMessageBox.warning(self, "错误", f"读取文件夹失败：{str(e)}")
            return
        
        if not subfolders:
            QMessageBox.information(self, "提示", "当前文件夹下没有子文件夹")
            return
        
        # 弹出确认框
        reply = QMessageBox.question(
            self,
            "自动匹配确认",
            f"将对当前目录下的 {len(subfolders)} 个文件夹进行自动匹配\n\n"
            f"路径：{self.current_folder_path}\n\n"
            f"是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        # 执行批量匹配
        self._auto_match_folders(subfolders)
    
    def _auto_match_folders(self, folder_paths: List[str]):
        """批量自动匹配多个文件夹（仅匹配一级文件夹，不递归）"""
        matched_count = 0
        not_matched_count = 0
        success_count = 0
        fail_count = 0
        match_details = []  # 记录匹配详情
        applied_folders = []  # 记录成功应用的文件夹路径
        
        try:
            for folder_path in folder_paths:
                folder_name = os.path.basename(folder_path)
                icon_path = self._find_matching_icon(folder_name)
                
                if icon_path:
                    matched_count += 1
                    success, _ = IconApplicator.apply_icon(folder_path, icon_path)
                    icon_name = os.path.splitext(os.path.basename(icon_path))[0]
                    if success:
                        success_count += 1
                        applied_folders.append(folder_path)
                        match_details.append(f"✅ {folder_name} → {icon_name}")
                    else:
                        fail_count += 1
                        match_details.append(f"❌ {folder_name} → 匹配失败")
                else:
                    not_matched_count += 1
                
                # 让界面保持响应
                QApplication.processEvents()
        except Exception as e:
            QMessageBox.warning(self, "错误", f"匹配过程发生错误：{str(e)}")
            return
        
        # 记录成功应用的文件夹到缓存
        if applied_folders and self.current_folder_path:
            self.cache.add_applied_folders(self.current_folder_path, applied_folders)
        
        # 刷新文件夹树
        self.folder_tree.load_root_folder(self.current_folder_path)
        
        # 显示结果
        result_msg = (
            f"📊 自动匹配完成\n\n"
            f"✅ 匹配成功：{success_count} 个\n"
            f"❌ 应用失败：{fail_count} 个\n"
            f"🔍 未找到图标：{not_matched_count} 个\n"
            f"📁 总计：{len(folder_paths)} 个文件夹"
        )
        
        # 如果有匹配成功的，显示详情
        if match_details:
            detail_msg = result_msg + "\n\n" + "─" * 30 + "\n匹配详情：\n" + "\n".join(match_details[:20])
            if len(match_details) > 20:
                detail_msg += f"\n... 等共 {len(match_details)} 项"
        else:
            detail_msg = result_msg
        
        QMessageBox.information(self, "匹配完成", detail_msg)


# ==================== 程序入口 ====================
def main():
    # Windows 下检查管理员权限，如果没有则尝试提权
    if sys.platform == 'win32' and not is_admin():
        print("正在申请管理员权限...")
        run_as_admin()
        # 如果提权失败，继续以普通权限运行
        print("未能获取管理员权限，以普通模式运行")
    
    # 高 DPI 支持
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    
    window = FolderIconChanger()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    # 支持单文件模式下启动子模块
    if len(sys.argv) > 1:
        if sys.argv[1] == '--run-creator':
            sys.argv.pop(1)
            import icon_creator
            icon_creator.main()
            sys.exit(0)
        elif sys.argv[1] == '--run-downloader':
            sys.argv.pop(1)
            import icon_downloader
            icon_downloader.main()
            sys.exit(0)
            
    main()
