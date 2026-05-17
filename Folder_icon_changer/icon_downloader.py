#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Folder11 Icon Downloader
从多个数据源批量下载 .ico 图标文件，支持内容去重
"""

import os
import sys
import json
import urllib.request
import urllib.error
import ssl
import hashlib
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import argparse

from PyQt6.QtCore import Qt, pyqtSignal, pyqtSlot, QThread, QTimer
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QProgressBar, QPushButton, QHBoxLayout


class DownloadProgressWindow(QWidget):
    progress_changed = pyqtSignal(int)
    task_changed = pyqtSignal(str)
    cancel_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_task_text = ""
        self._finished = False
        self.setWindowTitle("下载进度")
        self.setFixedSize(400, 120)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.task_label = QLabel("")
        self.task_label.setToolTip("")
        self.task_label.setFixedHeight(18)
        self.task_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        root.addWidget(self.task_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        self.progress.setFixedHeight(24)
        root.addWidget(self.progress)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedSize(100, 28)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        bottom.addWidget(self.cancel_btn)
        root.addLayout(bottom)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._full_task_text:
            self._set_task_text_internal(self._full_task_text)

    @pyqtSlot(int)
    def set_progress(self, value: int):
        v = max(0, min(100, int(value)))
        self.progress.setValue(v)
        self.progress_changed.emit(v)

    @pyqtSlot(str)
    def set_task(self, text: str):
        t = text or ""
        self._full_task_text = t
        self._set_task_text_internal(t)
        self.task_changed.emit(t)

    def _set_task_text_internal(self, text: str):
        self.task_label.setToolTip(text)
        width = max(0, self.task_label.width() - 2)
        metrics = QFontMetrics(self.task_label.font())
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight, width)
        self.task_label.setText(elided)

    def _on_cancel_clicked(self):
        if self._finished:
            self.close()
            return
        if not self.cancel_btn.isEnabled():
            return
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("正在取消…")
        self.cancel_requested.emit()
        self.close()  # 取消后直接关闭窗口，不再等待

    @pyqtSlot()
    def set_finished(self):
        self._finished = True
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("完成")


class DownloadWorker(QThread):
    progress = pyqtSignal(int)
    task = pyqtSignal(str)
    error = pyqtSignal(str)
    finished_ok = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, run_callable, parent=None):
        super().__init__(parent)
        self._run_callable = run_callable
        self._cancelled = False

    @pyqtSlot()
    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self._run_callable(self)
            if self._cancelled:
                self.cancelled.emit()
            else:
                self.finished_ok.emit()
        except Exception as e:
            self.error.emit(str(e))


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

class IconDownloader:
    def __init__(self):
        # 获取脚本所在目录，确保文件保存在脚本同目录下
        # 兼容 PyInstaller 打包环境
        self.script_dir = get_app_root_dir()
        self.resource_dir = get_resource_dir()
        
        # 数据源配置
        # 数据源1: GitHub 仓库 ico 文件夹（优先）
        self.github_api_url = "https://api.github.com/repos/icon11-community/Folder-Ico/contents/ico"
        self.github_raw_base = "https://raw.githubusercontent.com/icon11-community/Folder-Ico/main/ico/"
        
        # 数据源2: JSON 数据源（备用）
        self.json_url = "https://raw.githubusercontent.com/icon11-community/Folder-Ico/main/Folder11.json"
        
        # 本地 JSON 文件（备用）优先在资源目录查找
        self.local_json = os.path.join(self.resource_dir, "icons_data.json")
        if not os.path.exists(self.local_json):
            # 回退到 exe 所在目录
            self.local_json = os.path.join(self.script_dir, "icons_data.json")
        
        # 保存目录（在脚本所在目录下）
        self.save_dir = os.path.join(self.script_dir, "ico")
        
        # 统计信息
        self.total_count = 0
        self.success_count = 0
        self.skip_count = 0
        self.dup_count = 0  # 内容重复跳过计数
        self.fail_count = 0
        self.failed_list = []
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        
        # 本地文件的哈希集合（用于去重）
        self.local_hashes = set()
        
        # 创建 SSL 上下文（跳过证书验证，某些环境下需要）
        self.ssl_context = ssl.create_default_context()
        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE
    
    def create_directory(self):
        """创建保存目录"""
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
            print(f"[OK] 已创建目录: {self.save_dir}")
        else:
            print(f"[OK] 目录已存在: {self.save_dir}")
    
    def calculate_file_hash(self, filepath):
        """计算文件的 MD5 哈希值"""
        try:
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return None
    
    def build_local_hash_set(self):
        """构建本地已存在文件的哈希集合"""
        print(f"\n正在扫描本地已有文件并计算哈希值...")
        if not os.path.exists(self.save_dir):
            return
        
        ico_files = [f for f in os.listdir(self.save_dir) if f.endswith('.ico')]
        for filename in ico_files:
            filepath = os.path.join(self.save_dir, filename)
            file_hash = self.calculate_file_hash(filepath)
            if file_hash:
                self.local_hashes.add(file_hash)
        
        print(f"[OK] 已扫描 {len(ico_files)} 个本地文件，哈希集合大小: {len(self.local_hashes)}")
    
    def fetch_from_github(self):
        """从 GitHub API 获取图标列表（优先数据源）"""
        icons = []
        print(f"\n[数据源1] 正在从 GitHub 仓库获取图标列表...")
        try:
            request = urllib.request.Request(
                self.github_api_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/vnd.github.v3+json'
                }
            )
            with urllib.request.urlopen(request, context=self.ssl_context, timeout=60) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                for item in data:
                    if item.get('type') == 'file' and item.get('name', '').endswith('.ico'):
                        icons.append({
                            'name': item['name'].replace('.ico', ''),
                            'url': item.get('download_url', ''),
                            'source': 'GitHub'
                        })
                
                print(f"[OK] 从 GitHub 获取到 {len(icons)} 个图标")
                return icons
        except Exception as e:
            print(f"[WARN] GitHub 数据源获取失败: {e}")
            return []
    
    def fetch_from_json(self):
        """从 JSON 获取图标列表（备用数据源）"""
        icons = []
        
        # 优先尝试本地文件
        if os.path.exists(self.local_json):
            print(f"\n[数据源2] 正在从本地文件读取图标列表: {self.local_json}")
            try:
                with open(self.local_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    raw_icons = data.get('icons', [])
                    for icon in raw_icons:
                        icons.append({
                            'name': icon.get('name', 'unknown'),
                            'url': icon.get('url_icon', ''),
                            'source': 'JSON'
                        })
                print(f"[OK] 从本地文件读取到 {len(icons)} 个图标")
                return icons
            except Exception as e:
                print(f"[WARN] 本地文件读取失败: {e}")
        
        # 在线获取
        print(f"\n[数据源2] 正在在线获取图标列表...")
        try:
            request = urllib.request.Request(
                self.json_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
            )
            with urllib.request.urlopen(request, context=self.ssl_context, timeout=60) as response:
                data = json.loads(response.read().decode('utf-8'))
                raw_icons = data.get('icons', [])
                for icon in raw_icons:
                    icons.append({
                        'name': icon.get('name', 'unknown'),
                        'url': icon.get('url_icon', ''),
                        'source': 'JSON'
                    })
                print(f"[OK] 在线获取到 {len(icons)} 个图标")
                return icons
        except Exception as e:
            print(f"[WARN] JSON 数据源获取失败: {e}")
            return []
    
    def download_icon(self, icon_info, max_retries=3):
        """下载单个图标（带重试机制和内容去重）"""
        if self.cancel_event.is_set():
            return False
        name = icon_info.get('name', 'unknown')
        url = icon_info.get('url', '')
        source = icon_info.get('source', 'unknown')
        
        if not url:
            with self.lock:
                self.fail_count += 1
                self.failed_list.append((name, "URL为空", source))
            return False
        
        # 文件保存路径
        filename = f"{name}.ico"
        filepath = os.path.join(self.save_dir, filename)
        
        # 如果文件已存在且大小>0，跳过
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            with self.lock:
                self.skip_count += 1
            return True
        
        # 先下载内容到内存，用于哈希比对
        downloaded_data = None
        for attempt in range(max_retries):
            if self.cancel_event.is_set():
                return False
            try:
                request = urllib.request.Request(
                    url,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                )
                with urllib.request.urlopen(request, context=self.ssl_context, timeout=30) as response:
                    downloaded_data = response.read()
                    if len(downloaded_data) > 0:
                        break
                    else:
                        raise Exception("下载内容为空")
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                else:
                    with self.lock:
                        self.fail_count += 1
                        self.failed_list.append((name, str(e), source))
                    return False
        
        if not downloaded_data:
            return False
        
        # 计算下载内容的哈希值
        content_hash = hashlib.md5(downloaded_data).hexdigest()
        
        # 检查是否与本地已有文件内容重复
        with self.lock:
            if content_hash in self.local_hashes:
                self.dup_count += 1
                return True  # 内容重复，跳过保存
            # 将新哈希加入集合（防止后续重复下载相同内容）
            self.local_hashes.add(content_hash)
        
        # 保存文件
        try:
            with open(filepath, 'wb') as f:
                f.write(downloaded_data)
            with self.lock:
                self.success_count += 1
            return True
        except Exception as e:
            with self.lock:
                self.fail_count += 1
                self.failed_list.append((name, str(e), source))
            return False
    
    def download_batch(
        self,
        icons,
        source_name,
        *,
        verbose: bool = True,
        task_callback=None,
        progress_callback=None,
        overall_done=None,
        overall_total: int = 0,
    ):
        """批量下载图标"""
        if not icons:
            return
        
        total = len(icons)
        if verbose:
            print(f"\n开始下载 [{source_name}] 的 {total} 个图标...")
            print("-" * 50)
        
        if self.cancel_event.is_set():
            return

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self.download_icon, icon): icon for icon in icons}
            
            completed = 0
            for future in as_completed(futures):
                if self.cancel_event.is_set():
                    executor.shutdown(wait=False, cancel_futures=True)
                    return
                icon = futures.get(future)
                if task_callback and icon:
                    try:
                        task_callback(f"{source_name}: {icon.get('name', 'unknown')}.ico")
                    except Exception:
                        pass
                completed += 1

                if overall_done is not None and overall_total > 0:
                    overall_done[0] += 1
                    if progress_callback:
                        try:
                            progress_callback(overall_done[0], overall_total)
                        except Exception:
                            pass
                
                # 显示进度（每10个更新一次，减少输出频率）
                if verbose and (completed % 10 == 0 or completed == total):
                    progress = (completed / total) * 100
                    print(f"\r进度: {completed}/{total} ({progress:.1f}%) | 成功: {self.success_count} 已存在: {self.skip_count} 重复跳过: {self.dup_count} 失败: {self.fail_count}", end="", flush=True)
        
        if verbose:
            print()  # 换行
    
    def run(self):
        """运行下载器"""
        print("=" * 50)
        print("  Folder11 Icon Downloader v2.0")
        print("  多数据源图标下载工具（支持内容去重）")
        print("=" * 50)
        
        start_time = datetime.now()
        
        self.create_directory()
        self.build_local_hash_set()  # 构建本地哈希集合
        
        # 优先从 GitHub 下载
        github_icons = self.fetch_from_github()
        if github_icons:
            self.download_batch(github_icons, "GitHub")
        
        # 再从 JSON 数据源下载
        json_icons = self.fetch_from_json()
        if json_icons:
            # 过滤掉已经在 GitHub 下载过的（按名称去重）
            github_names = {icon['name'] for icon in github_icons} if github_icons else set()
            new_json_icons = [icon for icon in json_icons if icon['name'] not in github_names]
            
            if new_json_icons:
                print(f"\n[INFO] JSON 数据源中有 {len(new_json_icons)} 个新图标（排除已下载）")
                self.download_batch(new_json_icons, "JSON")
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # 打印统计结果
        print("\n" + "=" * 50)
        print("下载完成!")
        print(f"  新下载: {self.success_count}")
        print(f"  已存在跳过: {self.skip_count}")
        print(f"  内容重复跳过: {self.dup_count}")
        print(f"  失败: {self.fail_count}")
        print(f"  耗时: {duration:.2f} 秒")
        print(f"  目录: {self.save_dir}")
        
        # 如果有失败的，显示详情
        if self.failed_list:
            print(f"\n[WARN] {len(self.failed_list)} 个文件下载失败:")
            for name, error, source in self.failed_list[:10]:  # 只显示前10个
                print(f"  - {name} [{source}]: {error}")
            if len(self.failed_list) > 10:
                print(f"  ... 还有 {len(self.failed_list) - 10} 个失败")
        
        print("\n全部完成!")

    def run_with_ui(self):
        app = QApplication.instance() or QApplication(sys.argv)
        window = DownloadProgressWindow()

        def _runner(worker: DownloadWorker):
            worker.task.emit("初始化…")
            worker.progress.emit(0)
            self.create_directory()
            self.build_local_hash_set()

            worker.task.emit("获取图标列表（GitHub）…")
            github_icons = self.fetch_from_github()

            if self.cancel_event.is_set():
                return

            worker.task.emit("获取图标列表（JSON）…")
            json_icons = self.fetch_from_json()

            if self.cancel_event.is_set():
                return

            github_names = {icon['name'] for icon in github_icons} if github_icons else set()
            new_json_icons = [icon for icon in json_icons if icon['name'] not in github_names] if json_icons else []

            overall_total = len(github_icons) + len(new_json_icons)
            overall_done = [0]

            def progress_cb(done: int, total: int):
                if total <= 0:
                    pct = 100
                else:
                    pct = int((done / total) * 100)
                worker.progress.emit(max(0, min(100, pct)))

            def task_cb(text: str):
                worker.task.emit(text)

            if overall_total == 0:
                worker.progress.emit(100)
                worker.task.emit("未找到可下载的图标")
                return

            worker.task.emit("开始下载…")
            worker.progress.emit(0)

            if github_icons and not self.cancel_event.is_set():
                self.download_batch(
                    github_icons,
                    "GitHub",
                    verbose=False,
                    task_callback=task_cb,
                    progress_callback=progress_cb,
                    overall_done=overall_done,
                    overall_total=overall_total,
                )

            if new_json_icons and not self.cancel_event.is_set():
                self.download_batch(
                    new_json_icons,
                    "JSON",
                    verbose=False,
                    task_callback=task_cb,
                    progress_callback=progress_cb,
                    overall_done=overall_done,
                    overall_total=overall_total,
                )

            if self.cancel_event.is_set():
                worker.task.emit("已取消")
                return

            worker.progress.emit(100)
            worker.task.emit(
                f"完成：新下载 {self.success_count}，已存在 {self.skip_count}，重复 {self.dup_count}，失败 {self.fail_count}"
            )

        worker = DownloadWorker(_runner)
        worker.progress.connect(window.set_progress)
        worker.task.connect(window.set_task)
        worker.finished_ok.connect(window.set_finished)

        def _on_cancel():
            self.cancel_event.set()
            worker.cancel()
            worker.task.emit("正在取消…")

        window.cancel_requested.connect(_on_cancel)
        worker.error.connect(lambda msg: window.set_task(f"错误: {msg}"))
        worker.start()

        window.show()
        app.exec()

    @staticmethod
    def run_ui_demo():
        app = QApplication.instance() or QApplication(sys.argv)
        window = DownloadProgressWindow()
        window.set_task("UI 演示：准备中…")
        window.set_progress(0)

        state = {"p": 0}

        def tick():
            state["p"] += 7
            p = min(100, state["p"])
            window.set_progress(p)
            window.set_task(f"UI 演示：进度 {p}%（不会联网）")
            if p >= 100:
                window.set_task("UI 演示：完成（窗口不会自动关闭）")
                window.set_finished()

        timer = QTimer()
        timer.timeout.connect(tick)
        timer.start(120)

        window.show()
        app.exec()

    @staticmethod
    def run_ui_smoke_test():
        app = QApplication.instance() or QApplication(sys.argv)
        window = DownloadProgressWindow()
        window.set_task("UI Smoke Test")
        window.set_progress(100)
        window.set_finished()
        window.show()

        def quit_app():
            window.close()
            app.quit()

        QTimer.singleShot(300, quit_app)
        app.exec()


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--ui", action="store_true", help="使用 Qt 进度窗口模式运行")
    parser.add_argument("--ui-demo", action="store_true", help="仅显示 UI 演示（不联网，不下载）")
    parser.add_argument("--ui-smoke-test", action="store_true", help="UI 冒烟测试：弹窗后自动退出（用于单元测试）")
    args, _unknown = parser.parse_known_args()

    downloader = IconDownloader()

    if args.ui_demo:
        downloader.run_ui_demo()
    elif args.ui_smoke_test:
        downloader.run_ui_smoke_test()
    elif args.ui:
        downloader.run_with_ui()
    else:
        print("\n" + "=" * 50)
        print("  Folder11 Icon Downloader v2.0")
        print("  多数据源图标下载工具（支持内容去重）")
        print("=" * 50)
        
        print("\n数据源优先级:")
        print("  1. GitHub 仓库 (icon11-community/Folder-Ico/ico)")
        print("  2. JSON 数据源 (Folder11.json)")
        print("\n提示: 将 icons_data.json 放在本程序同目录下")
        print("      可加速启动并避免网络问题\n")
        print("提示：如需 UI 进度窗口，请使用：python icon_downloader.py --ui\n")

        downloader.run()

        # 仅在有可见终端时阻止窗口闪退（Windows 双击运行时）
        try:
            if sys.stdin and sys.stdin.isatty():
                input("\n按 Enter 键退出...")
        except Exception:
            pass

if __name__ == "__main__":
    main()
