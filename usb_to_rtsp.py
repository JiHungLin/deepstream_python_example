#!/usr/bin/env python3  # 指定使用 Python3 執行
# 檔名: usb_to_rtsp.py
# 功能: 將USB網路攝影機影像串流轉成H264播放

import argparse  # 導入命令行參數處理模塊
import sys  # 導入系統功能模塊
import gi  # 導入GNOME物件內省庫
gi.require_version('Gst', '1.0')  # 設定需要的GStreamer版本
from gi.repository import Gst, GLib  # 導入GStreamer和GLib庫
import subprocess  # 導入子進程執行模塊
import re  # 導入正則表達式處理模塊

def list_all_devices():  # 定義函數用於列出所有設備
    """列出所有可用的USB攝影機設備，使用v4l2-ctl查詢"""
    
    try:  # 嘗試執行命令
        # 執行v4l2-ctl --list-devices命令
        result = subprocess.run(['v4l2-ctl', '--list-devices'],  # 執行外部命令列出設備
                               stdout=subprocess.PIPE,  # 捕獲標準輸出
                               stderr=subprocess.PIPE,  # 捕獲標準錯誤
                               text=True)  # 以文字方式返回結果
        
        if result.returncode != 0:  # 如果命令執行失敗
            print(f"v4l2-ctl命令執行失敗: {result.stderr}")  # 輸出錯誤訊息
            return []  # 返回空列表
        
        # 使用正則表達式找出所有/dev/video開頭的設備路徑
        devices = re.findall(r'/dev/video\d+', result.stdout)  # 使用正則表達式搜尋所有視訊設備
        return devices  # 返回找到的設備列表
    
    except FileNotFoundError:  # 捕獲找不到檔案的錯誤
        print("找不到v4l2-ctl工具，請先安裝v4l-utils套件")  # 提示安裝必要工具
        return []  # 返回空列表
    except Exception as e:  # 捕獲其他所有錯誤
        print(f"查詢設備時出錯: {e}")  # 輸出錯誤訊息
        return []  # 返回空列表

def show_device_capabilities(device):  # 定義函數顯示設備能力
    """顯示指定設備的詳細資訊"""
    try:  # 嘗試執行命令
        # 執行v4l2-ctl --list-formats-ext命令來獲取設備支援的格式資訊
        result = subprocess.run(['v4l2-ctl', '--device', device, '--list-formats-ext'],  # 執行外部命令列出設備格式
                               stdout=subprocess.PIPE,  # 捕獲標準輸出
                               stderr=subprocess.PIPE,  # 捕獲標準錯誤
                               text=True)  # 以文字方式返回結果
        
        if result.returncode != 0:  # 如果命令執行失敗
            print(f"無法獲取設備 {device} 的資訊: {result.stderr}")  # 輸出錯誤訊息
            return  # 函數返回
        
        # 顯示結果
        print(result.stdout)  # 輸出設備支援的格式信息
    except FileNotFoundError:  # 捕獲找不到檔案的錯誤
        print("找不到v4l2-ctl工具，請先安裝v4l-utils套件")  # 提示安裝必要工具
    except Exception as e:  # 捕獲其他所有錯誤
        print(f"查詢設備資訊時出錯: {e}")  # 輸出錯誤訊息

