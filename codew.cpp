#include <iostream>
#include <vector>
#include <string>
#include <filesystem>
#include <fstream>
#include <set>
#include <map>
#include <chrono>
#include <thread>
#include <sstream>
#include "sqlite3.h"

namespace fs = std::filesystem;
using namespace std;

const set<string> SUPPORTED_EXTS = {".php", ".ahk", ".js", ".py", ".cpp", ".h", ".c", ".sql", ".html", ".css", ".txt"};
const int CHECK_INTERVAL_SEC = 120;

class CodeWatch {
private:
    sqlite3* db;
    string db_name = "code.db";

    string read_file_content(const string& path) {
        ifstream in(path, ios::binary);
        if (!in) return "";
        return string((istreambuf_iterator<char>(in)), istreambuf_iterator<char>());
    }

    bool is_valid_text_file(const fs::path& p) {
        if (p.filename() == db_name) return false;
        if (!SUPPORTED_EXTS.count(p.extension().string())) return false;
        try { return fs::exists(p) && fs::file_size(p) > 0; } catch (...) { return false; }
    }

    void save_snapshot(int file_id, const string& path, string note) {
        string content = read_file_content(path);
        if (content.empty()) return;
        sqlite3_stmt* stmt;
        sqlite3_prepare_v2(db, "INSERT INTO versions (file_id, content, note) VALUES (?, ?, ?)", -1, &stmt, 0);
        sqlite3_bind_int(stmt, 1, file_id);
        sqlite3_bind_text(stmt, 2, content.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 3, note.c_str(), -1, SQLITE_STATIC);
        sqlite3_step(stmt);
        sqlite3_finalize(stmt);
        cout << "[SAVED] Snapshot for: " << path << endl;
    }

public:
    CodeWatch() : db(nullptr) {}
    ~CodeWatch() { if (db) sqlite3_close(db); }

    bool connect() {
        if (!fs::exists(db_name)) return false;
        return sqlite3_open(db_name.c_str(), &db) == SQLITE_OK;
    }

    void init_project() {
        sqlite3_open(db_name.c_str(), &db);
        sqlite3_exec(db, "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, rel_path TEXT UNIQUE);", 0, 0, 0);
        sqlite3_exec(db, "CREATE TABLE IF NOT EXISTS versions (id INTEGER PRIMARY KEY, file_id INTEGER, content TEXT, note TEXT, stamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP);", 0, 0, 0);

        cout << "[SCANNING] Searching files..." << endl;
        vector<fs::path> found_files;
        int idx = 1;
        for (const auto& entry : fs::recursive_directory_iterator(".")) {
            if (fs::is_regular_file(entry) && is_valid_text_file(entry.path())) {
                string rel = fs::relative(entry.path(), ".").string();
                found_files.push_back(entry.path());
                cout << "[" << idx++ << "] " << rel << endl;
            }
        }
        cout << "\nEnter numbers to archive or 'all': ";
        string input; cin.ignore(); getline(cin, input);
        if (input == "all") { for (auto& p : found_files) add_to_tracking(p); }
        else {
            stringstream ss(input); int num;
            while (ss >> num) if (num > 0 && num <= (int)found_files.size()) add_to_tracking(found_files[num - 1]);
        }
    }

    void add_to_tracking(fs::path p) {
        string rel = fs::relative(p, ".").string();
        sqlite3_stmt* stmt;
        sqlite3_prepare_v2(db, "INSERT OR IGNORE INTO files (rel_path) VALUES (?)", -1, &stmt, 0);
        sqlite3_bind_text(stmt, 1, rel.c_str(), -1, SQLITE_STATIC);
        if (sqlite3_step(stmt) == SQLITE_DONE) {
            int f_id = (int)sqlite3_last_insert_rowid(db);
            if (f_id > 0) save_snapshot(f_id, rel, "Initial version");
        }
        sqlite3_finalize(stmt);
    }

