import os
import shutil
import glob

def cleanup():
    print("🧹 Cleaning up project files...")

    # Define moves: "Source File" -> "Destination Folder"
    moves = {
        "analyze_weekend.py": "scripts",
        "cleanup_md.py": "scripts",
        "test_journal.py": "tests",
        "test_telegram.py": "tests"
    }

    # Define deletions (wildcards supported)
    deletions = [
        "trades_us.log",
        ".python3.swp",
        "ta-lib-0.4.0-src.tar.gz*", # Wildcard for the zone identifier file
        "clean_project.bat" # Delete the windows script as we are replacing it
    ]

    # 1. Create Directories if not exist
    for folder in ["scripts", "tests"]:
        if not os.path.exists(folder):
            os.makedirs(folder)
            print(f"📁 Created directory: {folder}")

    # 2. Move Files
    for src, dst in moves.items():
        if os.path.exists(src):
            try:
                shutil.move(src, os.path.join(dst, src))
                print(f"✅ Moved: {src} -> {dst}/")
            except Exception as e:
                print(f"❌ Failed to move {src}: {e}")
        else:
            print(f"ℹ️  Skipped: {src} (Not found)")

    # 3. Delete Files
    for pattern in deletions:
        # Use glob for wildcards
        files = glob.glob(pattern)
        for f in files:
            try:
                os.remove(f)
                print(f"🗑️  Deleted: {f}")
            except Exception as e:
                print(f"❌ Failed to delete {f}: {e}")

    print("\n✨ Cleanup Complete!")

if __name__ == "__main__":
    cleanup()
