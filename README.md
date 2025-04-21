# DeepStream Python 7.0 範例程式

此目錄包含多個範例程式，展示如何使用 GStreamer 與 Python 進行影像串流處理。以下為各範例的功能與使用說明：

---

## 1. `rtsp_to_rtsp.py`
### 功能
將 RTSP 串流轉換為另一個 RTSP 串流。

### 使用方式
```bash
python3 rtsp_to_rtsp.py --source_rtsp <來源RTSP_URL> --target_rtsp <目標RTSP_URL>
```

---

## 2. `usb_to_rtmp.py`
### 功能
將 USB 攝影機影像串流轉換為 RTMP 串流。

### 使用方式
列出所有可用的 USB 攝影機設備：
```bash
python3 usb_to_rtmp.py --list-devices
```

顯示指定設備的詳細資訊：
```bash
python3 usb_to_rtmp.py --show-device --device /dev/video0
```

將 USB 攝影機影像串流轉換為 RTMP 串流：
```bash
python3 usb_to_rtmp.py --device /dev/video0 --rtmp --rtmp_url rtmp://<RTMP_SERVER>/<STREAM_KEY> --width 640 --height 480 --fps 30
```

---

## 3. `usb_to_rtsp.py`
### 功能
將 USB 攝影機影像串流轉換為 RTSP 串流。

### 使用方式
列出所有可用的 USB 攝影機設備：
```bash
python3 usb_to_rtsp.py --list-devices
```

顯示指定設備的詳細資訊：
```bash
python3 usb_to_rtsp.py --show-device --device /dev/video0
```

將 USB 攝影機影像串流轉換為 RTSP 串流：
```bash
python3 usb_to_rtsp.py --device /dev/video0 --rtsp --rtsp_url rtsp://<RTSP_SERVER>:<PORT>/<STREAM_NAME> --width 640 --height 480 --fps 30
```

---

## 4. `usb_to_screen.py`
### 功能
將 USB 攝影機影像串流顯示於本地螢幕。

### 使用方式
列出所有可用的 USB 攝影機設備：
```bash
python3 usb_to_screen.py --list-devices
```

顯示指定設備的詳細資訊：
```bash
python3 usb_to_screen.py --show-device --device /dev/video0
```

將 USB 攝影機影像串流顯示於本地螢幕：
```bash
python3 usb_to_screen.py --device /dev/video0 --local --width 640 --height 480 --fps 30
```

---

## 注意事項
1. 確保已安裝必要的 GStreamer 插件與 Python 套件。
2. 若遇到設備無法使用，請檢查是否已正確連接並安裝驅動程式。
3. 若需進一步調整參數，請參考各程式內的說明。

Test
