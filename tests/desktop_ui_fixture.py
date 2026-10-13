# SPDX-License-Identifier: AGPL-3.0-or-later
"""Isolated synthetic Link window for tests/packaging/desktop_ui_probe.cjs."""
import os, sys, base64
from pathlib import Path
os.environ.update(QT_QPA_PLATFORM='offscreen',QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu',ORION_MINI_TEST='1', QTWEBENGINE_REMOTE_DEBUGGING=os.environ.get('ORION_UI_DEBUG_PORT', '9467'))
from PySide6.QtCore import QTimer, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QImage, QPainter, QLinearGradient, QColor
from PySide6.QtWidgets import QApplication
import orion_mini.app as desktop
# Exercise the installed Link edition's real services in an isolated test profile.
desktop.workspace_installed=lambda:False
app=QApplication([])
root=Path(sys.argv[1]).resolve();root.mkdir(parents=True,exist_ok=True)
window=desktop.MainWindow(root,bootstrap=False)
window.resize(int(os.environ.get('ORION_UI_WIDTH',1280)),int(os.environ.get('ORION_UI_HEIGHT',850)))
w=window.workspace
w.settings['machine']['name']='Studio desktop'
w.settings['hub'].update(paired=True,base_url='http://127.0.0.1:1',device_id='desktop')
w.settings.setdefault('link',{})['camera']={'enabled':False}
w.phone.connected=True
w.phone.restore({'devices':[{'id':'phone','name':'Galaxy A55','online':True,'capabilities':['battery','photos','files'],'battery':{'battery_level':82,'is_charging':False,'updated_at':1}}], 'notifications':[]})
for i in range(15):
    width,height=(900,1500) if i%2==0 else (1600,900)
    image=QImage(width,height,QImage.Format.Format_RGB32)
    painter=QPainter(image); gradient=QLinearGradient(0,0,width,height)
    gradient.setColorAt(0,QColor('#204d67')); gradient.setColorAt(0.6,QColor('#6a7f95'));gradient.setColorAt(1,QColor('#dfb591'))
    painter.fillRect(image.rect(),gradient);painter.setBrush(QColor('#f1c899'));painter.setPen(QColor('#f1c899'));painter.drawEllipse(width//2,height//3,120,120);painter.end()
    path=root/f'Study {i+1}.jpg';image.save(str(path),'JPEG',95)
    small=image.scaled(200,200);buf=QByteArray();io=QBuffer(buf);io.open(QIODevice.WriteOnly);small.save(io,'JPEG')
    w.store.save('phone_photo',{'id':str(i),'photo_id':str(i),'device_id':'phone','name':path.name,'timestamp':i+1,'preview':'data:image/jpeg;base64,'+base64.b64encode(bytes(buf)).decode()})
    w.store.save('phone_photo_original',{'id':w.phone_features._photo_key('phone',str(i)),'path':str(path),'name':path.name,'size':path.stat().st_size})
window.show()
QTimer.singleShot(1000,lambda:window.bridge.changed.emit())
QTimer.singleShot(180000, app.quit)
print('UI_PROBE_READY',flush=True)
app.exec()
window.api.stop()
