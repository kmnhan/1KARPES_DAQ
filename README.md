# 1KARPES_DAQ
## Building
### Log viewer
```
pyinstaller ./src/logviewer.py --onedir --windowed `
--icon src/images/logviewer.ico `
--add-data="src/logviewer.ui;." `
--add-data="src/logreader.py;." `
--add-data="src/images/logviewer.ico;./images"` `
--add-data="src/qt_extensions/*;./qt_extensions/" `
--hidden-import PyQt6 `
--hidden-import pandas --hidden-import seaborn --exclude IPython `
--upx-dir C:\upx410w
```

### Pylon Camera Viewer
```
pyinstaller ./src/pyloncam.py --onedir --windowed `
--icon src/images/pyloncam.ico `
--add-data="src/framegrab.ui;." `
--add-data="src/images/pyloncam.ico;./images" `
--add-data="src/qt_extensions/*;./qt_extensions/" `
--hidden-import PyQt6 `
--hidden-import matplotlib `
--exclude IPython `
--upx-dir C:\upx410w
```


### Webcam Viewer
```
pyinstaller ./src/webcam.py --onedir --windowed `
--icon src/images/webcam.ico `
--add-data="src/framegrab.ui;." `
--add-data="src/images/webcam.ico;./images" `
--add-data="src/qt_extensions/*;./qt_extensions/" `
--hidden-import PyQt6 `
--exclude IPython `
--upx-dir C:\upx410w
```