    void list_files_loop() {
        while (true) {
            sqlite3_stmt* stmt;
            sqlite3_prepare_v2(db, "SELECT id, rel_path FROM files", -1, &stmt, 0);
            vector<int> available_ids;
            cout << "\n========== ARCHIVED FILES ==========" << endl;
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                int id = sqlite3_column_int(stmt, 0);
                available_ids.push_back(id);
                string path = (const char*)sqlite3_column_text(stmt, 1);
                cout << "[" << id << "] " << (fs::exists(path) ? "[OK] " : "[MISSING] ") << path << endl;
            }
            sqlite3_finalize(stmt);

            if (available_ids.empty()) { cout << "No files archived." << endl; break; }
            cout << "------------------------------------" << endl;
            cout << "Enter File ID to see history (or 0 to back): ";
            int choice; cin >> choice;
            if (choice == 0) break;
            
            bool found = false;
            for(int id : available_ids) if(id == choice) found = true;
            if (found) manage_file_history(choice);
            else cout << "[!] Invalid ID." << endl;
        }
    }

    void manage_file_history(int file_id) {
        while (true) {
            sqlite3_stmt* stmt;
            // جلب النسخ مرتبة من الأقدم إلى الأحدث لعرضها بتسلسل منطقي
            sqlite3_prepare_v2(db, "SELECT id, stamp, note FROM versions WHERE file_id = ? ORDER BY stamp ASC", -1, &stmt, 0);
            sqlite3_bind_int(stmt, 1, file_id);
            
            cout << "\n>>> History for File ID [" << file_id << "] <<<" << endl;
            vector<int> real_db_ids; // مصفوفة لتخزين الـ ID الحقيقي
            int sequence_num = 1;

            while (sqlite3_step(stmt) == SQLITE_ROW) {
                int real_id = sqlite3_column_int(stmt, 0);
                real_db_ids.push_back(real_id);
                cout << "  Version [" << sequence_num++ << "] | " << (const char*)sqlite3_column_text(stmt, 1) 
                     << " | Note: " << (const char*)sqlite3_column_text(stmt, 2) << endl;
            }
            sqlite3_finalize(stmt);

            if (real_db_ids.empty()) { cout << "No versions found." << endl; break; }

            cout << "------------------------------------" << endl;
            cout << "Commands: restore <V_Num> | delete <V_Num> | export <V_Num> | addnote <V_Num> | 0 (back)" << endl;
            cout << "Action: ";
            string cmd; int seq_choice;
            cin >> cmd;
            if (cmd == "0") break;
            cin >> seq_choice;

            // تحويل الرقم التسلسلي الذي اختاره المستخدم إلى الـ ID الحقيقي من قاعدة البيانات
            if (seq_choice > 0 && seq_choice <= (int)real_db_ids.size()) {
                int selected_real_id = real_db_ids[seq_choice - 1];
                execute_action(cmd, selected_real_id, file_id);
            } else {
                cout << "[!] Invalid Version Number." << endl;
            }
        }
    }

    void execute_action(string cmd, int real_vid, int fid) {
        sqlite3_stmt* stmt;
        if (cmd == "restore" || cmd == "export") {
            sqlite3_prepare_v2(db, "SELECT content, (SELECT rel_path FROM files WHERE id=?) FROM versions WHERE id=?", -1, &stmt, 0);
            sqlite3_bind_int(stmt, 1, fid); sqlite3_bind_int(stmt, 2, real_vid);
            if (sqlite3_step(stmt) == SQLITE_ROW) {
                string content = (const char*)sqlite3_column_text(stmt, 0);
                string path = (cmd == "restore") ? (const char*)sqlite3_column_text(stmt, 1) : "";
                if (cmd == "export") { cout << "Enter filename for export: "; cin >> path; }
                ofstream out(path); out << content; out.close();
                cout << "[SUCCESS] Saved to: " << path << endl;
            } else { cout << "[!] Version not found." << endl; }
            sqlite3_finalize(stmt);
        } 
        else if (cmd == "delete") {
            sqlite3_prepare_v2(db, "DELETE FROM versions WHERE id=?", -1, &stmt, 0);
            sqlite3_bind_int(stmt, 1, real_vid); sqlite3_step(stmt); sqlite3_finalize(stmt);
            cout << "[DELETED] Version removed from database." << endl;
        } 
        else if (cmd == "addnote") {
            cout << "Enter new note: "; string note; cin.ignore(); getline(cin, note);
            sqlite3_prepare_v2(db, "UPDATE versions SET note=? WHERE id=?", -1, &stmt, 0);
            sqlite3_bind_text(stmt, 1, note.c_str(), -1, SQLITE_STATIC);
            sqlite3_bind_int(stmt, 2, real_vid); sqlite3_step(stmt); sqlite3_finalize(stmt);
            cout << "[UPDATED] Note updated." << endl;
        } else {
            cout << "[!] Unknown command." << endl;
        }
    }

    void run_watcher() {
        cout << "[WATCH] Started (2m interval). Ctrl+C to stop." << endl;
        map<string, string> last_content;
        while (true) {
            sqlite3_stmt* stmt;
            sqlite3_prepare_v2(db, "SELECT id, rel_path FROM files", -1, &stmt, 0);
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                int id = sqlite3_column_int(stmt, 0);
                string path = (const char*)sqlite3_column_text(stmt, 1);
                if (fs::exists(path) && fs::file_size(path) > 0) {
                    string current = read_file_content(path);
                    if (last_content.count(path) && current != last_content[path]) {
                        save_snapshot(id, path, "Auto-save");
                    }
                    last_content[path] = current;
                }
            }
            sqlite3_finalize(stmt);
            this_thread::sleep_for(chrono::seconds(CHECK_INTERVAL_SEC));
        }
    }
};

int main(int argc, char* argv[]) {
    CodeWatch app;
    string action = (argc > 1) ? argv[1] : "";
    if (action == "init") { app.init_project(); } 
    else if (action == "now") { if (app.connect()) app.run_watcher(); else app.init_project(); } 
    else if (action == "list") { if (app.connect()) app.list_files_loop(); else cout << "No DB." << endl; }
    else { cout << "Usage: codew [init | now | list]" << endl; }
    return 0;
}