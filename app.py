import sys
import os
import json
import re
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QProgressBar, QLabel, QHeaderView,
    QTabWidget, QCheckBox, QFileDialog, QHBoxLayout, QMessageBox,
    QTextEdit, QComboBox, QSpinBox, QGroupBox, QFrame, QSizePolicy
)
from PyQt6.QtCore import QProcess, Qt, QTimer, pyqtSignal, QObject, QRectF
from PyQt6.QtGui import QIcon, QPainter, QPainterPath, QColor, QPixmap

class TabButtonBackground(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(404, 60)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)

        # Create the static pixmap once
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 15, 15)

        brush_color = QColor(255, 255, 255, 100)
        painter.fillPath(path, brush_color)
        painter.end()

        self.setPixmap(pixmap)

        geometry = self.geometry()
        x = geometry.x() + 6
        self.move(x, geometry.y())

class DownloadItem:
    def __init__(self, url, format_id, format_type, output_path, title="Unknown"):
        self.url = url
        self.format_id = format_id
        self.format_type = format_type
        self.output_path = output_path
        self.title = title
        self.status = "Queued"
        self.progress = 0
        self.process = None
        self.added_time = datetime.now()
        self.start_time = None
        self.end_time = None
        self.file_size = ""
        self.download_speed = ""

class DownloadHistory:
    def __init__(self, history_file="Saves/download_history.json"):
        self.history_file = history_file
        self.history = []

        # Ensure folder exists
        folder = os.path.dirname(self.history_file)
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

        # Ensure file exists
        if not os.path.exists(self.history_file):
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump([], f, indent=2)

        self.load_history()

    def load_history(self):
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.history = data
        except Exception as e:
            print(f"Error loading history: {e}")
            self.history = []

    def save_history(self):
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=2, ensure_ascii=False, default=str)
        except Exception as e:
            print(f"Error saving history: {e}")

    def add_item(self, download_item):
        history_entry = {
            "title": download_item.title,
            "url": download_item.url,
            "format_id": download_item.format_id,
            "format_type": download_item.format_type,
            "output_path": download_item.output_path,
            "status": download_item.status,
            "added_time": download_item.added_time.isoformat(),
            "start_time": download_item.start_time.isoformat() if download_item.start_time else None,
            "end_time": download_item.end_time.isoformat() if download_item.end_time else None,
            "file_size": download_item.file_size
        }
        self.history.insert(0, history_entry)
        self.save_history()

class DownloadManager(QObject):
    download_started = pyqtSignal(str)
    download_progress = pyqtSignal(str, int, str)
    download_finished = pyqtSignal(str, bool)
    
    def __init__(self, max_concurrent=3):
        super().__init__()
        self.max_concurrent = max_concurrent
        self.queue = []
        self.active_downloads = {}
        self.item_counter = 0
        
    def add_to_queue(self, download_item):
        self.item_counter += 1
        download_item.id = str(self.item_counter)
        self.queue.append(download_item)
        self.process_queue()
    
    def process_queue(self):
        while len(self.active_downloads) < self.max_concurrent and self.queue:
            item = self.queue.pop(0)
            self.start_download(item)
    
    def start_download(self, item):
        item.status = "Downloading"
        item.start_time = datetime.now()
        self.active_downloads[item.id] = item
        self.download_started.emit(item.id)
    
    def update_progress(self, item_id, progress, status=""):
        if item_id in self.active_downloads:
            item = self.active_downloads[item_id]
            item.progress = progress
            if status:
                item.status = status
            self.download_progress.emit(item_id, progress, status)
    
    def finish_download(self, item_id, success):
        if item_id in self.active_downloads:
            item = self.active_downloads[item_id]
            item.end_time = datetime.now()
            item.status = "Completed" if success else "Failed"
            item.progress = 100 if success else item.progress
            
            self.download_finished.emit(item_id, success)
            del self.active_downloads[item_id]
            
            self.process_queue()
    
    def get_queue_items(self):
        return self.queue.copy()
    
    def get_active_items(self):
        return list(self.active_downloads.values())
    
    def remove_from_queue(self, item_id):
        self.queue = [item for item in self.queue if item.id != item_id]
    
    def cancel_download(self, item_id):
        if item_id in self.active_downloads:
            item = self.active_downloads[item_id]
            if item.process and item.process.state() == QProcess.ProcessState.Running:
                item.process.kill()
            self.finish_download(item_id, False)