def main_pipeline(device, width, height, fps, bitrate, rtsp_url=None):  # 定義主要媒體處理管道函數
    """建立GStreamer管道"""
    # 初始化GStreamer
    Gst.init(None)  # 初始化GStreamer函式庫
        
    # 建立GStreamer管道
    pipeline = Gst.Pipeline()  # 創建GStreamer管道物件

    # 建立元素
    source = Gst.ElementFactory.make("v4l2src", "source")  # 創建視訊來源元素
    if not source:  # 如果元素創建失敗
        print("無法建立source元素，可能需要安裝對應的GStreamer外掛")  # 輸出錯誤訊息
        return None  # 返回空值
    source.set_property("device", device)  # 設定視訊裝置路徑
    print(f"使用設備: {device}")  # 輸出所使用的設備
    
    # 設定格式為YUY2
    capsfilter1 = Gst.ElementFactory.make("capsfilter", "capsfilter1")  # 創建格式過濾器元素
    if not capsfilter1:  # 如果元素創建失敗
        print("無法建立capsfilter元素，可能需要安裝對應的GStreamer外掛")  # 輸出錯誤訊息
        return None  # 返回空值
    caps1 = Gst.Caps.from_string(f"video/x-raw,width={width},height={height},framerate={fps}/1")  # 創建視訊格式設定
    
    capsfilter1.set_property("caps", caps1)  # 設定過濾器的格式屬性
    print(f"設定影像格式: {width}x{height}, {fps}fps")  # 輸出影像格式設定

    vidconvsrc = Gst.ElementFactory.make("videoconvert", "convertor_src1")  # 創建視訊轉換元素
    if not vidconvsrc:  # 如果元素創建失敗
        sys.stderr.write(" Unable to create videoconvert \n")  # 輸出錯誤訊息

    
    # NVIDIA影像轉換器
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "nvvidconv")  # 創建NVIDIA視訊轉換元素
    if not nvvidconv:  # 如果元素創建失敗
        print("無法建立nvvidconv元素，可能需要安裝對應的GStreamer外掛")  # 輸出錯誤訊息
        return None  # 返回空值
    
    # 嘗試使用NVIDIA硬體H264編碼器 (優先順序)
    # 1. nvv4l2h264enc - NVIDIA V4L2 based hardware encoder for Jetson
    # 2. nvh264enc - NVIDIA GPU based encoder for dGPU platforms
    # 3. x264enc - Software encoder as fallback
    encoder = Gst.ElementFactory.make("nvv4l2h264enc", "encoder")  # 嘗試創建NVIDIA V4L2 H264編碼器
    if not encoder:  # 如果元素創建失敗
        print("無法建立nvv4l2h264enc元素，嘗試使用nvh264enc...")  # 輸出錯誤訊息
        encoder = Gst.ElementFactory.make("nvh264enc", "encoder")  # 嘗試創建NVIDIA GPU H264編碼器
        if not encoder:  # 如果元素創建失敗
            print("無法建立nvh264enc元素，嘗試使用x264enc...")  # 輸出錯誤訊息
            encoder = Gst.ElementFactory.make("x264enc", "encoder")  # 嘗試創建軟體H264編碼器
            if not encoder:  # 如果元素創建失敗
                print("無法建立任何H264編碼器，請安裝所需的GStreamer外掛")  # 輸出錯誤訊息
                return None  # 返回空值
    
    # 設定編碼器參數 (根據不同編碼器調整參數)
    if encoder.get_factory().get_name() == "nvv4l2h264enc":  # 如果使用NVIDIA V4L2編碼器
        # nvv4l2h264enc 參數設定 (用於 Jetson)
        encoder.set_property("bitrate", bitrate * 1000)  # 設定比特率，單位為bits/sec
    elif encoder.get_factory().get_name() == "nvh264enc":  # 如果使用NVIDIA GPU編碼器
        # nvh264enc 參數設定 (用於 dGPU)
        encoder.set_property("bitrate", bitrate)  # 設定比特率，單位為Kbits/sec
        encoder.set_property("preset", 1)  # 設定預設值，0=慢，1=中，2=快
        encoder.set_property("rc-mode", 1)  # 設定速率控制模式，1=cbr，2=vbr
    else:  # 如果使用軟體編碼器
        # x264enc 參數設定 (軟體編碼)
        encoder.set_property("bitrate", bitrate)  # 設定比特率
        encoder.set_property("speed-preset", "medium")  # 設定速度預設為中
        encoder.set_property("tune", "zerolatency")  # 設定為零延遲優先調整


    print(f"使用 {encoder.get_factory().get_name()} 編碼器")  # 輸出所使用的編碼器名稱
    
    

    h264parser = Gst.ElementFactory.make("h264parse", "parser")  # 創建H264解析器元素
    if not h264parser:  # 如果元素創建失敗
        print("無法建立h264parse元素，可能需要安裝對應的GStreamer外掛")  # 輸出錯誤訊息
        return None  # 返回空值

    # RTSP串流
    rtsp_sink = Gst.ElementFactory.make("rtspclientsink", "rtsp_sink")  # 創建RTSP客戶端輸出元素
    if not rtsp_sink:  # 如果元素創建失敗
        print("無法建立rtspclientsink元素，可能需要安裝對應的GStreamer外掛")  # 輸出錯誤訊息
        return None  # 返回空值
    rtsp_sink.set_property("location", rtsp_url)  # 設定RTSP串流的URL位置

    # 將元素加入管道
    pipeline.add(source)  # 加入視訊來源元素到管道
    pipeline.add(capsfilter1)  # 加入格式過濾器元素到管道
    pipeline.add(vidconvsrc)  # 加入視訊轉換元素到管道
    pipeline.add(nvvidconv)  # 加入NVIDIA視訊轉換元素到管道
    pipeline.add(encoder)  # 加入編碼器元素到管道
    pipeline.add(h264parser)  # 加入H264解析器元素到管道

    # RTSP串流
    pipeline.add(rtsp_sink)  # 加入RTSP客戶端輸出元素到管道

    # 連接元素
    source.link(capsfilter1)  # 連接視訊來源到格式過濾器
    capsfilter1.link(vidconvsrc)  # 連接格式過濾器到視訊轉換
    vidconvsrc.link(nvvidconv)  # 連接視訊轉換到NVIDIA視訊轉換
    nvvidconv.link(encoder)  # 連接NVIDIA視訊轉換到編碼器
    encoder.link(h264parser)  # 連接編碼器到H264解析器

    # RTSP串流
    h264parser.link(rtsp_sink)  # 連接H264解析器到RTSP客戶端輸出
    # src_pad = h264parser.get_static_pad("src")  # 獲取H264解析器的輸出埠
    # if not src_pad:  # 如果獲取輸出埠失敗
    #     print("無法獲取h264parse的src pad")  # 輸出錯誤訊息
    #     return None  # 返回空值
    # sink_pad = rtsp_sink.get_request_pad("sink_0")  # 獲取RTSP客戶端的輸入埠
    # if not sink_pad:  # 如果獲取輸入埠失敗
    #     print("無法獲取rtspclientsink的sink pad")  # 輸出錯誤訊息
    #     return None  # 返回空值
    # if src_pad.is_linked():  # 如果輸出埠已被連接
    #     print("h264parse的src pad已經連接")  # 輸出錯誤訊息
    #     return None  # 返回空值
    # # 連接h264parse的src pad和rtspclientsink的sink pad
    # res = src_pad.link(sink_pad)  # 連接輸出埠到輸入埠
    # if res != Gst.PadLinkReturn.OK:  # 如果連接失敗
    #     print("無法連接h264parse的src pad和rtspclientsink的sink pad")  # 輸出錯誤訊息
    #     return None  # 返回空值
    # print("h264parse的src pad和rtspclientsink的sink pad已連接")  # 輸出連接成功訊息

    print("Complete pipeline for RTSP streaming")  # 輸出管道設定完成訊息
    print(f"RTSP URL: {rtsp_url}")  # 輸出RTSP URL訊息
        
    return pipeline  # 返回設定好的管道
    

