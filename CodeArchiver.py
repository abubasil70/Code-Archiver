import sys
import os
import sqlite3
import ctypes
import configparser
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, 
                             QHBoxLayout, QWidget, QFileDialog, QLabel, QListWidget, 
                             QLineEdit, QDialog, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QTextEdit, QCheckBox, QMessageBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

# Abu Basil's approved Windows message box
def msgbox(message, title="Code Archiver"):
    ctypes.windll.user32.MessageBoxW(0, str(message), title, 0)

class SelectionDialog(QDialog):
    """Initial setup dialog for selecting project files"""
    def __init__(self, files_list, title="Project Setup", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 450)
        layout = QVBoxLayout(self)
        
        label = QLabel("Select the files you want to track:")
        label.setFont(QFont("Segoe UI", 11))
        layout.addWidget(label)
        
        self.table = QTableWidget(len(files_list), 3)
        self.table.setHorizontalHeaderLabels(["Track", "File Path", "Reference Tag"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        
        self.rows = []
        for i, rel_path in enumerate(files_list):
            chk = QCheckBox()
            chk.setChecked(True)
            chk_widget = QWidget()
            chk_lay = QHBoxLayout(chk_widget)
            chk_lay.addWidget(chk)
            chk_lay.setAlignment(Qt.AlignCenter)
            chk_lay.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(i, 0, chk_widget)
            self.table.setItem(i, 1, QTableWidgetItem(rel_path))
            
            ref_input = QLineEdit()
            self.table.setCellWidget(i, 2, ref_input)
            self.rows.append((chk, rel_path, ref_input))
            
        layout.addWidget(self.table)
        btn = QPushButton("Start Tracking Selected Files")
        btn.clicked.connect(self.accept)
        layout.addWidget(btn)

    def get_selected(self):
        return [{'rel': r[1], 'old': r[2].text()} for r in self.rows if r[0].isChecked()]

class CodeManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.work_dir = ""
        self.db_path = ""
        self.settings_file = "settings.ini"
        self.current_file_id = None
        self.current_version_id = None
        self.text_exts = {'.py', '.pyw', '.sql', '.txt', '.php', '.ahk', '.html', '.css', '.js', '.json', '.md'}
        
        self.initUI()
        self.load_settings()

    def initUI(self):
        self.setWindowTitle('Code Archiver - Personal Version Control')
        self.setGeometry(100, 100, 1200, 800)
        self.setFont(QFont("Segoe UI", 10))
        
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        
        # --- Left: Explorer ---
        left_panel = QVBoxLayout()
        btn_open = QPushButton("📁 Open Project")
        btn_open.clicked.connect(self.select_project)
        left_panel.addWidget(btn_open)
        
        left_panel.addWidget(QLabel("Project Files:"))
        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self.load_history)
        left_panel.addWidget(self.file_list)
        
        self.btn_sync = QPushButton("🔄 Sync Project")
        self.btn_sync.setEnabled(False)
        self.btn_sync.clicked.connect(self.sync_project)
        left_panel.addWidget(self.btn_sync)
        
        main_layout.addLayout(left_panel, 1)
        
        # --- Middle: History ---
        mid_panel = QVBoxLayout()
        mid_panel.addWidget(QLabel("Version History:"))
        self.history_table = QTableWidget(0, 2)
        self.history_table.setHorizontalHeaderLabels(["Version Info", "Note"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.itemClicked.connect(self.view_version)
        mid_panel.addWidget(self.history_table)
        
        main_layout.addLayout(mid_panel, 2)
        
        # --- Right: Content & Actions ---
        right_panel = QVBoxLayout()
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        right_panel.addWidget(self.editor)
        
        note_box = QHBoxLayout()
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Edit version note...")
        note_box.addWidget(self.note_input)
        
        btn_save = QPushButton("💾 Save Changes")
        btn_save.clicked.connect(self.update_version)
        note_box.addWidget(btn_save)
        right_panel.addLayout(note_box)
        
        btn_restore = QPushButton("↩ Restore to Source File")
        btn_restore.clicked.connect(self.restore_file)
        right_panel.addWidget(btn_restore)
        
        btn_export = QPushButton("📤 Export Standalone File")
        btn_export.clicked.connect(self.export_version)
        right_panel.addWidget(btn_export)
        
        main_layout.addLayout(right_panel, 3)
        self.setCentralWidget(main_widget)

        # The "Fayka": Force Maximize using ctypes after initialization
        self.show()
        try:
            ctypes.windll.user32.ShowWindow(int(self.winId()), 3)
        except:
            pass

    # --- Persistence ---
    def load_settings(self):
        config = configparser.ConfigParser()
        if os.path.exists(self.settings_file):
            config.read(self.settings_file)
            path = config.get('Settings', 'LastPath', fallback="")
            if path and os.path.exists(path):
                self.setup_project(path)

    def save_settings(self, path):
        config = configparser.ConfigParser()
        config['Settings'] = {'LastPath': path}
        with open(self.settings_file, 'w') as f:
            config.write(f)

    # --- Project Management ---
    def select_project(self):
        path = QFileDialog.getExistingDirectory(self, "Select Folder")
        if path: self.setup_project(path)

    def setup_project(self, path):
        self.work_dir = path
        self.db_path = os.path.join(path, "code.db")
        self.save_settings(path)
        self.setWindowTitle(f"Code Archiver - {path}")
        
        if not os.path.exists(self.db_path):
            self.first_time_init()
        else:
            self.refresh_files()
        self.btn_sync.setEnabled(True)

    def first_time_init(self):
        files = []
        for r, _, fs in os.walk(self.work_dir):
            for f in fs:
                if os.path.splitext(f)[1].lower() in self.text_exts and f != "code.db":
                    files.append(os.path.relpath(os.path.join(r, f), self.work_dir))
        
        dlg = SelectionDialog(files, "Initialize Project", self)
        if dlg.exec_():
            selected = dlg.get_selected()
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, file_name TEXT, old_name TEXT, rel_path TEXT UNIQUE)")
            cur.execute("CREATE TABLE IF NOT EXISTS versions (id INTEGER PRIMARY KEY, file_id INTEGER, content TEXT, note TEXT, stamp TIMESTAMP)")
            
            for item in selected:
                cur.execute("INSERT INTO files (file_name, old_name, rel_path) VALUES (?, ?, ?)", 
                            (os.path.basename(item['rel']), item['old'], item['rel']))
                self.create_snapshot(cur, cur.lastrowid, item['rel'], "Initial Version")
            conn.commit()
            conn.close()
            self.refresh_files()

    def create_snapshot(self, cursor, f_id, rel, note):
        try:
            with open(os.path.join(self.work_dir, rel), 'r', encoding='utf-8') as f:
                cursor.execute("INSERT INTO versions (file_id, content, note, stamp) VALUES (?, ?, ?, ?)", 
                               (f_id, f.read(), note, datetime.now().isoformat()))
        except: pass

    def refresh_files(self):
        self.file_list.clear()
        conn = sqlite3.connect(self.db_path)
        for row in conn.execute("SELECT file_name FROM files"):
            self.file_list.addItem(row[0])
        conn.close()

    def sync_project(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        changed = 0
        for f_id, rel in cur.execute("SELECT id, rel_path FROM files").fetchall():
            path = os.path.join(self.work_dir, rel)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f: content = f.read()
                last = cur.execute("SELECT content FROM versions WHERE file_id=? ORDER BY stamp DESC LIMIT 1", (f_id,)).fetchone()
                if last and content != last[0]:
                    cur.execute("INSERT INTO versions (file_id, content, note, stamp) VALUES (?, ?, ?, ?)", 
                                (f_id, content, "Auto Sync", datetime.now().isoformat()))
                    changed += 1
        conn.commit()
        conn.close()
        msgbox(f"Sync finished. {changed} files updated.", "Sync Info")

    # --- History Management ---
    def load_history(self, item):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        res = cur.execute("SELECT id FROM files WHERE file_name=?", (item.text(),)).fetchone()
        if res:
            self.current_file_id = res[0]
            self.refresh_history_ui(cur)
        conn.close()

    def refresh_history_ui(self, cursor):
        """Relative numbering (Ver X) and hidden IDs"""
        self.history_table.setRowCount(0)
        data = cursor.execute("SELECT id, stamp, note FROM versions WHERE file_id=? ORDER BY stamp DESC", (self.current_file_id,)).fetchall()
        total = len(data)
        for i, (v_id, stamp, note) in enumerate(data):
            self.history_table.insertRow(i)
            try:
                dt = datetime.fromisoformat(stamp).strftime('%Y-%m-%d %H:%M')
            except: dt = stamp
            
            # Use relative version number (e.g., Ver 5, Ver 4...)
            rel_num = total - i
            display_item = QTableWidgetItem(f"Ver {rel_num} : {dt}")
            display_item.setData(Qt.UserRole, v_id) # Hidden ID
            
            self.history_table.setItem(i, 0, display_item)
            self.history_table.setItem(i, 1, QTableWidgetItem(str(note)))

    def view_version(self, item):
        self.current_version_id = self.history_table.item(item.row(), 0).data(Qt.UserRole)
        conn = sqlite3.connect(self.db_path)
        res = conn.execute("SELECT content, note FROM versions WHERE id=?", (self.current_version_id,)).fetchone()
        conn.close()
        if res:
            self.editor.setText(res[0])
            self.note_input.setText(res[1])

    def update_version(self):
        if not self.current_version_id: return
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("UPDATE versions SET content=?, note=? WHERE id=?", (self.editor.toPlainText(), self.note_input.text(), self.current_version_id))
        conn.commit()
        self.refresh_history_ui(cur)
        conn.close()
        msgbox("Archived version updated.", "Saved")

    def restore_file(self):
        if not self.current_version_id: return
        if QMessageBox.question(self, 'Confirm', 'Overwrite current file?') == QMessageBox.No: return
        conn = sqlite3.connect(self.db_path)
        content = conn.execute("SELECT content FROM versions WHERE id=?", (self.current_version_id,)).fetchone()[0]
        rel = conn.execute("SELECT rel_path FROM files WHERE id=?", (self.current_file_id,)).fetchone()[0]
        conn.close()
        with open(os.path.join(self.work_dir, rel), 'w', encoding='utf-8') as f: f.write(content)
        msgbox("Restored successfully.", "Success")

    def export_version(self):
        if not self.current_version_id: return
        conn = sqlite3.connect(self.db_path)
        content, stamp = conn.execute("SELECT content, stamp FROM versions WHERE id=?", (self.current_version_id,)).fetchone()
        name = conn.execute("SELECT file_name FROM files WHERE id=?", (self.current_file_id,)).fetchone()[0]
        conn.close()
        
        base, ext = os.path.splitext(name)
        suggested = f"{base}_Ver{self.current_version_id}{ext}"
        path, _ = QFileDialog.getSaveFileName(self, "Export File", suggested, "All Files (*.*)")
        if path:
            with open(path, 'w', encoding='utf-8') as f: f.write(content)
            #msgbox("Exported.", "Success")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = CodeManager()
    sys.exit(app.exec_())