class VideoDownloader(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VDM (Video Download Manager)")
        self.setWindowIcon(QIcon("Dependencies/VDM_icon.ico"))
        self.setMinimumSize(1200, 800)

        # Paths
        self.Dependencies_path = "./Dependencies/"
        self.yt_dlp_path = self.Dependencies_path + "yt-dlp.exe"
        self.ffmpeg_path = self.Dependencies_path + "ffmpeg-8.0-full_build/bin/ffmpeg.exe"

        # State
        self.format_json = []
        self.video_info = {}
        self.show_best_mp4_highlight = True
        self.fetching_info = False
        self.fetching_search = False
        self.search_results = []
        self.current_search_query = ""
        self.info_buffer = ""

        # Download management
        self.download_manager = DownloadManager()
        self.download_history = DownloadHistory()
        self.setup_download_manager_connections()

        # Create shared console first
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.setMaximumHeight(150)
        self.console_output.setStyleSheet("background-color: #1e1e1e; color: #ffffff; font-family: Consolas, monospace;")

        # Tabs
        self.tabs = QTabWidget()
        self.main_tab = QWidget()
        self.queue_tab = QWidget()
        self.history_tab = QWidget()
        self.settings_tab = QWidget()
        self.tabs.addTab(self.main_tab, "Downloader")
        self.tabs.addTab(self.queue_tab, "Download Queue")
        self.tabs.addTab(self.history_tab, "Download History")
        self.tabs.addTab(self.settings_tab, "Settings")

        # Tab background
        self.tab_background = TabButtonBackground(self)

        # UI
        self.init_main_tab()
        self.init_queue_tab()
        self.init_history_tab()
        self.init_settings_tab()
        
        # Main layout with shared console
        root = QVBoxLayout()
        root.addWidget(self.tabs)
        
        # Add shared console at the bottom
        self.console_frame = QFrame()
        self.console_frame.setFrameStyle(QFrame.Shape.Box)
        self.console_frame.setMaximumHeight(200)
        self.console_frame.setSizePolicy(
            self.console_frame.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Preferred
        )

        console_layout = QVBoxLayout()
        console_header = QHBoxLayout()
        console_header.addWidget(QLabel("Console Output:"))
        clear_console_btn = QPushButton("Clear Console")
        clear_console_btn.clicked.connect(self.console_output.clear)
        console_header.addStretch()
        console_header.addWidget(clear_console_btn)
        console_layout.addLayout(console_header)
        console_layout.addWidget(self.console_output)
        self.console_frame.setLayout(console_layout)
        
        root.addWidget(self.console_frame)
        self.setLayout(root)

        # Processes
        self.init_processes()
        
        # Update timer for queue display
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_queue_display)
        self.update_timer.start(1000)

    def setup_download_manager_connections(self):
        self.download_manager.download_started.connect(self.on_download_started)
        self.download_manager.download_progress.connect(self.on_download_progress_update)
        self.download_manager.download_finished.connect(self.on_download_completed)

    def log_to_console(self, message):
        if self.console_output is not None:
            self.console_output.append(message.strip())
            scrollbar = self.console_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        else:
            print(f"Console not ready: {message.strip()}")

    def init_processes(self):
        self.proc_info = QProcess()
        self.proc_search = QProcess()

        self.proc_info.readyReadStandardOutput.connect(self.on_info_output)
        self.proc_info.readyReadStandardError.connect(self.on_info_error)
        self.proc_info.finished.connect(self.on_info_finished)

        self.proc_search.readyReadStandardOutput.connect(self.on_search_output)
        self.proc_search.readyReadStandardError.connect(self.on_search_error)
        self.proc_search.finished.connect(self.on_search_finished)

    def init_main_tab(self):
        layout = QVBoxLayout()

        # Search/URL input section
        search_group = QGroupBox("Search or Enter URL")
        search_layout = QVBoxLayout()
        
        # Input row with mode selection
        input_row = QHBoxLayout()
        self.input_mode = QComboBox()
        self.input_mode.addItems(["URL", "Search YouTube", "Search All Sites"])
        self.input_mode.setMaximumWidth(150)
        self.input_mode.currentTextChanged.connect(self.on_input_mode_changed)
        
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter video URL (YouTube, TikTok, Instagram, Facebook, etc.)")
        
        self.fetch_button = QPushButton("Fetch Formats")
        self.fetch_button.clicked.connect(self.fetch_formats)
        
        input_row.addWidget(self.input_mode)
        input_row.addWidget(self.url_input)
        input_row.addWidget(self.fetch_button)
        
        # Search options (hidden by default)
        self.search_options = QWidget()
        search_options_layout = QHBoxLayout()
        search_options_layout.addWidget(QLabel("Results:"))
        self.search_limit = QSpinBox()
        self.search_limit.setRange(1, 50)
        self.search_limit.setValue(10)
        self.search_limit.setMaximumWidth(60)
        search_options_layout.addWidget(self.search_limit)
        search_options_layout.addStretch()
        self.search_options.setLayout(search_options_layout)
        self.search_options.setVisible(False)
        
        # Search results table (hidden by default)
        self.search_table = QTableWidget()
        self.search_table.setColumnCount(4)
        self.search_table.setHorizontalHeaderLabels(["Title", "Uploader", "Duration", "View Count"])
        search_header = self.search_table.horizontalHeader()
        search_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        search_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        search_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        search_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.search_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.search_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.search_table.setAlternatingRowColors(True)
        self.search_table.setMaximumHeight(200)
        self.search_table.setVisible(False)
        self.search_table.cellDoubleClicked.connect(self.on_search_result_selected)
        
        # Select from search button
        self.select_search_btn = QPushButton("Select from Search Results")
        self.select_search_btn.clicked.connect(self.on_search_result_selected)
        self.select_search_btn.setVisible(False)
        
        search_layout.addLayout(input_row)
        search_layout.addWidget(self.search_options)
        search_layout.addWidget(self.search_table)
        search_layout.addWidget(self.select_search_btn)
        search_group.setLayout(search_layout)

        # Filter
        filter_row = QHBoxLayout()
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter by resolution, type, codec, itag…")
        self.filter_input.textChanged.connect(self.apply_filter)
        filter_row.addWidget(QLabel("Filter:"))
        filter_row.addWidget(self.filter_input)

        # Format table
        self.format_table = QTableWidget()
        self.format_table.setColumnCount(10)
        self.format_table.setHorizontalHeaderLabels(
            ["Itag", "Ext", "Resolution", "Type", "VCodec", "ACodec", "FPS", "Bitrate", "Size", "Note"]
        )
        header = self.format_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.format_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.format_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.format_table.setShowGrid(False)
        self.format_table.setAlternatingRowColors(True)
        self.format_table.setStyleSheet("""
            QTableWidget::item:selected {
                background-color: #4a90e2;
                color: white;
                font-weight: bold;
            }
        """)
        self.format_table.cellDoubleClicked.connect(self.on_double_click_row)

        # Buttons
        actions_row = QHBoxLayout()
        self.btn_add_selected = QPushButton("Add Selected to Queue")
        self.btn_add_best = QPushButton("Add Best Quality to Queue")
        self.btn_add_selected.clicked.connect(self.add_selected_to_queue)
        self.btn_add_best.clicked.connect(self.add_best_to_queue)
        actions_row.addWidget(self.btn_add_selected)
        actions_row.addWidget(self.btn_add_best)

        layout.addWidget(search_group)
        layout.addLayout(filter_row)
        layout.addWidget(self.format_table)
        layout.addLayout(actions_row)
        
        self.main_tab.setLayout(layout)

    def init_queue_tab(self):
        layout = QVBoxLayout()
        
        # Queue controls
        controls_row = QHBoxLayout()
        self.queue_status_label = QLabel("Queue Status: 0 queued, 0 downloading")
        self.pause_all_btn = QPushButton("Pause All")
        self.cancel_all_btn = QPushButton("Cancel All")
        self.clear_completed_btn = QPushButton("Clear Completed")
        
        self.pause_all_btn.clicked.connect(self.pause_all_downloads)
        self.cancel_all_btn.clicked.connect(self.cancel_all_downloads)
        self.clear_completed_btn.clicked.connect(self.clear_completed_downloads)
        
        controls_row.addWidget(self.queue_status_label)
        controls_row.addStretch()
        controls_row.addWidget(self.pause_all_btn)
        controls_row.addWidget(self.cancel_all_btn)
        controls_row.addWidget(self.clear_completed_btn)
        
        # Queue table
        self.queue_table = QTableWidget()
        self.queue_table.setColumnCount(8)
        self.queue_table.setHorizontalHeaderLabels([
            "Title", "Format", "Status", "Progress", "Speed", "Size", "Added", "Actions"
        ])
        
        queue_header = self.queue_table.horizontalHeader()
        queue_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        queue_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        queue_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        queue_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        queue_header.resizeSection(3, 120)
        queue_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        queue_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        queue_header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        queue_header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        queue_header.resizeSection(7, 100)
        
        self.queue_table.setAlternatingRowColors(True)
        self.queue_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        layout.addLayout(controls_row)
        layout.addWidget(self.queue_table)
        self.queue_tab.setLayout(layout)

    def init_history_tab(self):
        layout = QVBoxLayout()
        
        # History controls
        controls_row = QHBoxLayout()
        self.history_status_label = QLabel(f"Total downloads: {len(self.download_history.history)}")
        self.clear_history_btn = QPushButton("Clear History")
        self.export_history_btn = QPushButton("Export History")
        
        self.clear_history_btn.clicked.connect(self.clear_history)
        self.export_history_btn.clicked.connect(self.export_history)
        
        controls_row.addWidget(self.history_status_label)
        controls_row.addStretch()
        controls_row.addWidget(self.export_history_btn)
        controls_row.addWidget(self.clear_history_btn)
        
        # History table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "Title", "Format", "Status", "File Size", "Date Added", "Duration", "Path"
        ])
        
        history_header = self.history_table.horizontalHeader()
        history_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        history_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        history_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        
        # Context menu for history
        self.history_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_table.customContextMenuRequested.connect(self.show_history_context_menu)
        
        self.populate_history_table()
        
        layout.addLayout(controls_row)
        layout.addWidget(self.history_table)
        self.history_tab.setLayout(layout)

    def init_settings_tab(self):
        layout = QVBoxLayout()
        
        # Download settings
        download_group = QGroupBox("Download Settings")
        download_layout = QVBoxLayout()
        
        concurrent_row = QHBoxLayout()
        concurrent_row.addWidget(QLabel("Max Concurrent Downloads:"))
        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self.concurrent_spin.setValue(self.download_manager.max_concurrent)
        self.concurrent_spin.valueChanged.connect(self.update_concurrent_downloads)
        concurrent_row.addWidget(self.concurrent_spin)
        concurrent_row.addStretch()
        
        self.highlight_checkbox = QCheckBox("Show Best MP4 Highlight")
        self.highlight_checkbox.setChecked(True)
        self.highlight_checkbox.stateChanged.connect(self.toggle_highlight)
        
        download_layout.addLayout(concurrent_row)
        download_layout.addWidget(self.highlight_checkbox)
        download_group.setLayout(download_layout)

        # Console toggle
        self.console_checkbox = QCheckBox("Show Console")
        self.console_checkbox.setChecked(True)
        self.console_checkbox.stateChanged.connect(self.toggle_console)

        layout.addWidget(download_group)
        layout.addWidget(self.console_checkbox)
        layout.addStretch(1)
        self.settings_tab.setLayout(layout)

    def on_input_mode_changed(self, mode):
        is_search = mode != "URL"
        self.search_options.setVisible(is_search)
        
        if mode == "URL":
            self.url_input.setPlaceholderText("Enter video URL (YouTube, TikTok, Instagram, Facebook, etc.)")
            self.fetch_button.setText("Fetch Formats")
        elif mode == "Search YouTube":
            self.url_input.setPlaceholderText("Search YouTube videos...")
            self.fetch_button.setText("Search")
        elif mode == "Search All Sites":
            self.url_input.setPlaceholderText("Search videos across all supported sites...")
            self.fetch_button.setText("Search")
        
        self.search_table.setVisible(False)
        self.select_search_btn.setVisible(False)
        self.format_table.setRowCount(0)

    def perform_search(self, query, search_type):
        self.console_output.clear()
        self.search_results = []
        self.current_search_query = query
        self.fetching_search = True
        
        # Clear search table and show loading row
        self.search_table.setRowCount(1)
        self.search_table.setColumnCount(4)
        
        # Create loading row
        loading_item = QTableWidgetItem("Fetching results...")
        loading_item.setBackground(Qt.GlobalColor.darkBlue)
        loading_item.setForeground(Qt.GlobalColor.white)
        font = loading_item.font()
        font.setBold(True)
        loading_item.setFont(font)
        
        self.search_table.setItem(0, 0, loading_item)
        for col in range(1, 4):
            self.search_table.setItem(0, col, QTableWidgetItem(""))
        
        # Make search table visible to show loading state
        self.search_table.setVisible(True)
        self.select_search_btn.setVisible(False)
        
        # Disable search button while loading
        self.fetch_button.setEnabled(False)
        
        # Build search command
        limit = self.search_limit.value()
        if search_type == "Search YouTube":
            search_query = f"ytsearch{limit}:{query}"
        else:
            search_query = f"ytsearch{limit}:{query}"
        
        args = [
            "--flat-playlist",
            "--dump-json",
            search_query
        ]
        
        self.log_to_console(f"[SEARCH] Command: {self.yt_dlp_path} {' '.join(args)}")
        self.proc_search.start(self.yt_dlp_path, args)

    def on_search_output(self):
        output = str(self.proc_search.readAllStandardOutput(), "utf-8")
        self.log_to_console(f"[SEARCH] {output}")
        
        for line in output.strip().split('\n'):
            if line.strip():
                try:
                    result = json.loads(line)
                    if result.get('_type') != 'playlist':
                        self.search_results.append(result)
                except json.JSONDecodeError:
                    continue

    def on_search_error(self):
        error = str(self.proc_search.readAllStandardError(), "utf-8")
        if error.strip():
            self.log_to_console(f"[SEARCH ERROR] {error}")

    def on_search_finished(self):
        self.fetching_search = False
        self.fetch_button.setEnabled(True)
        
        if self.search_results:
            self.populate_search_results()
        else:
            self.search_table.setRowCount(1)
            error_item = QTableWidgetItem("No search results found")
            error_item.setBackground(Qt.GlobalColor.darkRed)
            error_item.setForeground(Qt.GlobalColor.white)
            font = error_item.font()
            font.setBold(True)
            error_item.setFont(font)
            self.search_table.setItem(0, 0, error_item)
            for col in range(1, 4):
                self.search_table.setItem(0, col, QTableWidgetItem(""))
            
            self.log_to_console("[SEARCH] No search results found")

    def populate_search_results(self):
        self.search_table.setRowCount(len(self.search_results))
        
        for idx, result in enumerate(self.search_results):
            title = result.get('title', 'Unknown Title')
            uploader = result.get('uploader', result.get('channel', 'Unknown'))
            duration = self.format_duration(result.get('duration', 0))
            view_count = self.format_view_count(result.get('view_count', 0))
            
            self.search_table.setItem(idx, 0, QTableWidgetItem(title))
            self.search_table.setItem(idx, 1, QTableWidgetItem(uploader))
            self.search_table.setItem(idx, 2, QTableWidgetItem(duration))
            self.search_table.setItem(idx, 3, QTableWidgetItem(view_count))
        
        self.search_table.setVisible(True)
        self.select_search_btn.setVisible(True)

    def on_search_result_selected(self, row=None, col=None):
        if row is None:
            selected_rows = self.search_table.selectionModel().selectedRows()
            if not selected_rows:
                QMessageBox.warning(self, "No Selection", "Please select a video from the search results.")
                return
            row = selected_rows[0].row()
        
        if 0 <= row < len(self.search_results):
            selected_result = self.search_results[row]
            video_url = selected_result.get('webpage_url') or selected_result.get('url')
            
            if video_url:
                self.input_mode.setCurrentText("URL")
                self.url_input.setText(video_url)
                
                self.search_table.setVisible(False)
                self.select_search_btn.setVisible(False)
                
                self.format_table.setRowCount(0)
                
                self.fetch_formats()
            else:
                QMessageBox.warning(self, "Error", "Could not get URL for selected video.")

    def format_duration(self, seconds):
        if not seconds:
            return "Unknown"
        seconds = int(seconds)
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes:02d}:{secs:02d}"

    def format_view_count(self, count):
        if not count:
            return "Unknown"
        if count >= 1000000:
            return f"{count/1000000:.1f}M views"
        elif count >= 1000:
            return f"{count/1000:.1f}K views"
        else:
            return f"{count} views"

    def toggle_highlight(self, state):
        self.show_best_mp4_highlight = state == Qt.CheckState.Checked.value
        if self.format_json:
            self.populate_table()

    def update_concurrent_downloads(self, value):
        self.download_manager.max_concurrent = value
        self.download_manager.process_queue()

    def toggle_console(self, state):
        is_visible = state == Qt.CheckState.Checked.value
        self.console_frame.setVisible(is_visible)

    def _show_format_error(self, error_message):
        """Helper method to display error in the format table"""
        self.format_table.setRowCount(1)
        error_item = QTableWidgetItem(error_message)
        error_item.setBackground(Qt.GlobalColor.red)
        error_item.setForeground(Qt.GlobalColor.white)
        font = error_item.font()
        font.setBold(True)
        error_item.setFont(font)
        self.format_table.setItem(0, 0, error_item)
        for col in range(1, 10):
            self.format_table.setItem(0, col, QTableWidgetItem(""))

    def fetch_formats(self):
        input_text = self.url_input.text().strip()
        if not input_text:
            return
        
        mode = self.input_mode.currentText()
        
        if mode != "URL":
            self.perform_search(input_text, mode)
            return
        
        url = input_text
        self.console_output.clear()
        
        self.format_json = []
        self.video_info = {}
        
        self.format_table.setRowCount(1)
        self.format_table.setColumnCount(10)
        
        loading_item = QTableWidgetItem("Fetching formats...")
        loading_item.setBackground(Qt.GlobalColor.darkBlue)
        loading_item.setForeground(Qt.GlobalColor.white)
        font = loading_item.font()
        font.setBold(True)
        loading_item.setFont(font)
        
        self.format_table.setItem(0, 0, loading_item)
        for col in range(1, 10):
            self.format_table.setItem(0, col, QTableWidgetItem(""))
        
        self.btn_add_selected.setEnabled(False)
        self.btn_add_best.setEnabled(False)

        self.fetching_info = True
        self.info_buffer = ""
        
        if not os.path.exists(self.yt_dlp_path):
            self.log_to_console(f"[ERROR] yt-dlp not found at: {self.yt_dlp_path}")
            self._show_format_error("yt-dlp executable not found")
            self.btn_add_selected.setEnabled(True)
            self.btn_add_best.setEnabled(True)
            return
        
        args = ["-J", "--no-warnings", url]
        self.log_to_console(f"[INFO] Starting yt-dlp with command: {self.yt_dlp_path} {' '.join(args)}")
        
        self.proc_info.start(self.yt_dlp_path, args)

    def on_info_output(self):
        chunk = str(self.proc_info.readAllStandardOutput(), "utf-8")
        if chunk:
            self.info_buffer += chunk
            self.log_to_console(f"[INFO] {chunk}")

        if not self.fetching_info:
            return

        buf = self.info_buffer.strip()
        if not buf:
            return

        if buf.startswith("{"):
            brace_count = 0
            last_complete_pos = -1
            
            for i, char in enumerate(buf):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        last_complete_pos = i
                        break
            
            if last_complete_pos != -1:
                json_str = buf[:last_complete_pos + 1]
                try:
                    info = json.loads(json_str)
                    self.fetching_info = False
                    self.info_buffer = ""
                    if info is not None:
                        self.video_info = info
                        self.format_json = info.get("formats", [])
                        if self.format_json:
                            self.populate_table()
                            self.log_to_console(f"[INFO] Successfully parsed {len(self.format_json)} formats")
                        else:
                            self.log_to_console("[WARNING] No formats found in video info")
                            self._show_format_error("No formats available for this video")
                        
                        self.btn_add_selected.setEnabled(True)
                        self.btn_add_best.setEnabled(True)
                        return
                except json.JSONDecodeError as e:
                    self.log_to_console(f"[DEBUG] JSON parse failed, waiting for more data: {e}")
                    return

    def on_info_error(self):
        error = str(self.proc_info.readAllStandardError(), "utf-8")
        if error.strip():
            self.log_to_console(f"[ERROR] {error}")

    def on_info_finished(self, exit_code):
        self.fetching_info = False
        
        self.btn_add_selected.setEnabled(True)
        self.btn_add_best.setEnabled(True)
        
        self.log_to_console(f"[INFO] Process finished with exit code: {exit_code}")
        
        if self.format_json:
            self.log_to_console(f"[INFO] Formats already processed successfully")
            self.info_buffer = ""
            return
        
        buf = self.info_buffer.strip()
        
        if exit_code != 0:
            error_msg = "Failed to fetch formats"
            if "ERROR:" in buf:
                lines = buf.split('\n')
                for line in lines:
                    if "ERROR:" in line:
                        error_msg = line.strip()
                        break
            elif "WARNING:" in buf and "Video unavailable" in buf:
                error_msg = "Video unavailable or private"
            elif not buf:
                error_msg = "No output received from yt-dlp"
            
            self.log_to_console(f"[ERROR] {error_msg}")
            self._show_format_error(error_msg)
            self.info_buffer = ""
            return
        
        if not buf:
            self.log_to_console("[ERROR] Process finished successfully but no data received")
            self._show_format_error("No format data received")
            return

        try:
            lines = buf.split('\n')
            json_line = None
            
            for line in lines:
                line = line.strip()
                if line.startswith('{') and line.endswith('}'):
                    json_line = line
                    break
            
            if json_line:
                info = json.loads(json_line)
                self.video_info = info
                self.format_json = info.get("formats", [])
                if self.format_json:
                    self.populate_table()
                    self.log_to_console(f"[INFO] Successfully parsed {len(self.format_json)} formats")
                else:
                    self.log_to_console("[WARNING] No formats found in video info")
                    self._show_format_error("No formats available for this video")
            else:
                info = json.loads(buf)
                self.video_info = info
                self.format_json = info.get("formats", [])
                if self.format_json:
                    self.populate_table()
                else:
                    self._show_format_error("No formats available for this video")
                    
        except json.JSONDecodeError as e:
            self.log_to_console(f"[ERROR] Failed to parse JSON: {e}")
            self.log_to_console(f"[DEBUG] Buffer content: {buf[:500]}...")
            self._show_format_error("Failed to parse format data")
        
        self.info_buffer = ""

    def add_selected_to_queue(self):
        if not self.format_json:
            QMessageBox.warning(self, "No Formats", "Please fetch video formats first.")
            return
        
        rows = self.format_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "No Selection", "Please select a format from the table.")
            return
        
        row = rows[0].row()
        itag = self.format_table.item(row, 0).text()
        fmt = next((f for f in self.format_json if str(f.get("format_id", "")) == itag), None)
        
        if not fmt:
            QMessageBox.warning(self, "Format Error", "Selected format not found.")
            return
        
        self._add_format_to_queue(fmt, "selected")

    def add_best_to_queue(self):
        if not self.format_json:
            QMessageBox.warning(self, "No Formats", "Please fetch video formats first.")
            return
        
        self._add_format_to_queue(None, "best")

    def _add_format_to_queue(self, fmt, format_type):
        title = self.video_info.get("title", "Unknown Video")
        url = self.url_input.text().strip()
        
        if format_type == "selected" and fmt:
            format_id = str(fmt.get("format_id", ""))
            is_audio_only = fmt.get("vcodec") == "none" or fmt.get("vcodec") is None
            original_ext = fmt.get("ext", "mkv")
            
            if is_audio_only:
                default_name = f"{title}.{original_ext}"
                file_filter = f"Audio File (*.{original_ext})"
            else:
                default_name = f"{title}.mkv"
                file_filter = "Matroska Video (*.mkv)"
        else:
            format_id = "best"
            default_name = f"{title}.mkv"
            file_filter = "Matroska Video (*.mkv)"
        
        default_name = re.sub(r'[<>:"/\\|?*]', '_', default_name)
        
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save File As",
            str(Path.home() / default_name),
            file_filter
        )
        
        if not save_path:
            return
        
        download_item = DownloadItem(
            url=url,
            format_id=format_id,
            format_type=format_type,
            output_path=save_path,
            title=title
        )
        
        self.download_manager.add_to_queue(download_item)
        self.log_to_console(f"[QUEUE] Added to queue: {title}")
        
        self.tabs.setCurrentIndex(1)

    def on_download_started(self, item_id):
        item = self.download_manager.active_downloads.get(item_id)
        if item:
            self.log_to_console(f"[DOWNLOAD] Started: {item.title}")
            self._create_download_process(item)

    def _create_download_process(self, item):
        process = QProcess()
        item.process = process
        
        process.readyReadStandardOutput.connect(lambda: self._on_process_output(item.id))
        process.readyReadStandardError.connect(lambda: self._on_process_error(item.id))
        process.finished.connect(lambda: self._on_process_finished(item.id))
        
        if item.format_type == "selected":
            fmt = None
            if hasattr(self, 'format_json'):
                fmt = next((f for f in self.format_json if str(f.get("format_id", "")) == item.format_id), None)
            
            if fmt and (fmt.get("acodec") == "none" or fmt.get("acodec") is None):
                format_selector = f"{item.format_id}+bestaudio"
            else:
                format_selector = item.format_id
        else:
            format_selector = "bestvideo+bestaudio/best"
        
        args = [
            "-f", format_selector,
            item.url,
            "--newline",
            "-o", item.output_path,
            "--force-overwrites",
            "--no-warnings",
            "--embed-metadata",
            "--ignore-errors",
            "--ffmpeg-location", self.ffmpeg_path
        ]
        
        if not item.output_path.lower().endswith(('.mp3', '.m4a', '.wav', '.flac')):
            args.extend(["--merge-output-format", "mkv"])
        
        self.log_to_console(f"[DOWNLOAD] Command: {self.yt_dlp_path} {' '.join(args)}")
        process.start(self.yt_dlp_path, args)

    def _on_process_output(self, item_id):
        item = self.download_manager.active_downloads.get(item_id)
        if not item or not item.process:
            return
        
        output = str(item.process.readAllStandardOutput(), "utf-8")
        if output.strip():
            self.log_to_console(f"[{item_id}] {output}")
        
        lines = output.splitlines()
        for line in lines:
            m = re.search(r"\[download\]\s+(\d{1,3}(?:\.\d+)?)%", line)
            if m:
                progress = int(float(m.group(1)))
                self.download_manager.update_progress(item_id, progress)
            
            speed_match = re.search(r"\[download\]\s+\d+\.\d+%\s+of\s+[^\s]+\s+at\s+([^\s]+)", line)
            if speed_match:
                item.download_speed = speed_match.group(1)
            
            size_match = re.search(r"\[download\]\s+\d+\.\d+%\s+of\s+([^\s]+)", line)
            if size_match:
                item.file_size = size_match.group(1)
            
            if "Merging formats into" in line or "[Merger]" in line:
                self.download_manager.update_progress(item_id, item.progress, "Merging...")
            elif "Deleting original file" in line:
                self.download_manager.update_progress(item_id, item.progress, "Cleaning up...")
            elif "[ffmpeg]" in line and ("Converting" in line or "Merging" in line):
                self.download_manager.update_progress(item_id, item.progress, "Processing...")

    def _on_process_error(self, item_id):
        item = self.download_manager.active_downloads.get(item_id)
        if not item or not item.process:
            return
        
        error = str(item.process.readAllStandardError(), "utf-8")
        if error.strip():
            self.log_to_console(f"[{item_id} ERROR] {error}")

    def _on_process_finished(self, item_id):
        item = self.download_manager.active_downloads.get(item_id)
        if not item or not item.process:
            return
        
        exit_code = item.process.exitCode()
        success = exit_code == 0
        
        self.log_to_console(f"[{item_id}] Finished with exit code: {exit_code}")
        self.download_manager.finish_download(item_id, success)

    def on_download_progress_update(self, item_id, progress, status):
        pass

    def on_download_completed(self, item_id, success):
        item = self.download_manager.active_downloads.get(item_id) or \
               next((i for i in self.download_manager.get_active_items() if i.id == item_id), None)
        
        if item:
            self.log_to_console(f"[DOWNLOAD] {'Completed' if success else 'Failed'}: {item.title}")
            
            self.download_history.add_item(item)
            self.populate_history_table()
            self.update_history_status()

    def update_queue_display(self):
        all_items = self.download_manager.get_queue_items() + self.download_manager.get_active_items()
        
        self.queue_table.setRowCount(len(all_items))
        
        for idx, item in enumerate(all_items):
            self.queue_table.setItem(idx, 0, QTableWidgetItem(item.title[:50] + "..." if len(item.title) > 50 else item.title))
            
            format_text = item.format_type.title()
            if item.format_id != "best":
                format_text += f" ({item.format_id})"
            self.queue_table.setItem(idx, 1, QTableWidgetItem(format_text))
            
            status_item = QTableWidgetItem(item.status)
            if item.status == "Completed":
                status_item.setBackground(Qt.GlobalColor.green)
            elif item.status == "Failed":
                status_item.setBackground(Qt.GlobalColor.red)
            elif item.status == "Downloading":
                status_item.setBackground(Qt.GlobalColor.blue)
            self.queue_table.setItem(idx, 2, status_item)
            
            progress_bar = QProgressBar()
            progress_bar.setValue(item.progress)
            progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.queue_table.setCellWidget(idx, 3, progress_bar)
            
            self.queue_table.setItem(idx, 4, QTableWidgetItem(getattr(item, 'download_speed', '')))
            self.queue_table.setItem(idx, 5, QTableWidgetItem(getattr(item, 'file_size', '')))
            
            added_time = item.added_time.strftime("%H:%M:%S")
            self.queue_table.setItem(idx, 6, QTableWidgetItem(added_time))
            
            if item.status in ["Queued", "Downloading"]:
                cancel_btn = QPushButton("Cancel")
                cancel_btn.clicked.connect(lambda checked, i=item.id: self.cancel_download(i))
                self.queue_table.setCellWidget(idx, 7, cancel_btn)
            else:
                self.queue_table.setItem(idx, 7, QTableWidgetItem(""))
        
        queued_count = len(self.download_manager.get_queue_items())
        active_count = len(self.download_manager.get_active_items())
        self.queue_status_label.setText(f"Queue Status: {queued_count} queued, {active_count} downloading")

    def cancel_download(self, item_id):
        self.download_manager.cancel_download(item_id)
        self.log_to_console(f"[QUEUE] Cancelled download: {item_id}")

    def pause_all_downloads(self):
        for item_id in list(self.download_manager.active_downloads.keys()):
            self.download_manager.cancel_download(item_id)
        self.log_to_console("[QUEUE] Paused all downloads")

    def cancel_all_downloads(self):
        for item_id in list(self.download_manager.active_downloads.keys()):
            self.download_manager.cancel_download(item_id)
        
        self.download_manager.queue.clear()
        self.log_to_console("[QUEUE] Cancelled all downloads and cleared queue")

    def clear_completed_downloads(self):
        self.log_to_console("[QUEUE] Cleared completed downloads from view")

    def populate_history_table(self):
        self.history_table.setRowCount(len(self.download_history.history))
        
        for idx, entry in enumerate(self.download_history.history):
            self.history_table.setItem(idx, 0, QTableWidgetItem(entry.get("title", "Unknown")))
            
            format_text = entry.get("format_type", "").title()
            if entry.get("format_id") and entry.get("format_id") != "best":
                format_text += f" ({entry.get('format_id')})"
            self.history_table.setItem(idx, 1, QTableWidgetItem(format_text))
            
            status = entry.get("status", "Unknown")
            status_item = QTableWidgetItem(status)
            if status == "Completed":
                status_item.setBackground(Qt.GlobalColor.darkGreen)
            elif status == "Failed":
                status_item.setBackground(Qt.GlobalColor.darkRed)
            self.history_table.setItem(idx, 2, status_item)
            
            self.history_table.setItem(idx, 3, QTableWidgetItem(entry.get("file_size", "")))
            
            added_time = entry.get("added_time", "")
            if added_time:
                try:
                    dt = datetime.fromisoformat(added_time)
                    formatted_time = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    formatted_time = added_time
            else:
                formatted_time = ""
            self.history_table.setItem(idx, 4, QTableWidgetItem(formatted_time))
            
            duration = ""
            if entry.get("start_time") and entry.get("end_time"):
                try:
                    start = datetime.fromisoformat(entry["start_time"])
                    end = datetime.fromisoformat(entry["end_time"])
                    duration_seconds = (end - start).total_seconds()
                    duration = f"{int(duration_seconds // 60)}m {int(duration_seconds % 60)}s"
                except:
                    duration = ""
            self.history_table.setItem(idx, 5, QTableWidgetItem(duration))
            
            self.history_table.setItem(idx, 6, QTableWidgetItem(entry.get("output_path", "")))

    def update_history_status(self):
        total_downloads = len(self.download_history.history)
        completed = sum(1 for entry in self.download_history.history if entry.get("status") == "Completed")
        self.history_status_label.setText(f"Total downloads: {total_downloads} ({completed} completed)")

    def clear_history(self):
        reply = QMessageBox.question(
            self, "Clear History", 
            "Are you sure you want to clear all download history?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.download_history.history.clear()
            self.download_history.save_history()
            self.populate_history_table()
            self.update_history_status()

    def export_history(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export History", 
            str(Path.home() / "download_history.json"),
            "JSON Files (*.json)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.download_history.history, f, indent=2, ensure_ascii=False, default=str)
                QMessageBox.information(self, "Export Complete", f"History exported to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export history: {str(e)}")

    def show_history_context_menu(self, position):
        pass

    def on_double_click_row(self, row, col):
        self.add_selected_to_queue()

    def populate_table(self):
        self.format_table.setRowCount(0)
        best_row = None
        best_fmt = None

        if not self.format_json:
            return

        single_format = len(self.format_json) == 1

        for idx, fmt in enumerate(self.format_json):
            row = self.format_table.rowCount()
            self.format_table.insertRow(row)
            itag = str(fmt.get("format_id", idx+1))
            ext = fmt.get("ext", "mkv")
            width = fmt.get("width")
            height = fmt.get("height")
            resolution = f"{width}x{height}" if width and height else ""
            vcodec = fmt.get("vcodec") or ""
            acodec = fmt.get("acodec") or ""
            typ = "Audio" if vcodec == "none" else "Video"
            fps = fmt.get("fps")
            tbr = fmt.get("tbr")
            size_bytes = fmt.get("filesize") or fmt.get("filesize_approx")
            size = f"{round(size_bytes/(1024*1024), 2)} MiB" if size_bytes else ""
            note = fmt.get("format_note", "")

            ext_display = ext if typ == "Audio" else "mkv"
            values = [itag, ext_display, resolution, typ, vcodec, acodec, str(fps or ""), str(tbr or ""), size, note]
            for c, v in enumerate(values):
                self.format_table.setItem(row, c, QTableWidgetItem(v))

            if "Audio" in typ:
                for c in range(self.format_table.columnCount()):
                    item = self.format_table.item(row, c)
                    item.setBackground(Qt.GlobalColor.lightGray)

            if "Video" in typ and ext in ["mp4","webm"]:
                if not best_fmt:
                    best_fmt = fmt
                    best_row = row
                else:
                    def key(f):
                        return (f.get("height") or 0, f.get("fps") or 0, f.get("tbr") or 0)
                    if key(fmt) > key(best_fmt):
                        best_fmt = fmt
                        best_row = row

        if self.show_best_mp4_highlight and best_row is not None and not single_format:
            for c in range(self.format_table.columnCount()):
                item = self.format_table.item(best_row, c)
                if item:
                    item.setBackground(Qt.GlobalColor.darkGreen)
                    item.setForeground(Qt.GlobalColor.white)
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)

        self.format_table.setVisible(not single_format)
        self.btn_add_selected.setVisible(not single_format)

    def apply_filter(self):
        needle = self.filter_input.text().lower()
        for r in range(self.format_table.rowCount()):
            show = False
            for c in range(self.format_table.columnCount()):
                it = self.format_table.item(r, c)
                if it and needle in it.text().lower():
                    show = True
                    break
            self.format_table.setRowHidden(r, not show)

    def closeEvent(self, event):
        active_downloads = len(self.download_manager.get_active_items())
        running_info = self.proc_info.state() == QProcess.ProcessState.Running
        running_search = self.proc_search.state() == QProcess.ProcessState.Running
        
        if active_downloads > 0 or running_info or running_search:
            reply = QMessageBox.question(
                self,
                "Process in Progress",
                f"There are {active_downloads} downloads running and other processes active. "
                "Closing now may interrupt them.\nDo you really want to exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.cancel_all_downloads()
                if running_info: 
                    self.proc_info.kill()
                if running_search: 
                    self.proc_search.kill()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def debug_yt_dlp(self, url):
        """Test yt-dlp directly to see what's happening"""
        import subprocess
        try:
            result = subprocess.run([self.yt_dlp_path, "-J", url], 
                                  capture_output=True, text=True, timeout=30)
            self.log_to_console(f"Debug - Exit code: {result.returncode}")
            self.log_to_console(f"Debug - Stdout: {result.stdout[:500]}...")
            self.log_to_console(f"Debug - Stderr: {result.stderr[:500]}...")
        except Exception as e:
            self.log_to_console(f"Debug error: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = VideoDownloader()
    win.show()
    sys.exit(app.exec())