DISALLOWED_EXTENSIONS = (
    ".lock", ".gitignore", ".dockerignore", ".npmignore", ".yarnignore",
    ".pyc", ".pyo", ".pyd", ".pyw", ".pyz", ".pyzw",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".tiff", ".ico",
    ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv",
    ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz",
    ".exe", ".dll", ".so", ".bin", ".app", ".msi", ".deb", ".rpm",
    ".ttf", ".otf", ".woff", ".woff2",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"
)

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
MAX_FILE_LENGTH = 20000
IGNORED_DIRECTORIES = ["__pycache__", ".git", ".vscode"]
DEFAULT_ENCODING = "utf-8"
