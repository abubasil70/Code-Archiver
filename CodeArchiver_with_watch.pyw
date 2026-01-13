import sys, os, sqlite3, configparser, difflib
from datetime import datetime
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    Observer = None
    FileSystemEventHandler = None

class FileWatcher(FileSystemEventHandler):
    def __init__(self, callback_modified, callback_created):
        self.callback_modified = callback_modified
        self.callback_created = callback_created
    
    def on_modified(self, event):
        if not event.is_directory:
            self.callback_modified(event.src_path)
    
    def on_created(self, event):
        if not event.is_directory:
            self.callback_created(event.src_path)

class SelectionDialog(QDialog):
    def __init__(self, files_list, title="Project Setup", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 450)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(len(files_list), 3)
        self.table.setHorizontalHeaderLabels(["Track", "File Path", "Reference Tag"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.rows = []
        for i, rel_path in enumerate(files_list):
            chk = QCheckBox(); chk.setChecked(True)
            chk_widget = QWidget(); chk_lay = QHBoxLayout(chk_widget)
            chk_lay.addWidget(chk); chk_lay.setAlignment(Qt.AlignCenter); chk_lay.setContentsMargins(0,0,0,0)
            self.table.setCellWidget(i, 0, chk_widget)
            self.table.setItem(i, 1, QTableWidgetItem(rel_path))
            ref_input = QLineEdit()
            self.table.setCellWidget(i, 2, ref_input)
            self.rows.append((chk, rel_path, ref_input))
        layout.addWidget(self.table)
        btn = QPushButton("Start Tracking")
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
        
        # متغيرات المراقبة التلقائية
        self.auto_monitor_enabled = False
        self.observer = None
        self.file_contents_cache = {}  # تخزين محتوى الملفات السابقة
        
        self.initUI()
        self.load_settings()

    def initUI(self):
        self.setWindowTitle('Code Archiver')
        self.setGeometry(100, 100, 1100, 700)
        
        main_widget = QWidget()
        main_layout = QHBoxLayout(main_widget)
        
        left_panel = QVBoxLayout()
        btn_open = QPushButton("📂 Open Project")
        btn_open.clicked.connect(self.select_project)
        left_panel.addWidget(btn_open)
        
        btn_refresh = QPushButton("🔄 Refresh Files")
        btn_refresh.clicked.connect(self.refresh_and_update)
        left_panel.addWidget(btn_refresh)
        
        btn_delete_file = QPushButton("🗑️ Delete File Record")
        btn_delete_file.clicked.connect(self.delete_file_record)
        left_panel.addWidget(btn_delete_file)
        
        self.file_list = QListWidget()
        self.file_list.itemClicked.connect(self.load_history)
        self.file_list.itemDoubleClicked.connect(self.view_current_file)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_file_context_menu)
        left_panel.addWidget(QLabel("Files:"))
        left_panel.addWidget(self.file_list)
        
        self.btn_sync = QPushButton("🔄 Sync Now")
        self.btn_sync.setEnabled(False)
        self.btn_sync.clicked.connect(self.sync_project)
        left_panel.addWidget(self.btn_sync)
        
        self.btn_auto_monitor = QPushButton("⏱️ Auto Monitor OFF")
        self.btn_auto_monitor.setEnabled(False)
        self.btn_auto_monitor.setStyleSheet("background-color: #95a5a6; color: white; height: 35px;")
        self.btn_auto_monitor.clicked.connect(self.toggle_auto_monitor)
        left_panel.addWidget(self.btn_auto_monitor)

        main_layout.addLayout(left_panel, 1)
        
        # التاريخ والمحرر (من كودك الأصلي)
        mid_panel = QVBoxLayout()
        self.history_table = QTableWidget(0, 2)
        self.history_table.setHorizontalHeaderLabels(["Version", "Note"])
        self.history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.history_table.itemClicked.connect(self.view_version)
        mid_panel.addWidget(QLabel("History:"))
        mid_panel.addWidget(self.history_table)
        main_layout.addLayout(mid_panel, 2)
        
        right_panel = QVBoxLayout()
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Consolas", 11))
        right_panel.addWidget(self.editor)
        
        self.note_input = QLineEdit()
        btn_save = QPushButton("💾 Save Changes")
        btn_save.clicked.connect(self.update_version)
        
        nb = QHBoxLayout(); nb.addWidget(self.note_input); nb.addWidget(btn_save)
        right_panel.addLayout(nb)
        
        btn_restore = QPushButton("⏪ Restore"); btn_restore.clicked.connect(self.restore_file)
        btn_export = QPushButton("📦 Export"); btn_export.clicked.connect(self.export_version)
        btn_delete = QPushButton("🗑️ Delete Version"); btn_delete.clicked.connect(self.delete_version)
        right_panel.addWidget(btn_restore); right_panel.addWidget(btn_export); right_panel.addWidget(btn_delete)
        
        main_layout.addLayout(right_panel, 3)
        self.setCentralWidget(main_widget)

    def load_settings(self):
        config = configparser.ConfigParser()
        if os.path.exists(self.settings_file):
            config.read(self.settings_file)
            path = config.get('Settings', 'LastPath', fallback="")
            if path and os.path.exists(path): 
                self.setup_project(path)

    def save_settings(self):
        config = configparser.ConfigParser()
        config.add_section('Settings')
        config.set('Settings', 'LastPath', self.work_dir)
        with open(self.settings_file, 'w') as f:
            config.write(f)

    # --- الوظائف الأساسية للمشروع (مدمجة بالكامل من ملفك) ---
    def setup_project(self, path):
        self.work_dir = path
        self.db_path = os.path.join(path, "code.db")
        self.setWindowTitle(f"Code Archiver - {path}")
        if not os.path.exists(self.db_path): 
            self.first_time_init()
        else: 
            self.sync_files_from_folder()
            self.refresh_files()
        self.btn_sync.setEnabled(True)
        self.btn_auto_monitor.setEnabled(True)

    def sync_project(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        changed = 0
        for f_id, rel in cur.execute("SELECT id, rel_path FROM files").fetchall():
            p = os.path.join(self.work_dir, rel)
            if os.path.exists(p):
                with open(p, 'r', encoding='utf-8') as f: 
                    content = f.read()
                last = cur.execute("SELECT content FROM versions WHERE file_id=? ORDER BY stamp DESC LIMIT 1", (f_id,)).fetchone()
                if last and content != last[0]:
                    cur.execute("INSERT INTO versions (file_id, content, note, stamp) VALUES (?, ?, ?, ?)", 
                                (f_id, content, "Auto Sync", datetime.now().isoformat()))
                    changed += 1
        conn.commit()
        conn.close()
        QMessageBox.information(self, "Success", f"Sync finished. {changed} files updated.")

    def first_time_init(self):
        files = self.get_actual_files_from_folder()
        dlg = SelectionDialog(files, "Initialize Project", self)
        if dlg.exec_():
            selected = dlg.get_selected()
            conn = sqlite3.connect(self.db_path); cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, file_name TEXT, old_name TEXT, rel_path TEXT UNIQUE)")
            cur.execute("CREATE TABLE IF NOT EXISTS versions (id INTEGER PRIMARY KEY, file_id INTEGER, content TEXT, note TEXT, stamp TIMESTAMP)")
            for item in selected:
                cur.execute("INSERT INTO files (file_name, old_name, rel_path) VALUES (?, ?, ?)", (os.path.basename(item['rel']), item['old'], item['rel']))
                self.create_snapshot(cur, cur.lastrowid, item['rel'], "Initial Version")
            conn.commit(); conn.close(); self.refresh_files()

    def get_actual_files_from_folder(self):
        """قراءة جميع الملفات من المجلد الفعلي"""
        files = []
        for root, _, fs in os.walk(self.work_dir):
            for f in fs:
                if os.path.splitext(f)[1].lower() in self.text_exts and f != "code.db":
                    files.append(os.path.relpath(os.path.join(root, f), self.work_dir))
        return files

    def create_snapshot(self, cursor, f_id, rel, note):
        try:
            with open(os.path.join(self.work_dir, rel), 'r', encoding='utf-8') as f:
                cursor.execute("INSERT INTO versions (file_id, content, note, stamp) VALUES (?, ?, ?, ?)", (f_id, f.read(), note, datetime.now().isoformat()))
        except: pass

    def refresh_files(self):
        """تحديث قائمة الملفات مع الألوان حسب الحالة"""
        self.file_list.clear()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # الحصول على جميع الملفات من قاعدة البيانات
        db_files = cur.execute("SELECT id, file_name, rel_path FROM files").fetchall()
        
        # الحصول على جميع الملفات الفعلية من المجلد
        actual_files = set(self.get_actual_files_from_folder())
        
        # عرض الملفات مع الألوان
        for file_id, file_name, rel_path in db_files:
            item = QListWidgetItem(file_name)
            
            # تحديد الحالة واللون
            if rel_path in actual_files:
                # أخضر: موجود فعلياً وفي قاعدة البيانات
                item.setForeground(QColor("#27ae60"))  # أخضر
                item.setText(f"✓ {file_name}")
            else:
                # أحمر: محذوف من المجلد لكن موجود في قاعدة البيانات
                item.setForeground(QColor("#e74c3c"))  # أحمر
                item.setText(f"✗ {file_name}")
            
            # تخزين معرّف الملف في البيانات الإضافية للعنصر
            item.setData(Qt.UserRole, file_id)
            self.file_list.addItem(item)
        
        conn.close()

    def sync_files_from_folder(self):
        """مسح المجلد والمقارنة مع قاعدة البيانات، وإضافة الملفات الجديدة"""
        # الحصول على جميع الملفات من قاعدة البيانات
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        db_files = {row[0] for row in cur.execute("SELECT rel_path FROM files").fetchall()}
        conn.close()
        
        # الحصول على جميع الملفات الفعلية من المجلد
        actual_files = set(self.get_actual_files_from_folder())
        
        # إضافة الملفات الجديدة التي لم تكن موجودة في قاعدة البيانات
        new_files = actual_files - db_files
        
        if new_files:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            for rel_path in new_files:
                full_path = os.path.join(self.work_dir, rel_path)
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    file_name = os.path.basename(full_path)
                    cur.execute("INSERT INTO files (file_name, old_name, rel_path) VALUES (?, ?, ?)", 
                                (file_name, file_name, rel_path))
                    f_id = cur.lastrowid
                    
                    cur.execute("INSERT INTO versions (file_id, content, note, stamp) VALUES (?, ?, ?, ?)",
                                (f_id, content, "Discovered in folder", datetime.now().isoformat()))
                except:
                    pass
            conn.commit()
            conn.close()

    def refresh_and_update(self):
        """تحديث قاعدة البيانات بقراءة المجلد الفعلي ثم تحديث القائمة"""
        if not self.work_dir:
            QMessageBox.warning(self, "Warning", "Please open a project first.")
            return
        
        self.sync_files_from_folder()
        self.refresh_files()
        QMessageBox.information(self, "Success", "Files list updated from folder.")

    def load_history(self, item):
        # الحصول على معرّف الملف من البيانات المخزنة
        self.current_file_id = item.data(Qt.UserRole)
        if self.current_file_id:
            conn = sqlite3.connect(self.db_path)
            self.refresh_history_ui(conn.cursor())
            conn.close()

    def refresh_history_ui(self, cursor):
        self.history_table.setRowCount(0)
        data = cursor.execute("SELECT id, stamp, note FROM versions WHERE file_id=? ORDER BY stamp ASC", (self.current_file_id,)).fetchall()
        for i, (v_id, stamp, note) in enumerate(data, 1):
            self.history_table.insertRow(i-1)
            item = QTableWidgetItem(f"Ver {i} : {stamp[:16]}"); item.setData(Qt.UserRole, v_id)
            self.history_table.setItem(i-1, 0, item)
            self.history_table.setItem(i-1, 1, QTableWidgetItem(str(note)))

    def view_version(self, item):
        self.current_version_id = self.history_table.item(item.row(), 0).data(Qt.UserRole)
        conn = sqlite3.connect(self.db_path); res = conn.execute("SELECT content, note FROM versions WHERE id=?", (self.current_version_id,)).fetchone(); conn.close()
        if res: self.editor.setText(res[0]); self.note_input.setText(res[1])

    def update_version(self):
        if not self.current_version_id: 
            return
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("UPDATE versions SET content=?, note=? WHERE id=?", (self.editor.toPlainText(), self.note_input.text(), self.current_version_id))
        conn.commit()
        self.refresh_history_ui(cur)
        conn.close()
        QMessageBox.information(self, "Success", "Version updated.")

    def restore_file(self):
        if not self.current_version_id: 
            return
        if QMessageBox.question(self, 'Confirm', 'Overwrite file with this version?') == QMessageBox.No: 
            return
        conn = sqlite3.connect(self.db_path)
        content = conn.execute("SELECT content FROM versions WHERE id=?", (self.current_version_id,)).fetchone()[0]
        rel = conn.execute("SELECT rel_path FROM files WHERE id=?", (self.current_file_id,)).fetchone()[0]
        conn.close()
        with open(os.path.join(self.work_dir, rel), 'w', encoding='utf-8') as f: 
            f.write(content)
        QMessageBox.information(self, "Success", "File restored.")

    def export_version(self):
        if not self.current_version_id: 
            return
        conn = sqlite3.connect(self.db_path)
        res = conn.execute("SELECT content, file_name FROM versions JOIN files ON versions.file_id=files.id WHERE versions.id=?", (self.current_version_id,)).fetchone()
        conn.close()
        path, _ = QFileDialog.getSaveFileName(self, "Export", res[1])
        if path:
            with open(path, 'w', encoding='utf-8') as f: 
                f.write(res[0])
            QMessageBox.information(self, "Success", "File exported.")

    def delete_version(self):
        if not self.current_version_id: 
            return
        if QMessageBox.question(self, 'Confirm', 'Delete this version permanently?') == QMessageBox.No: 
            return
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM versions WHERE id=?", (self.current_version_id,))
        conn.commit()
        conn.close()
        self.current_version_id = None
        self.editor.clear()
        self.note_input.clear()
        conn = sqlite3.connect(self.db_path)
        self.refresh_history_ui(conn.cursor())
        conn.close()
        QMessageBox.information(self, "Success", "Version deleted.")

    def view_current_file(self, item=None):
        """عرض محتوى الملف الحالي من المجلد في نافذة منبثقة"""
        # إذا تم استدعاؤها من الضغط المزدوج، استخدم المعامل
        if item is not None:
            file_id = item.data(Qt.UserRole)
        else:
            file_id = self.current_file_id
        
        if not file_id:
            QMessageBox.warning(self, "Warning", "Please select a file first.")
            return
        
        # الحصول على مسار الملف
        conn = sqlite3.connect(self.db_path)
        res = conn.execute("SELECT rel_path, file_name FROM files WHERE id=?", (file_id,)).fetchone()
        conn.close()
        
        if not res:
            return
        
        rel_path, file_name = res
        full_path = os.path.join(self.work_dir, rel_path)
        
        # التحقق من وجود الملف
        if not os.path.exists(full_path):
            QMessageBox.warning(self, "Warning", f"File not found:\n{rel_path}\n\nThe file may have been deleted.")
            return
        
        # قراءة محتوى الملف الحالي
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Cannot read file:\n{str(e)}")
            return
        
        # إنشاء نافذة منبثقة
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Current Version - {file_name}")
        dialog.resize(800, 600)
        
        layout = QVBoxLayout(dialog)
        
        # محرر نصوص بدون تعديل
        editor = QTextEdit()
        editor.setText(content)
        editor.setReadOnly(True)
        editor.setFont(QFont("Consolas", 11))
        layout.addWidget(editor)
        
        # معلومات الملف
        info_label = QLabel(f"Path: {rel_path}\nSize: {len(content)} characters | {len(content.encode())} bytes")
        info_label.setStyleSheet("color: #7f8c8d; font-size: 10px;")
        layout.addWidget(info_label)
        
        # زر الإغلاق
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec_()

    def delete_file_record(self):
        """حذف قيد الملف وجميع إصداراته من قاعدة البيانات"""
        if not self.current_file_id:
            QMessageBox.warning(self, "Warning", "Please select a file first.")
            return
        
        conn = sqlite3.connect(self.db_path)
        res = conn.execute("SELECT file_name FROM files WHERE id=?", (self.current_file_id,)).fetchone()
        conn.close()
        
        if not res:
            return
        
        file_name = res[0]
        
        # تأكيد الحذف
        if QMessageBox.question(self, 'Confirm', 
                              f'Delete file record "{file_name}" and all its versions?\n\n'
                              f'The actual file will NOT be deleted from the folder.') == QMessageBox.No:
            return
        
        # حذف جميع الإصدارات أولاً
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM versions WHERE file_id=?", (self.current_file_id,))
        # ثم حذف الملف من جدول الملفات
        cur.execute("DELETE FROM files WHERE id=?", (self.current_file_id,))
        conn.commit()
        conn.close()
        
        # مسح الواجهة
        self.current_file_id = None
        self.current_version_id = None
        self.editor.clear()
        self.note_input.clear()
        self.history_table.setRowCount(0)
        
        # تحديث قائمة الملفات
        self.refresh_files()
        QMessageBox.information(self, "Success", f"File record '{file_name}' and all its versions have been deleted.")

    def show_file_context_menu(self, position):
        """عرض قائمة سياقية عند الضغط بزر الفأرة الأيمن"""
        item = self.file_list.itemAt(position)
        if not item:
            return
        
        menu = QMenu()
        action_delete = menu.addAction("🗑️ Delete File Record")
        action_delete.triggered.connect(lambda: self.delete_file_record_from_menu(item))
        menu.exec_(self.file_list.mapToGlobal(position))

    def delete_file_record_from_menu(self, item):
        """حذف قيد الملف من خلال قائمة السياق"""
        self.current_file_id = item.data(Qt.UserRole)
        self.delete_file_record()

    def calculate_diff_summary(self, old_content, new_content):
        """حساب الفرق بين محتويين وإرجاع ملخص"""
        if not old_content:
            return "Initial version"
        
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=''))
        
        added = len([l for l in diff if l.startswith('+')])
        removed = len([l for l in diff if l.startswith('-')])
        
        if added == 0 and removed == 0:
            return "No changes"
        
        summary = []
        if added > 0:
            summary.append(f"+{added}")
        if removed > 0:
            summary.append(f"-{removed}")
        
        return "Auto-saved | " + " ".join(summary) + " lines"

    def toggle_auto_monitor(self):
        """تفعيل/تعطيل المراقبة التلقائية"""
        if Observer is None:
            QMessageBox.warning(self, "Error", "watchdog library not installed.\nInstall it with: pip install watchdog")
            return
        
        if self.auto_monitor_enabled:
            # تعطيل المراقبة
            if self.observer:
                self.observer.stop()
                self.observer.join()
                self.observer = None
            self.auto_monitor_enabled = False
            self.btn_auto_monitor.setText("⏱️ Auto Monitor OFF")
            self.btn_auto_monitor.setStyleSheet("background-color: #95a5a6; color: white; height: 35px;")
            QMessageBox.information(self, "Info", "Auto monitoring disabled.")
        else:
            # تفعيل المراقبة
            self.auto_monitor_enabled = True
            self.btn_auto_monitor.setText("⏱️ Auto Monitor ON")
            self.btn_auto_monitor.setStyleSheet("background-color: #27ae60; color: white; height: 35px;")
            
            # إنشاء observer جديد
            self.observer = Observer()
            event_handler = FileWatcher(self.on_file_modified, self.on_file_created)
            self.observer.schedule(event_handler, self.work_dir, recursive=True)
            self.observer.start()
            QMessageBox.information(self, "Info", "Auto monitoring enabled.\nChanges will be saved automatically.")

    def on_file_modified(self, file_path):
        """يتم استدعاء هذه الدالة عند تعديل ملف"""
        # التحقق من أن الملف من الملفات المتتبعة
        rel_path = os.path.relpath(file_path, self.work_dir)
        ext = os.path.splitext(file_path)[1].lower()
        
        if ext not in self.text_exts or not os.path.isfile(file_path):
            return
        
        # قراءة محتوى الملف
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                new_content = f.read()
        except:
            return
        
        # البحث عن الملف في قاعدة البيانات
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        res = cur.execute("SELECT id FROM files WHERE rel_path=?", (rel_path,)).fetchone()
        
        if not res:
            conn.close()
            return
        
        f_id = res[0]
        
        # الحصول على آخر نسخة
        last_version = cur.execute("SELECT content FROM versions WHERE file_id=? ORDER BY stamp DESC LIMIT 1", (f_id,)).fetchone()
        old_content = last_version[0] if last_version else ""
        
        # تجنب حفظ نسخة إذا لم يتغير المحتوى
        if old_content == new_content:
            conn.close()
            return
        
        # حساب ملخص الفرق
        note = self.calculate_diff_summary(old_content, new_content)
        
        # حفظ النسخة الجديدة
        cur.execute("INSERT INTO versions (file_id, content, note, stamp) VALUES (?, ?, ?, ?)",
                    (f_id, new_content, note, datetime.now().isoformat()))
        conn.commit()
        conn.close()

    def on_file_created(self, file_path):
        """يتم استدعاء هذه الدالة عند إنشاء ملف جديد"""
        rel_path = os.path.relpath(file_path, self.work_dir)
        ext = os.path.splitext(file_path)[1].lower()
        
        # التحقق من أن الملف من الملفات المدعومة
        if ext not in self.text_exts or not os.path.isfile(file_path):
            return
        
        # قراءة محتوى الملف
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except:
            return
        
        # إضافة الملف إلى قاعدة البيانات
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        
        # التحقق من أن الملف ليس موجوداً بالفعل
        res = cur.execute("SELECT id FROM files WHERE rel_path=?", (rel_path,)).fetchone()
        if res:
            conn.close()
            return
        
        # إضافة الملف الجديد
        file_name = os.path.basename(file_path)
        cur.execute("INSERT INTO files (file_name, old_name, rel_path) VALUES (?, ?, ?)", 
                    (file_name, file_name, rel_path))
        f_id = cur.lastrowid
        
        # حفظ النسخة الأولى
        cur.execute("INSERT INTO versions (file_id, content, note, stamp) VALUES (?, ?, ?, ?)",
                    (f_id, content, "Auto-detected new file", datetime.now().isoformat()))
        conn.commit()
        conn.close()
        
        # تحديث قائمة الملفات في الواجهة
        self.refresh_files()

    def select_project(self):
        path = QFileDialog.getExistingDirectory(self, "Select Project Folder")
        if path: 
            self.setup_project(path)
            self.save_settings()

    def closeEvent(self, event):
        """تنظيف المراقب عند إغلاق التطبيق"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = CodeManager()
    ex.show()
    sys.exit(app.exec_())