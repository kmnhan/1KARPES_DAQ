# 1KARPES_DAQ
## Building
### Log viewer
```
pyinstaller logviewer.py --windowed --onefile --icon ./images/logviewer.ico --add-data="./images/logviewer.ico;./images" --add-data="logviewer.ui;." --add-data="logreader.py;." --add-data="./qt_extensions/*;./qt_extensions/"  --exclude IPython
```
