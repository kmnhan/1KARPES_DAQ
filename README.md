# 1KARPES_DAQ
## Building
### Log viewer
```
pyinstaller ./src/logviewer.py \
    --onefile --windowed --icon src/images/logviewer.ico \
    --add-data="src/logviewer.ui;." \
    --add-data="src/logreader.py;." \
    --add-data="src/images/logviewer.ico;./images" \
    --add-data="src/qt_extensions/*;./qt_extensions/" \
    --hidden-import PyQt6 \
    --hidden-import pandas \
    --hidden-import seaborn \
    --exclude IPython --upx-dir C:\upx410w
```