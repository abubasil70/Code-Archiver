# Code Archiver (Git-Inspired Local Versioning) 📂
 Made by Gemini and claude, I was the director.
A simple, lightweight local code versioning tool designed for developers who want a "no-cloud, no-hassle" way to track their project history. 

## What is it?
This tool is inspired by Git but stripped down to the bare essentials. It creates a local `code.db` file (SQLite) inside your project directory to store every version of your files. No complex commands, just sync and archive.

## Core Features
- **Project Memory:** Remembers the last project you worked on via `settings.ini`.
- **Zero Configuration:** Just select your folder and start tracking.
- **SQLite Database:** All your history is stored in a single `code.db` file for easy portability.
- **Instant Sync:** Automatically detects changes in your files and creates backups with a single click.
- **Note Management:** Add custom notes to each backup to describe what you changed.
- **Clean UI:** Date-based version history with unique IDs for easy navigation.
- **Restore Functionality:** Accidentally broke something? Restore any previous version to the source file instantly.

## How to use
1. **Launch:** Run the script.
2. **Open Folder:** Select your project directory.
3. **Initialize:** Choose the file extensions you want to track (e.g., .py, .sql, .js).
4. **Sync:** Whenever you reach a milestone, click **Sync All Changes**.
5. **Review:** Click on any version in the history table to see the code or update its notes.
6. Watching directory and many other functions where added to the new branch.

---
**Maintained by:** Abu Basil  
**Status:** Open for contributions!
