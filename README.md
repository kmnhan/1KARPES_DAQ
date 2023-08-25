# 1KARPES_DAQ
## Building
### Log viewer
```
pyinstaller logviewer.py --onefile --icon ./images/logviewer.ico --exclude IPython --add-data="logviewer.ui;." --add-data="legendtable.py;." --add-data="logreader.py;."
```