def main():  # 定義主函數
    # check arguments and switch between actions(check devices, show devices details) and main
    # check if the first argument is --list-devices
    # use argparse.ArgumentParser
    parser = argparse.ArgumentParser(description="轉換USB webcam串流到RTSP或本地顯示")  # 創建命令行參數解析器
    parser.add_argument('--list-devices', action='store_true', help="列出所有可用的USB攝影機設備")  # 添加列出設備的參數
    parser.add_argument('--show-device', action='store_true', help="顯示指定設備的詳細資訊")  # 添加顯示設備詳情的參數
    parser.add_argument('--device', type=str, help="指定要使用的USB攝影機設備路徑，例如/dev/video0")  # 添加指定設備的參數
    parser.add_argument('--rtsp_url', type=str, help="指定RTSP URL")  # 添加RTSP URL的參數
    parser.add_argument('--rtsp', action='store_true', help="將串流轉換為RTSP")  # 添加RTSP轉換的參數
    parser.add_argument('--width', type=int, default=640, help="影像寬度")  # 添加寬度設定的參數
    parser.add_argument('--height', type=int, default=480, help="影像高度")  # 添加高度設定的參數
    parser.add_argument('--fps', type=int, default=30, help="影像幀率")  # 添加幀率設定的參數
    parser.add_argument('--bitrate', type=int, default=2000, help="H264編碼比特率")  # 添加比特率設定的參數

    # 如果沒有參數，顯示說明
    if len(sys.argv) == 1:  # 如果命令行參數只有程式名稱
        parser.print_help()  # 顯示幫助訊息
        return  # 函數返回

    args = parser.parse_args()  # 解析命令行參數
    
    if args.list_devices:  # 如果用戶要求列出設備
        devices = list_all_devices()  # 獲取設備列表
        if devices:  # 如果有找到設備
            print("可用的USB攝影機設備:")  # 輸出標題
            for device in devices:  # 遍歷每個設備
                print(device)  # 輸出設備路徑
        else:  # 如果沒有找到設備
            print("沒有找到可用的USB攝影機設備")  # 輸出提示訊息
        return  # 函數返回
    elif args.show_device:  # 如果用戶要求顯示設備詳情
        if args.device:  # 如果指定了設備
            print(f"顯示設備 {args.device} 的詳細資訊")  # 輸出標題
            show_device_capabilities(args.device)  # 顯示指定設備的能力
        else:  # 如果沒有指定設備
            print("錯誤: 請指定要顯示的設備路徑，例如 --device /dev/video0")  # 輸出錯誤訊息
            print("使用 -h 或 --help 參數查看完整說明")  # 輸出提示訊息
        return  # 函數返回
    
    # 檢查RTSP或本地顯示時必須指定設備
    if args.rtsp and not args.device:  # 如果要求RTSP但沒有指定設備
        print("錯誤: 使用 --rtsp 時，必須使用 --device 參數指定設備")  # 輸出錯誤訊息
        print("使用 -h 或 --help 參數查看完整說明")  # 輸出提示訊息
        return  # 函數返回
        
    # 若未指定任何操作模式
    if not args.rtsp:  # 如果沒有指定RTSP
        print("錯誤: 請指定要執行的操作 (--rtsp)")  # 輸出錯誤訊息
        print("使用 -h 或 --help 參數查看完整說明")  # 輸出提示訊息
        return  # 函數返回
    
    if args.rtsp:  # 如果用戶要求RTSP轉換
        # RTSP的實作
        pipeline = main_pipeline(args.device, args.width, args.height, args.fps, args.bitrate, rtsp_url=args.rtsp_url)  # 建立媒體處理管道
        if not pipeline:  # 如果管道建立失敗
            print("無法建立管道")  # 輸出錯誤訊息
            return  # 函數返回
        
        # 啟動管道
        pipeline.set_state(Gst.State.PLAYING)  # 設定管道開始執行
        print("開始RTSP串流...")  # 輸出開始串流訊息
        # 等待結束
        try:  # 嘗試執行
            loop = GLib.MainLoop()  # 創建主循環
            loop.run()  # 執行主循環
        except KeyboardInterrupt:  # 捕獲鍵盤中斷
            print("停止RTSP串流...")  # 輸出停止串流訊息
        finally:  # 最終執行
            pipeline.set_state(Gst.State.NULL)  # 設定管道停止
            print("管道已停止")  # 輸出管道停止訊息
    else:  # 如果不是RTSP也不是其他已知操作
        print("錯誤: 未知的操作模式")  # 輸出錯誤訊息
        print("使用 -h 或 --help 參數查看完整說明")  # 輸出提示訊息
        return  # 函數返回

        
    
if __name__ == "__main__":  # 如果程式是直接被執行而非導入
    main()  # 執行主函數

# python3 usb_to_rtsp2.py  --list-devices  # 使用範例：列出所有設備
# python3 usb_to_rtsp2.py  --show-device --device /dev/video0  # 使用範例：顯示指定設備的詳情
# python3 usb_to_rtsp2.py  --device /dev/video0 --rtsp --rtsp_url rtsp://192.168.1.222:8544/test1 --width 640 --height 480 --fps 5  # 使用範例：轉換視頻到RTSP