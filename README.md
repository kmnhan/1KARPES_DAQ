# 1KARPES_DAQ
## Building
### Log viewer
```
pyinstaller logviewer.py --windowed --onefile --icon ./images/logviewer.ico --exclude IPython --add-data="logviewer.ui;." --add-data="legendtable.py;." --add-data="logreader.py;." --add-data="./images/logviewer.ico;./images"
```