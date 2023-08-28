# 1KARPES_DAQ
## Building
### Log viewer
```
pyinstaller ./src/logviewer.py --windowed --onefile --icon src/images/logviewer.ico --add-data="src/images/logviewer.ico;./images" --add-data="src/logviewer.ui;." --add-data="src/logreader.py;." --add-data="src/qt_extensions/*;./qt_extensions/"  --exclude IPython --upx-dir C:\upx410w
```
